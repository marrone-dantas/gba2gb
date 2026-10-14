"""Phase 2 build glue: classification of the accesses (intercept.py) and the extra
ROM0 sections of a HAL program (.data/.bss initialisation, ARM image for ROM loads,
compile-time HAL configuration). See docs/hal.md."""
from __future__ import annotations
from elftools.elf.elffile import ELFFile
from tools.prune import range_analysis as ra
from tools.hal.intercept import classify, bg0cnt, InterceptError

ARM_IMAGE_MAX = 0x2000   # mapped at ROM0 $2000-$3FFF: $2000 | (addr & $1FFF)


def analyze(ssa):
    acc, warnings = classify(ssa)
    nobj = 0
    for a, d in acc.items():
        if d["region"] == "oam" and d["store"]:
            nobj = max(nobj, (d["const"] - 0x07000000) // 8 + 1)
    if nobj > 32:
        raise InterceptError("objects >= 32 are not supported by the GBA OAM mirror")
    cnt = bg0cnt(ssa, acc)
    return acc, {"nobj": nobj, "bg0cnt": cnt, "warnings": warnings}


def classify_phase0(prog):
    ssa = ra.SSAProgram(prog)
    ra.analyze(ssa)
    return analyze(ssa)


def db(data):
    return ["    db " + ", ".join(f"${b:02X}" for b in data[i:i + 32]) for i in range(0, len(data), 32)]


def hal_sections(elf_path, prog, info):
    with open(elf_path, "rb") as fh:
        elf = ELFFile(fh)
        sec = {s.name: s for s in elf.iter_sections()}
        data = sec[".data"].data() if ".data" in sec else b""
        dvma = sec[".data"]["sh_addr"] if ".data" in sec else 0x03000000
        bss = (sec[".bss"]["sh_addr"], sec[".bss"]["sh_size"]) if ".bss" in sec else (0x03000000, 0)
    for vma, size in ((dvma, len(data)), bss):
        if size and not (0x03000000 <= vma and vma + size <= 0x03000E00):
            raise InterceptError(f"data at {vma:#x}+{size:#x} outside the IWRAM area mapped to WRAM "
                                 "(0x03000000-0x03000DFF, docs/memory_map.md)")
    img = prog.img.data
    if prog.img.base != 0x08000000 or len(img) > ARM_IMAGE_MAX:
        raise InterceptError(f"ARM image of {len(img)} bytes does not fit the 8 KiB ROM0 window")
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
    L += ["    ret", "GbaData:"] + db(data)
    L += [f"GbaObjCount:: db {info['nobj']}", f"GbaBgCbbHi:: db ${cbb * 0x40:02X}",
          f"GbaBgSbbHi:: db ${sbb * 8:02X}"]
    L += ['SECTION "arm_image", ROM0[$2000]', "ArmImage:"] + db(img)
    return "\n".join(L) + "\n"
