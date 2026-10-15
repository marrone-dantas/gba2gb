"""Phase 2 build glue: classification of the accesses (intercept.py) and the extra
ROM0 sections of a HAL program (.data/.bss initialisation, ARM image for ROM loads,
compile-time HAL configuration). See docs/hal.md."""
from __future__ import annotations
import os
from elftools.elf.elffile import ELFFile
from tools.prune import range_analysis as ra
from tools.hal.intercept import classify, bg0cnt, InterceptError

ARM_IMAGE_MAX = 0x2000   # mapped at ROM0 $2000-$3FFF: $2000 | (addr & $1FFF)


class AccMap(dict):
    """Access classification {addr: Access} + .hoist (SRAM bank switches hoisted
    to loop headers, tools/sram/bank_switch.py)."""
    hoist = {}


def analyze(ssa, strict=None):
    import os
    if strict is None:
        strict = os.environ.get("GBA2GB_STRICT_PTR", "") not in ("", "0")
    acc, warnings = classify(ssa, strict=strict)
    from tools.sram.bank_switch import plan as bank_plan
    acc = AccMap(acc)
    acc.hoist, srep = bank_plan(ssa, acc, hoist=os.environ.get("GBA2GB_NO_HOIST", "") in ("", "0"))
    nobj = 0
    for a, d in acc.items():
        if d["region"] == "oam" and d["store"]:
            nobj = max(nobj, (d["const"] - 0x07000000) // 8 + 1)
    if nobj > 128:
        raise InterceptError("OAM has 128 objects")
    if any(d.get("oam") for d in acc.values()):
        nobj = max(nobj, 128)     # Phase 5 B3: pointer OAM -> full mirror
        view = 1
    else:
        view = 1 if nobj > 32 else 0
    from tools.hal.intercept import CONFIG
    cnt = bg0cnt(ssa, acc, CONFIG.get("display_bg", 0))
    oam_st = {a: d for a, d in acc.items() if d["region"] == "oam" and d["store"]}
    io_st = {a: d for a, d in acc.items() if d["region"] == "io" and d["store"]}
    return acc, {"sram": srep, "nobj": nobj, "bg0cnt": cnt, "warnings": warnings, "oam_stores": oam_st, "io_stores": io_st, "view": view}


def classify_phase0(prog):
    ssa = ra.SSAProgram(prog)
    ra.analyze(ssa)
    return analyze(ssa)


def db(data):
    return ["    db " + ", ".join(f"${b:02X}" for b in data[i:i + 32]) for i in range(0, len(data), 32)]


def hal_sections(elf_path, prog, info, affine=None):
    with open(elf_path, "rb") as fh:
        elf = ELFFile(fh)
        sec = {s.name: s for s in elf.iter_sections()}
        data = sec[".data"].data() if ".data" in sec else b""
        dvma = sec[".data"]["sh_addr"] if ".data" in sec else 0x03000000
        bss = (sec[".bss"]["sh_addr"], sec[".bss"]["sh_size"]) if ".bss" in sec else (0x03000000, 0)
        # every allocated EWRAM section (.ewram data, NOBITS .sbss / heap-start padding):
        # the SRAM banks of the whole span are cleared at boot
        ews = [(s_["sh_addr"], s_["sh_size"]) for s_ in elf.iter_sections()
               if s_["sh_flags"] & 2 and 0x02000000 <= s_["sh_addr"] < 0x02040000 and s_["sh_size"]]
        ew = (min(a for a, _ in ews), max(a + n for a, n in ews) - min(a for a, _ in ews)) if ews \
            else (0x02000000, 0)
    if ew[1] and not (0x02000000 <= ew[0] and sum(ew) <= 0x02020000):
        raise InterceptError(f"EWRAM data at {ew[0]:#x}+{ew[1]:#x} outside the 128 KiB mapped to MBC5 SRAM")
    for vma, size in ((dvma, len(data)), bss):
        if size and not (0x03000000 <= vma and vma + size <= 0x03000E00):
            raise InterceptError(f"data at {vma:#x}+{size:#x} outside the IWRAM area mapped to WRAM "
                                 "(0x03000000-0x03000DFF, docs/memory_map.md)")
    from tools.hal.intercept import CONFIG
    img = prog.img.data
    rom_sram = CONFIG["rom_sram"]
    rom_banked = CONFIG.get("rom_banked")
    if not rom_banked and (prog.img.base != 0x08000000 or (len(img) > ARM_IMAGE_MAX and not rom_sram)):
        raise InterceptError(f"ARM image of {len(img)} bytes does not fit the 8 KiB ROM0 window")
    if rom_sram:
        lim = (ew[0] - 0x02000000) if ew[1] else 0x10000
        if CONFIG["vram_shadow"]:
            lim = min(lim, 0x10000)          # banks 8-11: VRAM shadow
        if len(img) > lim:
            raise InterceptError(f"ARM image of {len(img)} bytes overlaps the SRAM banks of EWRAM / VRAM shadow")
    cnt = info["bg0cnt"] or 0
    cbb, sbb = (cnt >> 2) & 3, (cnt >> 8) & 31
    L = ['', 'SECTION "gba_init", ROM0', "GbaDataInit::"]
    if data:
        L += [f"    ld hl, ${0xC000 | (dvma & 0xFFF):04X}", "    ld de, GbaData", f"    ld bc, {len(data)}",
              ".d:", "    ld a, [de]", "    inc de", "    ld [hl+], a", "    dec bc", "    ld a, b", "    or c",
              "    jr nz, .d"]
    if bss[1]:
        L += [f"    ld hl, ${0xC000 | (bss[0] & 0xFFF):04X}", f"    ld bc, {bss[1]}", ".b:", "    xor a",
              "    ld [hl+], a", "    dec bc", "    ld a, b", "    or c", "    jr nz, .b"]
    # Phase 5 A2: enable the MBC5 SRAM (EWRAM) and clear the banks in use
    L += ["    ld a, $0A", "    ld [$0000], a"]
    end = ew[0] - 0x02000000 + ew[1]
    first = (ew[0] - 0x02000000) // 0x2000 if rom_sram else 0
    for b in range(first, (end + 0x1FFF) // 0x2000 if ew[1] else 0):
        n = min(0x2000, end - b * 0x2000)
        L += [f"    ld a, {b}", "    ld [$4000], a", "    ld hl, $A000", f"    ld bc, {n}",
              f".e{b}:", "    xor a", "    ld [hl+], a", "    dec bc", "    ld a, b", "    or c", f"    jr nz, .e{b}"]
    if rom_sram:
        # copy the ARM image (ROMX chunks of 8 KiB) to SRAM banks 0.. (ROM loads read it there)
        for k in range(0, (len(img) + 0x1FFF) // 0x2000):
            n = min(0x2000, len(img) - k * 0x2000)
            L += [f"    ld a, BANK(ArmImg{k})", "    ld [$2000], a", f"    ld a, {k}", "    ld [$4000], a",
                  f"    ld de, ArmImg{k}", "    ld hl, $A000", f"    ld bc, {n}",
                  f".i{k}:", "    ld a, [de]", "    inc de", "    ld [hl+], a", "    dec bc", "    ld a, b",
                  "    or c", f"    jr nz, .i{k}"]
        L += ["    ld a, 1", "    ld [$2000], a"]
    if CONFIG.get("port_init"):
        L += ["    call PortInit"]
    info["ewram"] = ew
    L += ["    ret", "GbaData:"] + db(data)
    view = info.get("view", 0)
    prio = (cnt or 0) & 3
    L += [f"GbaObjCount:: db {info['nobj']}", f"GbaBgCbbHi:: db ${cbb * 0x40:02X}",
          f"GbaBgSbbHi:: db ${sbb * 8:02X}", f"GbaBg0Prio:: db {prio}",
          f"GbaView:: db {view}", f"GbaShadow:: db {1 if view and not ew[1] else 0}", "GbaFollow:: db 0", "GbaPinLo:: db 66", "GbaPinHi:: db 76"]
    if rom_banked:
        L += rom_banked_sections(elf_path)
    elif rom_sram:
        for k in range(0, len(img), 0x2000):
            L += [f'SECTION "arm_image_{k // 0x2000}", ROMX', f"ArmImg{k // 0x2000}:"] + db(img[k:k + 0x2000])
    else:
        L += ['SECTION "arm_image", ROM0[$2000]', "ArmImage:"] + db(img)
    from tools.affine.affine_lut_baker import bake_program
    aff_asm, rep = bake_program(elf_path, info["oam_stores"], **(affine or {}))
    info["affine"] = rep
    from tools.audio.dsound_convert import convert_program, stub_asm
    from tools.hal.intercept import CONFIG as _cfg
    if not _cfg.get("audio", True):
        snd_asm, srep = stub_asm(), {"sfx": [], "off": True}
    elif any(d["region"] == "io" and d["store"] and d["const"] == 0x040000BC for d in info["io_stores"].values()):
        from tools.hal.gba_ref import GBARef
        ref = GBARef(elf_path)
        ref.run([0] * 400, 400)
        snd_asm, srep = convert_program(elf_path, ref.writes)
    else:
        snd_asm, srep = stub_asm(), {"sfx": []}
    info["audio"] = srep
    return "\n".join(L) + "\n" + aff_asm + snd_asm


ROMB_FIRST = 256        # first MBC5 bank of the banked GBA ROM image (HAL_ROMB_ADDR)


def rom_image(elf_path):
    """The GBA cartridge image (load addresses of all PT_LOAD segments in ROM)."""
    with open(elf_path, "rb") as fh:
        elf = ELFFile(fh)
        segs = [(sg["p_paddr"], sg.data()) for sg in elf.iter_segments()
                if sg["p_type"] == "PT_LOAD" and 0x08000000 <= sg["p_paddr"] < 0x0A000000 and sg["p_filesz"]]
    end = max(a + len(d) for a, d in segs) - 0x08000000
    img = bytearray(end)
    for a, d in segs:
        img[a - 0x08000000:a - 0x08000000 + len(d)] = d
    return bytes(img)


def rom_banked_sections(elf_path):
    """ROMX sections at banks ROMB_FIRST.. holding the GBA ROM image (INCBIN of a file
    written next to the system temp directory, keyed by the image hash)."""
    import hashlib, tempfile
    img = rom_image(elf_path)
    if len(img) > 0x400000:
        raise InterceptError(f"GBA ROM image of {len(img)} bytes: rom_banked supports up to 4 MiB")
    path = os.path.join(tempfile.gettempdir(), f"gba2gb_rom_{hashlib.sha1(img).hexdigest()[:16]}.bin")
    if not os.path.exists(path):
        with open(path + ".tmp", "wb") as fh:
            fh.write(img)
        os.replace(path + ".tmp", path)
    L = []
    for k in range(0, len(img), 0x4000):
        n = min(0x4000, len(img) - k)
        L += [f'SECTION "gba_rom_{k >> 14}", ROMX[$4000], BANK[{ROMB_FIRST + (k >> 14)}]',
              f'    INCBIN "{path}", {k}, {n}']
    return L
