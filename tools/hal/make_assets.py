"""Generate tests/demos/assets.h: procedural 4bpp tiles, palettes and the brin map
for the Phase 2 demos (original artwork; nothing is copied from Tonc)."""


def rgb(r, g, b):
    return r | (g << 5) | (b << 10)


def tiles_from_pixels(px, w, h):
    """px[y][x] = 4-bit index -> list of u32 words, 1D tile order (row-major tiles)."""
    words = []
    for ty in range(h // 8):
        for tx in range(w // 8):
            for r in range(8):
                v = 0
                for p in range(8):
                    v |= (px[ty * 8 + r][tx * 8 + p] & 15) << (4 * p)
                words.append(v)
    return words


def obj32():
    px = [[0] * 32 for _ in range(32)]
    for y in range(32):
        for x in range(32):
            d2 = (x - 15.5) ** 2 + (y - 15.5) ** 2
            if 2 <= x <= 29 and 2 <= y <= 29 and (x in (2, 29) or y in (2, 29)):
                px[y][x] = 3            # box
            elif d2 < 11 ** 2:
                px[y][x] = 2            # body
                if d2 > 9 ** 2:
                    px[y][x] = 3        # outline
            if (x - 11) ** 2 + (y - 12) ** 2 < 6 or (x - 20) ** 2 + (y - 12) ** 2 < 6:
                px[y][x] = 1            # eyes
            if y > 22 and x in (9, 15, 16, 22) and d2 < 13 ** 2:
                px[y][x] = 3            # legs (asymmetric under flips)
    return px


def obj16():
    px = [[0] * 16 for _ in range(16)]
    for y in range(16):
        for x in range(16):
            if abs(x - 7.5) + abs(y - 7.5) < 7:
                px[y][x] = 2 if abs(x - 7.5) + abs(y - 7.5) < 5 else 3
    px[3][3] = 1
    return px


def ship32():
    """Asymmetric 32x32 'ship' for the affine demo (rotation must be visible)."""
    px = [[0] * 32 for _ in range(32)]
    for y in range(32):
        for x in range(32):
            # arrow pointing right: triangle body + tail fin + cockpit
            if 6 <= x <= 27 and abs(y - 15.5) <= (27 - x) * 0.45 + 1:
                px[y][x] = 2 if abs(y - 15.5) <= (27 - x) * 0.45 - 1 else 3
            if 4 <= x <= 10 and 4 <= y <= 9:
                px[y][x] = 3            # top fin only (breaks the mirror symmetry)
    for y in range(13, 19):
        for x in range(16, 21):
            px[y][x] = 1                # cockpit
    return px


def sin_lut():
    import math
    return [int(round(256 * math.sin(2 * math.pi * i / 256))) & 0xFFFF for i in range(256)]


def sfx_zap(fs=8192, dur=0.3):
    """Original SFX: descending chirp with decay, 8-bit signed PCM at 8192 Hz."""
    import math
    n = int(fs * dur) // 32 * 32
    out, ph = [], 0.0
    for i in range(n):
        t = i / fs
        f = 1800 * (1 - t / dur) + 250
        ph += 2 * math.pi * f / fs
        env = (1 - t / dur) ** 1.5
        v = math.sin(ph) * 0.8 + (0.2 if math.sin(ph * 0.5) > 0 else -0.2)
        out.append(int(max(-127, min(127, round(110 * env * v)))) & 0xFF)
    while len(out) % 4:
        out.append(0)
    return out


def key_tiles():
    out = []
    for st in range(4):  # up, hit, released, held
        px = [[0] * 8 for _ in range(8)]
        for y in range(8):
            for x in range(8):
                edge = x in (0, 7) or y in (0, 7)
                if st == 0:
                    px[y][x] = 2 if edge else 0
                elif st == 1:
                    px[y][x] = 3 if edge or x == y or x == 7 - y else 0
                elif st == 2:
                    px[y][x] = 1 if edge or (x % 2 == 0 and y % 2 == 0) else 0
                else:
                    px[y][x] = 3 if edge else 2
        out += tiles_from_pixels(px, 8, 8)
    return out


def brin():
    tiles = []
    for t in range(16):
        px = [[0] * 8 for _ in range(8)]
        for y in range(8):
            for x in range(8):
                mortar = y in (0, 4) or (x == (0 if y < 4 else 4))
                px[y][x] = 3 if mortar else (1 + ((x + y + t) // 3) % 2 + (t % 2)) % 4
                if t == 0:
                    px[y][x] = 0        # sky
                if t == 15 and (x + y) % 4 == 0:
                    px[y][x] = 3
        tiles += tiles_from_pixels(px, 8, 8)
    m = []
    for y in range(32):
        for x in range(32):
            if y < 8 + (x * 7 % 5) or (12 < y < 16 and 10 < x < 22):
                m.append(0)
            else:
                m.append(1 + (x * 3 + y * 5) % 15)
    return tiles, m


def arr(name, typ, vals, fmt="0x{:08X}"):
    body = ",".join((fmt.format(v) + ("\n    " if i % 8 == 7 else "")) for i, v in enumerate(vals))
    return f"static const {typ} {name}[{len(vals)}] = {{\n    {body}\n}};\n"


def main():
    pal0 = [0, rgb(31, 31, 24), rgb(12, 20, 8), rgb(4, 4, 8)] + [rgb(i, i, i) for i in range(4, 16)]
    pal1 = [0, rgb(4, 4, 8), rgb(31, 16, 16), rgb(31, 31, 31)] + [rgb(i, i, i) for i in range(4, 16)]
    otiles = tiles_from_pixels(obj32(), 32, 32) + tiles_from_pixels(obj16(), 16, 16)
    kpal = [0, rgb(31, 31, 0), rgb(16, 16, 16), rgb(31, 0, 0)] + [rgb(0, 24, 0)] * 12
    bt, bm = brin()
    bpal = [rgb(20, 26, 31), rgb(24, 12, 6), rgb(14, 8, 4), rgb(3, 2, 2)] + [rgb(i, i, i) for i in range(4, 16)]
    s = ["/* Generated by tools/hal/make_assets.py — do not edit. */", "#ifndef ASSETS_H", "#define ASSETS_H"]
    s.append(arr("obj_pal", "u16", pal0 + pal1, "0x{:04X}"))
    s.append(f"#define OBJ_TILE_WORDS {len(otiles)}")
    s.append(arr("obj_tiles", "u32", otiles))
    s.append(arr("key_pal", "u16", kpal, "0x{:04X}"))
    kt = key_tiles()
    s.append(f"#define KEY_TILE_WORDS {len(kt)}")
    s.append(arr("key_tiles", "u32", kt))
    s.append(arr("brin_pal", "u16", bpal, "0x{:04X}"))
    s.append(f"#define BRIN_TILE_WORDS {len(bt)}")
    s.append(arr("brin_tiles", "u32", bt))
    s.append(arr("brin_map", "u16", bm, "0x{:04X}"))
    st = tiles_from_pixels(ship32(), 32, 32)
    s.append(f"#define SHIP_TILE_WORDS {len(st)}")
    s.append(arr("ship_tiles", "u32", st))
    s.append(arr("sin_lut", "s16", sin_lut(), "(s16)0x{:04X}"))
    z = sfx_zap()
    s.append(f"#define SFX_LEN {len(z)}")
    s.append("__attribute__((aligned(4)))")
    s.append(arr("sfx_zap", "u8", z, "0x{:02X}"))
    s.append("#endif")
    print("\n".join(s))


if __name__ == "__main__":
    main()
