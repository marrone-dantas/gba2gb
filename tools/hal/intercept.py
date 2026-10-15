"""Static I/O interceptor (Phase 2.1).

Every memory access of the lifted program is classified at compile time from the
proven ranges of its address operands (range analysis + pointer induction below):

| region | ARM range | requirement | GB lowering |
|---|---|---|---|
| ram  | 0x02000000-0x03FFFFFF (and unknown pointers, C semantics) | - | WRAM window |
| io   | 0x04000000-0x040003FF | constant address | shim call |
| pal  | 0x05000000-0x050003FF | stores only | luminance shim |
| vram | 0x06000000-0x06017FFF | stores only | 4bpp->2bpp shim |
| oam  | 0x07000000-0x070003FF | constant address | GBA OAM mirror (inline) |
| rom  | 0x08000000-0x09FFFFFF | loads only | ARM image copy in ROM0 |

An access whose address range intersects the I/O or OAM regions without being a
single constant, or that mixes regions, is a compile error (`InterceptError`, all
offending PCs listed). Pointers with no known range at all (TOP: stack pointers,
pointers loaded from memory) get their region from pointer provenance through
registers and stack slots (tools/hal/provenance.py); when that is unknown the
access is dispatched at run time on the address (region "dyn"), or rejected in
strict mode. (Before Phase 5 they were silently assumed to be RAM.)

Pointer induction: a phi `p = phi(C0, p + k)` (or `stmia p!`) whose loop exits on
`cmp p', B` + `bne`/`beq`, with constants C0 < B and (B - C0) % k == 0, ranges over
[C0, B] (gives the region of memcpy-style loops).
"""
from __future__ import annotations
from tools.prune import range_analysis as ra

REGIONS = [("io", 0x04000000, 0x040003FF), ("pal", 0x05000000, 0x050003FF),
           ("vram", 0x06000000, 0x06017FFF), ("oam", 0x07000000, 0x070003FF),
           ("rom", 0x08000000, 0x09FFFFFF), ("ewram", 0x02000000, 0x0201FFFF),
           ("ram", 0x03000000, 0x03FFFFFF)]
SRAM_BANK = 0x2000      # Phase 5 A2: EWRAM -> MBC5 SRAM, bank = (addr >> 13) & 15
# Large homebrew images (docs/homebrew_port.md): CONFIG["rom_sram"] copies the ARM image to
# SRAM banks 0.. at boot and turns ROM loads into SRAM loads (same bank formula as
# EWRAM, so EWRAM data must then live above the image, e.g. 0x02018000 = bank 12);
# CONFIG["vram_shadow"] keeps a copy of GBA VRAM 0x06000000-0x06007FFF (BG tiles/maps)
# in SRAM banks 8-11 so the game can read its BG maps back (region "vsh").
# CONFIG["audio"] False: the audio subsystem is removed (tools/audio/strip.py); sound
# and FIFO-DMA register writes are dropped by the backend.
CONFIG = {"rom_sram": False, "vram_shadow": False, "audio": True}


def ewram_bank(lo, hi):
    """Compile-time SRAM bank of an EWRAM (or SRAM-copied ROM) access range, or None if
    it spans banks."""
    base = 0x08000000 if lo >= 0x08000000 else 0x02000000
    b0, b1 = (lo - base) // SRAM_BANK, (hi - base) // SRAM_BANK
    return (b0 & 15) if b0 == b1 else None


def remap(reg, st):
    """Region after the large-image options (rom -> ewram, vram load -> vsh)."""
    if reg == "rom" and not st and CONFIG["rom_sram"]:
        return "ewram"
    if reg == "vram" and not st and CONFIG["vram_shadow"]:
        return "vsh"
    return reg
WIDTH = {"": 4, "b": 1, "h": 2, "sb": 1, "sh": 2}
SWIS = {5: "VBlankIntrWait"}
IO_NAMES = {0x000: "DISPCNT", 0x004: "DISPSTAT", 0x006: "VCOUNT", 0x008: "BG0CNT", 0x00A: "BG1CNT",
            0x010: "BG0HOFS", 0x012: "BG0VOFS", 0x130: "KEYINPUT", 0x200: "IE",
            0x202: "IF", 0x208: "IME", 0x100: "TM0CNT_L", 0x102: "TM0CNT_H",
            0x104: "TM1CNT_L", 0x106: "TM1CNT_H"}
