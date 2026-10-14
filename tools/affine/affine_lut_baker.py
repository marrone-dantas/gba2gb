"""Phase 4.1: affine OBJ baker (docs/affine.md).

The DMG has no affine sprites. For a program that rotates/scales an OBJ through an
affine matrix, this tool

1. detects affine OBJ usage: OBJ_AFFINE parameter writes (OAM offsets 6 mod 8,
   resolved at compile time by the static I/O interceptor) and the OAM affine flag
   (attr0 bit 8) of the objects seen in a short GBA reference run;
2. bakes NROT rotations x the configured scales of the sprite's tiles offline with
   the exact GBA affine sampling rule, converts them to 2bpp and packs them into
   dedicated MBC5 ROM banks;
3. emits the runtime: a 4096-entry ROMX LUT maps the quantised (pa, pb) pair to a
   frame number in O(1) (HAL_AFFINE_SEL, called by the translated code after each
   pa/pb write in place of a matrix), and either
   - resident mode: all frames fit OBJ VRAM, copied once at boot; selecting a frame
     is a tile-index swap, or
   - stream mode: two VRAM slots; the VBlank ISR copies CHUNK bytes per VBlank of
     the selected frame from ROMX into the back slot and flips slots when complete.

Only pa and pb are used (rotation + uniform scale, pa = cos/s, pb = -sin/s)."""
from __future__ import annotations
import argparse
import json
import math

from tools.hal.gba_ref import GBARef, OBJ_SIZES, obj_pixels, affine_sample, u16
from tools.hal.oam_model import levels_of

LUT_BANK = 2
FRAME_BANK0 = 3


class AffineError(Exception):
    pass


