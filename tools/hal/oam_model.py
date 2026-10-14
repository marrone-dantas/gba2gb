"""Reference model of the spatial OAM shim (runtime/gb_hal_shims.asm `Compose`) and
of the 4bpp -> 2bpp / luminance conversion, used by tests/test_oam_lockstep.py."""
from tools.hal.make_luts import gb_x, gb_y

SIZES = {(0, 0): (1, 1), (0, 1): (2, 2), (0, 2): (4, 4), (0, 3): (8, 8),
         (1, 0): (2, 1), (1, 1): (4, 1), (1, 2): (4, 2), (1, 3): (8, 4),
         (2, 0): (1, 2), (2, 1): (1, 4), (2, 2): (2, 4), (2, 3): (4, 8)}


def u16(b, o):
    return b[o] | (b[o + 1] << 8)


def compose(oam, nobj, dispcnt):
    """GBA OAM bytes -> (40 GB OAM entries (y, x, tile, flags), dropped count, per-object
    list of expected (X_gb, Y_gb) for visible objects)."""
    out, dropped, origin = [], 0, {}
    for i in range(nobj):
        a0, a1, a2 = u16(oam, 8 * i), u16(oam, 8 * i + 2), u16(oam, 8 * i + 4)
        if (a0 & 0x300) == 0x200 or (a2 & 0x300):
            continue
        w, h = SIZES.get((a0 >> 14, a1 >> 14), (1, 1))
        X, Y = gb_x(a1 & 0x1FF), gb_y(a0 & 0xFF)
        origin[i] = (X, Y)
        hf, vf = bool(a1 & 0x1000), bool(a1 & 0x2000)
        flags = (0x20 if hf else 0) | (0x40 if vf else 0) | (0x10 if a2 >> 12 else 0)
        stride = w if dispcnt & 0x40 else 32
        for r in range(h):
            for c in range(w):
                sy, sx = Y + 8 * r, X + 8 * c
                if not (9 <= sy <= 159 and 1 <= sx <= 167):
                    continue
                if len(out) == 40:
                    dropped += 1
                    continue
                tr, tc = (h - 1 - r if vf else r), (w - 1 - c if hf else c)
                out.append((sy, sx, ((a2 & 0xFF) + tr * stride + tc) & 0xFF, flags))
    return out, dropped, origin


def gb_oam_entries(oam_bytes):
    """Visible entries of the GB OAM (Y != 0), in OAM order."""
    return [tuple(oam_bytes[4 * i:4 * i + 4]) for i in range(40) if oam_bytes[4 * i] != 0]


def per_line(entries):
    """Max number of 8x8 sprites on one GB screen line."""
    cnt = [0] * 144
    for y, *_ in entries:
        for ly in range(y - 16, y - 8):
            if 0 <= ly < 144:
                cnt[ly] += 1
    return max(cnt) if cnt else 0


def level(c, obj):
    r, g, b = c & 31, (c >> 5) & 31, (c >> 10) & 31
    lv = 3 - (((r + 2 * g + b) >> 2) >> 3)
    return max(lv, 1) if obj else lv


def tile_2bpp(vram, off, levels):
    """GBA 4bpp tile at vram[off:off+32] -> 16 GB bytes."""
    out = []
    for row in range(8):
        lo = hi = 0
        for p in range(8):
            byte = vram[off + row * 4 + p // 2]
            ci = (byte >> (4 * (p & 1))) & 15
            lv = levels[ci]
            lo |= (lv & 1) << (7 - p)
            hi |= (lv >> 1) << (7 - p)
        out += [lo, hi]
    return bytes(out)


def levels_of(pal, base, obj):
    lv = [level(u16(pal, base + 2 * i), obj) for i in range(16)]
    if obj:
        bd = level(u16(pal, 0), False)   # backdrop level: equal OBJ shades are moved
        lv = [(2 if v != 2 else 3) if v == bd else v for v in lv]
        lv[0] = 0
        return lv
    l0 = lv[0]   # backdrop: GB colour 0, BGP swaps shades 0 and l0
    return [0] + [l0 if v == 0 else 0 if v == l0 else v for v in lv[1:]]