IO_READ = {0x006, 0x100, 0x104, 0x130}                 # registers with a read shim
IO_WRITE = {0x000, 0x004, 0x008, 0x00A, 0x010, 0x012, 0x100, 0x102, 0x104, 0x106, 0x200, 0x202, 0x208}


class InterceptError(Exception):
    pass


def _const(v):
    return v is not None and v.proven is not None and v.proven[0] == v.proven[1]


def pointer_induction(ssa):
    """phi value -> (lo, hi) for monotonic pointer loops (see module docstring)."""
    out = {}
    cmps = []  # (value compared, constant bound, address)
    for a, env in ssa.envs.items():
        x = ssa.prog.ins[a]
        if x.op == "cmp" and isinstance(x.a, str):
            va = env.get(int(x.a[1:]))
            if isinstance(x.b, str):
                vb = env.get(int(x.b[1:]))
                if _const(vb):
                    cmps.append((va, vb.proven[0], a))
            elif isinstance(x.b, int):
                cmps.append((va, x.b, a))
    for v in ssa.values:
        if v.kind != "phi" or len(v.args) != 2:
            continue
        init = [a for a in v.args.values() if _const(a)]
        back = [a for a in v.args.values() if not _const(a)]
        if len(init) != 1 or len(back) != 1:
            continue
        c0, u = init[0].proven[0], back[0]
        while u.kind == "pi":
            u = u.env["x"]
        k = None
        if u.kind == "ins" and u.ins.op == "add" and isinstance(u.ins.b, int) and \
                u.env.get(int(u.ins.a[1:])) is v:
            k = u.ins.b
        elif u.kind == "ins" and u.ins.op in ("ldm", "stm") and u.ins.wb and u.reg == u.ins.rd and \
                u.env.get(u.ins.rd) is v:
            k = 4 * len(u.ins.regs)
        if not k or k <= 0:
            continue
        for va, bound, a in cmps:
            nxt = ssa.prog.ins.get(a + ssa.prog.ins[a].size)
            if va is u and nxt is not None and nxt.op == "bcc" and nxt.cond in ("ne", "eq") \
                    and bound > c0 and (bound - c0) % k == 0:
                out[v] = (c0, bound)
                out[u] = (c0 + k, bound)
    return out


def interval(v, ind):
    if v is None:
        return None
    while v.kind == "pi" and v not in ind:
        v = v.env["x"]
    if v in ind:
        return ind[v]
    if v.proven is None or (v.proven[0] == 0 and v.proven[1] == ra.M32):
        return None
    return v.proven[0], v.proven[1]


def region_of(lo, hi):
    for name, a, b in REGIONS:
        if a <= lo and hi <= b:
            return name
    return None