# ---------------------------------------------------------------- detection
def detect(acc):
    """Affine parameter writes found by the interceptor: {group: [(pc, param), ...]}."""
    out = {}
    for pc, d in acc.items():
        if d["region"] == "oam" and d["store"]:
            o = d["const"] - 0x07000000
            if o % 8 == 6:
                out.setdefault(o // 32, []).append((pc, "pa pb pc pd".split()[(o % 32) // 8]))
    return out


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def affine_objects(snap):
    """Objects with the OAM affine flag set: [(obj, group, w, h, tile, double)]."""
    oam, out = snap["oam"], []
    for i in range(128):
        a0, a1, a2 = u16(oam, 8 * i), u16(oam, 8 * i + 2), u16(oam, 8 * i + 4)
        if a0 & 0x100:
            w, h = OBJ_SIZES[(a0 >> 14, a1 >> 14)]
            out.append((i, (a1 >> 9) & 31, w, h, a2 & 0x3FF, bool(a0 & 0x200)))
    return out


# ---------------------------------------------------------------- selection model
def q(v, shift):
    v >>= shift
    return max(-32, min(31, v)) & 63


def frame_for(pa, pb, nrot, scales):
    """Nearest baked (rotation, scale) frame for a matrix with pa = cos/s, pb = -sin/s."""
    r = math.hypot(pa, pb)
    if r < 1e-6:
        return 0
    k = int(round(math.atan2(-pb, pa) / (2 * math.pi / nrot))) % nrot
    s = 256.0 / r
    j = min(range(len(scales)), key=lambda i: abs(math.log(scales[i] / s)))
    return k + nrot * j


def build_lut(nrot, scales, shift):
    lut = bytearray(4096)
    for qa in range(64):
        for qb in range(64):
            va = ((qa - 64 if qa >= 32 else qa) << shift) + (1 << shift) // 2
            vb = ((qb - 64 if qb >= 32 else qb) << shift) + (1 << shift) // 2
            lut[qa * 64 + qb] = frame_for(va, vb, nrot, scales)
    return bytes(lut)


def select(pa, pb, lut, shift):
    """Exact model of HAL_AFFINE_SEL."""
    return lut[q(s16(pa), shift) * 64 + q(s16(pb), shift)]


def choose_shift(scales):
    m = 256.0 / min(scales)
    for sh in range(2, 8):
        if m / (1 << sh) <= 32:
            return sh
    raise AffineError("scales too small")


# ---------------------------------------------------------------- baking
def matrix(k, s, nrot):
    a = 2 * math.pi * k / nrot
    c, n = math.cos(a) / s, math.sin(a) / s
    return [int(round(256 * c)), int(round(-256 * n)), int(round(256 * n)), int(round(256 * c))]


def to_2bpp(px, w, h, levels):
    out = bytearray()
    for ty in range(h // 8):
        for tx in range(w // 8):
            for r in range(8):
                lo = hi = 0
                for p in range(8):
                    lv = levels[px[ty * 8 + r][tx * 8 + p]]
                    lo |= (lv & 1) << (7 - p)
                    hi |= (lv >> 1) << (7 - p)
                out += bytes((lo, hi))
    return bytes(out)


def bake(src, w, h, levels, nrot, scales):
    """-> list of frames (2bpp, 1D tile order), index = k + nrot * scale_index, plus
    the colour-index images (for tests/screenshots)."""
    frames, imgs = [], []
    for s in scales:
        for k in range(nrot):
            P = matrix(k, s, nrot)
            img = [[affine_sample(src, w, h, P, x, y) for x in range(w)] for y in range(h)]
            imgs.append(img)
            frames.append(to_2bpp(img, w, h, levels))
    return frames, imgs


# ---------------------------------------------------------------- plan + asm
def plan(nframes, tpf, prog_tiles, chunk=128, mode="auto"):
    """Resident if every frame fits the OBJ tiles left after the program's own tiles."""
    base = -(-prog_tiles // 16) * 16
    fb = tpf * 16
    if mode in ("auto", "resident") and base + nframes * tpf <= 256:
        return {"mode": "resident", "base": base, "tpf": tpf, "frame_bytes": fb}
    if mode == "resident":
        raise AffineError(f"{nframes} frames x {tpf} tiles do not fit OBJ VRAM from tile {base}")
    chunk = min(chunk, fb)
    if 256 % chunk or fb % chunk:
        raise AffineError("chunk must divide 256 and the frame size")
    s1 = 256 - tpf
    s1 -= s1 % max(1, chunk // 16)
    s0 = s1 - tpf
    s0 -= s0 % max(1, chunk // 16)
    if s0 < base:
        raise AffineError("not enough OBJ VRAM for two stream slots")
    return {"mode": "stream", "slots": [s0, s1], "tpf": tpf, "frame_bytes": fb, "chunk": chunk,
            "chunks": fb // chunk, "base": base}


def db(data):
    return ["    db " + ", ".join(f"${b:02X}" for b in data[i:i + 32]) for i in range(0, len(data), 32)]


def clamp_macro():
    return """MACRO AFF_CLAMP          ; hl (signed) -> a = clamp(hl, -32, 31) & 63
    bit 7, h
    jr nz, .n\\@
    ld a, h
    or a
    jr nz, .p\\@
    ld a, l
    cp 32
    jr c, .ok\\@
.p\\@:
    ld a, 31
    jr .ok\\@
.n\\@:
    ld a, h
    inc a
    jr nz, .m\\@
    ld a, l
    cp $E0
    jr nc, .ok\\@
.m\\@:
    ld a, $E0
.ok\\@:
    and 63
ENDM
"""


def stub_asm():
    return """
SECTION "affine_stub", ROM0
HAL_AFFINE_SEL::
AffInit::
AffStream::
    ret
"""


def emit_asm(group, frames, lut, shift, p):
    """Runtime + data for one affine group."""
    fb = p["frame_bytes"]
    per_bank = 16384 // fb
    if 16384 % fb:
        raise AffineError("frame size must divide 16 KiB")
    pa_off, pb_off = 32 * group + 6, 32 * group + 14
    L = [clamp_macro(), 'SECTION "affine_rt", ROM0']
    # O(1) selection: called after each pa / pb write
    L += ["HAL_AFFINE_SEL::"]
    for off, reg in ((pa_off, "d"), (pb_off, "e")):
        L += [f"    ld a, [wGbaOAM + {off}]", "    ld l, a", f"    ld a, [wGbaOAM + {off + 1}]", "    ld h, a"]
        L += ["    sra h", "    rr l"] * shift
        L += ["    AFF_CLAMP", f"    ld {reg}, a"]
    L += ["    ld a, d", "    rrca", "    rrca", "    ld b, a", "    and $0F", "    or $40", "    ld h, a",
          "    ld a, b", "    and $C0", "    or e", "    ld l, a",
          "    di", f"    ld a, {LUT_BANK}", "    ld [$2000], a", "    ld b, [hl]"]
    if p["mode"] == "resident":
        L += ["    ld h, $50", "    ld l, b", "    ld a, [hl]", "    ld [wAffTile], a"]
    L += ["    ld a, [wRomBank]", "    ld [$2000], a", "    ei", "    ld a, b", "    ld [wAffWant], a"]
    if p["mode"] == "resident":
        L += ["    ld [wAffHave], a"]
    L += ["    ret", ".end::"]
    # frame source tables
    nf = len(frames)
    L += ["AffSrcBank:"] + db([FRAME_BANK0 + f // per_bank for f in range(nf)])
    L += ["AffSrcLo:"] + db([((f % per_bank) * fb) & 0xFF for f in range(nf)])
    L += ["AffSrcHi:"] + db([0x40 + (((f % per_bank) * fb) >> 8) for f in range(nf)])
    # boot copy (LCD off): b = frame, de = VRAM destination; copies one frame
    L += ["AffCopyFrame:", "    ld c, b", "    ld b, 0", "    ld hl, AffSrcBank", "    add hl, bc",
          "    ld a, [hl]", "    ld [$2000], a", "    ld hl, AffSrcLo", "    add hl, bc", "    ld a, [hl]",
          "    push af", "    ld hl, AffSrcHi", "    add hl, bc", "    ld h, [hl]", "    pop af", "    ld l, a",
          f"    ld bc, {fb}", ".c:", "    ld a, [hl+]", "    ld [de], a", "    inc de", "    dec bc", "    ld a, b",
          "    or c", "    jr nz, .c", "    ld a, [wRomBank]", "    ld [$2000], a", "    ret"]
    if p["mode"] == "resident":
        base = p["base"]
        L += ["AffInit::", "    ld de, $%04X" % (0x8000 + 16 * base), "    xor a", ".f:", "    push af",
              "    ld b, a", "    call AffCopyFrame", "    pop af", "    inc a", f"    cp {nf}", "    jr nz, .f",
              f"    ld a, {base}", "    ld [wAffTile], a", "    xor a", "    ld [wAffWant], a",
              "    ld [wAffHave], a", "    ret",
              "AffStream::", "    ret"]
        res = bytes((base + f * p["tpf"]) & 0xFF for f in range(nf)) + bytes(256 - nf)
    else:
        s0, s1 = p["slots"]
        L += ["AffInit::", "    ld de, $%04X" % (0x8000 + 16 * s0), "    ld b, 0", "    call AffCopyFrame",
              f"    ld a, {s0}", "    ld [wAffTile], a", "    ld [wAffUsed], a", "    ld [wAffShown], a",
              f"    ld a, {s1}", "    ld [wAffBack], a",
              "    xor a", "    ld [wAffWant], a", "    ld [wAffHave], a", "    ld [wAffLeft], a", "    ret"]
        L += ["; VBlank ISR part (af saved by the ISR): CHUNK bytes of the wanted frame per VBlank",
              "AffStream::", "    push bc", "    ld a, [wAffLeft]", "    or a", "    jr nz, .go", "    ld a, [wAffWant]",
              "    ld b, a", "    ld a, [wAffHave]", "    cp b", "    jp z, .idle",
              "    ld a, [wAffShown]", "    ld c, a", "    ld a, [wAffTile]", "    cp c",
              "    jp nz, .idle          ; hardware OAM still shows the back slot", ".go:",
              "    push de", "    push hl", "    ld a, [wAffLeft]", "    or a", "    jr nz, .cont",
              "    ld a, b", "    ld [wAffCur], a", "    ld c, a", "    ld b, 0", "    ld hl, AffSrcLo",
              "    add hl, bc", "    ld a, [hl]", "    ld [wAffSrc], a", "    ld hl, AffSrcHi", "    add hl, bc",
              "    ld a, [hl]", "    ld [wAffSrc + 1], a", "    ld a, [wAffBack]", "    ld l, a", "    ld h, 0",
              "    add hl, hl", "    add hl, hl", "    add hl, hl", "    add hl, hl", "    ld a, l",
              "    ld [wAffDst], a", "    ld a, h", "    or $80", "    ld [wAffDst + 1], a",
              f"    ld a, {p['chunks']}", "    ld [wAffLeft], a",
              ".cont:", "    ld a, [wAffCur]", "    ld c, a", "    ld b, 0", "    ld hl, AffSrcBank",
              "    add hl, bc", "    ld a, [hl]", "    ld [$2000], a", "    ld a, [wAffSrc]", "    ld l, a",
              "    ld a, [wAffSrc + 1]", "    ld h, a", "    ld a, [wAffDst]", "    ld e, a", "    ld a, [wAffDst + 1]",
              "    ld d, a", ".cp::", f"    REPT {p['chunk']}", "    ld a, [hl+]", "    ld [de], a", "    inc e",
              "    ENDR", ".cpend::", "    ld a, e", "    or a", "    jr nz, .nd", "    inc d", ".nd:",
              "    ld a, l", "    ld [wAffSrc], a", "    ld a, h", "    ld [wAffSrc + 1], a", "    ld a, e",
              "    ld [wAffDst], a", "    ld a, d", "    ld [wAffDst + 1], a", "    ld a, [wRomBank]", "    ld [$2000], a",
              "    ld hl, wAffLeft", "    dec [hl]", "    jr nz, .out", "    ld a, [wAffBack]",
              "    ld [wAffTile], a", f"    xor {s0 ^ s1}", "    ld [wAffBack], a", "    ld a, [wAffCur]",
              "    ld [wAffHave], a", ".out:", "    pop hl", "    pop de", "    pop bc", "    ret", ".idle:",
              "    pop bc", "    ret", ".end::"]
        res = bytes(256)
    L += [f'SECTION "affine_lut", ROMX[$4000], BANK[{LUT_BANK}]', "AffLut::"] + db(lut)
    L += [f'SECTION "affine_res", ROMX[$5000], BANK[{LUT_BANK}]', "AffRes::"] + db(res)
    for b in range(-(-nf // per_bank)):
        chunk = b"".join(frames[b * per_bank:(b + 1) * per_bank])
        L += [f'SECTION "affine_frames_{b}", ROMX[$4000], BANK[{FRAME_BANK0 + b}]'] + db(chunk)
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- driver
def bake_program(elf, acc, nrot=32, scales=(1.0, 2.0), chunk=128, mode="auto", ref_frames=4):
    """Full pipeline for one ELF: returns (asm, report)."""
    groups = detect(acc)
    if not groups:
        return stub_asm(), {"affine": False}
    if len(groups) > 1:
        raise AffineError(f"affine groups {sorted(groups)}: only one affine group is supported")
    g = next(iter(groups))
    snaps = GBARef(elf).run([0] * (ref_frames + 1), ref_frames)
    s = snaps[-1]
    objs = [o for o in affine_objects(s) if o[1] == g]
    if not objs:
        raise AffineError(f"OBJ_AFFINE group {g} is written but no object has the affine flag")
    if any(o[5] for o in objs):
        raise AffineError("double-size affine objects are not supported (docs/affine.md)")
    shapes = {(o[2], o[3], o[4]) for o in objs}
    if len(shapes) > 1:
        raise AffineError("objects sharing an affine group must share size and tiles")
    w, h, tile = shapes.pop()
    oned = bool(u16(s["io"], 0) & 0x40)
    src = obj_pixels(s["vram"], tile, w, h, oned)
    levels = levels_of(s["pal"], 0x200, True)
    frames, _ = bake(src, w, h, levels, nrot, list(scales))
    used = [t for t in range(1024) if any(s["vram"][0x10000 + 32 * t:0x10020 + 32 * t])]
    prog_tiles = (max(used) + 1) if used else 0
    p = plan(len(frames), (w // 8) * (h // 8), prog_tiles, chunk, mode)
    shift = choose_shift(scales)
    lut = build_lut(nrot, list(scales), shift)
    rep = {"affine": True, "group": g, "objects": [o[0] for o in objs], "size": [w, h], "src_tile": tile,
           "param_writes": [[f"{pc:#x}", n] for pc, n in sorted(groups[g])], "nrot": nrot,
           "scales": list(scales), "shift": shift, "frames": len(frames), "rom_bytes": len(frames) * p["frame_bytes"],
           "banks": [LUT_BANK] + list(range(FRAME_BANK0, FRAME_BANK0 + -(-len(frames) * p["frame_bytes"] // 16384))),
           **p}
    rep["_lut"], rep["_levels"], rep["_src"] = lut, levels, src
    return emit_asm(g, frames, lut, shift, p), rep


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("elf")
    ap.add_argument("--rot", type=int, default=32)
    ap.add_argument("--scales", default="1,2")
    ap.add_argument("--chunk", type=int, default=128)
    ap.add_argument("--mode", default="auto", choices=["auto", "resident", "stream"])
    a = ap.parse_args()
    import os
    import tempfile
    from tools.backend.gba2gbc_core import build
    opts = {"nrot": a.rot, "scales": [float(x) for x in a.scales.split(",")], "chunk": a.chunk, "mode": a.mode}
    with tempfile.TemporaryDirectory() as td:
        prog = build(a.elf, os.path.join(td, "out.gbc"), entry="main", prune="sound", hal=True, affine=opts)
    rep = prog.hal_info["affine"]
    print(json.dumps({k: v for k, v in rep.items() if not k.startswith("_")}, indent=1))


if __name__ == "__main__":
    main()