def classify(ssa, strict=False):
    """Returns ({addr: Access}, {"swi": {addr: n}}, warnings). Access = dict(region,
    const address or None, width, store?).

    Pointers without a proven range get their address space from pointer
    provenance (tools/hal/provenance.py, through stack slots). If that is unknown
    too, the access becomes region "dyn" (runtime address-space dispatch,
    HAL_DYN_ADDR / HAL_DYN_STORE) or, with strict=True, a compile error."""
    from tools.hal.provenance import Provenance
    ind = pointer_induction(ssa)
    prov = Provenance(ssa, ind)

    def unknown(a, x, env, base, idx, st, n):
        reg = prov.region(env, base, idx)
        if reg is None:
            if strict:
                errors.append(f"{a:#010x}: {x.text}: pointer of unknown address space (strict mode)")
                return None
            return "dyn"
        if reg == "oam":
            return "dyn:oam"        # Phase 5 B3: OAM through a pointer -> run-time dispatch to the mirror
        reg = remap(reg, st)
        if (reg == "rom" and st) or (reg in ("pal", "vram") and not st) or reg == "io":
            errors.append(f"{a:#010x}: {x.text}: {reg} access through a non-constant pointer not supported")
            return None
        return reg
    acc, errors, warnings = {}, [], []
    for a, x in sorted(ssa.prog.ins.items()):
        if x.op == "swi":
            if x.a not in SWIS:
                errors.append(f"{a:#010x}: unsupported BIOS call swi {x.a}")
            continue
        if x.op in ("ldm", "stm") and x.rd != 13:
            env = ssa.envs.get(a, {})
            iv = interval(env.get(x.rd), ind)
            reg = region_of(iv[0], iv[1] + 4 * len(x.regs) - 1) if iv else \
                unknown(a, x, env, x.rd, None, x.op == "stm", 4)
            if iv and reg:
                reg = remap(reg, x.op == "stm")
            if reg is None and not iv:
                continue
            if iv and reg is None:
                errors.append(f"{a:#010x}: {x.text}: address range {iv[0]:#x}-{iv[1]:#x} spans regions")
                continue
            if reg and reg.split(":")[0] not in ("ram", "rom", "vram", "dyn", "ewram", "vsh") or (reg == "rom" and x.op == "stm") or \
                    (reg == "vram" and x.op == "ldm"):
                errors.append(f"{a:#010x}: {x.text}: {reg} block transfer not supported")
                continue
            acc[a] = {"region": reg.split(":")[0], "const": None, "width": 4, "store": x.op == "stm", "oam": reg == "dyn:oam"}
            if reg == "ewram":
                acc[a]["bank"] = ewram_bank(iv[0], iv[1] + 4 * len(x.regs) - 1) if iv else None
            continue
        if x.mem is None:
            continue
        base, idx, disp = x.mem
        if base == 15:
            continue
        env = ssa.envs.get(a, {})
        n = WIDTH[x.op[3:]]
        ib = interval(env.get(base), ind)
        ii = (0, 0) if idx is None else interval(env.get(idx), ind)
        if base == 13:
            acc[a] = {"region": "ram", "const": None, "width": n, "store": x.op.startswith("str")}
            continue
        if ib is None or ii is None:
            reg = unknown(a, x, env, base, idx, x.op.startswith("str"), n)
            if reg is not None:
                acc[a] = {"region": reg.split(":")[0], "const": None, "width": n, "store": x.op.startswith("str"), "oam": reg == "dyn:oam"}
                if reg == "ewram":
                    acc[a]["bank"] = None
            continue
        lo, hi = ib[0] + ii[0] + disp, ib[1] + ii[1] + disp + n - 1
        reg = region_of(lo, hi)
        st = x.op.startswith("str")
        const = lo if hi - lo == n - 1 else None
        if reg is None:
            touches = any(lo <= b and a0 <= hi for nm, a0, b in REGIONS if nm in ("io", "oam"))
            if touches or (lo >= 0x02000000 and hi < 0x0A000000):
                errors.append(f"{a:#010x}: {x.text}: unresolvable address range {lo:#x}-{hi:#x}")
                continue
            reg = "ram"
        if reg == "oam" and const is None:
            # Phase 5 B3: OAM indexed by a loop / pointer -> run-time dispatch to the mirror
            acc[a] = {"region": "dyn", "const": None, "width": n, "store": st, "oam": True}
            continue
        reg = remap(reg, st)
        if reg == "io" and const is None:
            errors.append(f"{a:#010x}: {x.text}: non-constant {reg.upper()} address {lo:#x}-{hi:#x}")
            continue
        if (reg == "rom" and st) or (reg in ("pal", "vram") and not st):
            errors.append(f"{a:#010x}: {x.text}: {'store to ROM' if st else 'read of ' + reg.upper()} not supported")
            continue
        if reg == "io":
            off = const - 0x04000000
            known = IO_WRITE if st else IO_READ
            if off not in known:
                warnings.append(f"{a:#010x}: {x.text}: I/O register {off:#05x} "
                                f"{'write ignored' if st else 'read returns 0'}")
        acc[a] = {"region": reg, "const": const, "width": n, "store": st}
        if reg == "ewram":
            acc[a]["bank"] = ewram_bank(lo, hi)
    if errors:
        raise InterceptError("unresolvable or unsupported accesses:\n  " + "\n  ".join(errors))
    return acc, warnings


def bg0cnt(ssa, acc, bg=0):
    """Compile-time value of BG0CNT (needed to route VRAM writes to tiles or map); a port
    displaying another layer (CONFIG["display_bg"]) uses that layer's BGxCNT instead."""
    vals = set()
    for a, d in acc.items():
        if d["region"] == "io" and d["store"] and d["const"] == 0x04000008 + 2 * bg:
            v = ssa.envs[a].get(ssa.prog.ins[a].rd)
            if not _const(v):
                raise InterceptError(f"{a:#010x}: BG{bg}CNT written with a non-constant value")
            vals.add(v.proven[0])
    if len(vals) > 1:
        raise InterceptError(f"BG{bg}CNT written with several values: {sorted(vals)}")
    return vals.pop() if vals else None
