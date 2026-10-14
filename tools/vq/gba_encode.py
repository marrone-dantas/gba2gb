"""Encode RGBA background layers into a GBA mode-0 snapshot (inverse of the dumper).

Used to build the scene dataset from pixel art and as a round-trip test of the
dumper. Each layer is an RGBA image of a text-BG size (256/512 x 256/512); alpha < 128
is transparent. Colours are rounded to BGR555. Tiles are deduplicated including
h/v flips. 4bpp is used when every tile fits a 15-colour bank (banks are packed
first-fit from bank 15 downwards), otherwise 8bpp. VRAM layout: layer i tiles in
CBB i (i < 3; 4bpp <= 512 tiles, 8bpp <= 256), screen blocks from SBB 24 up (CBB 3)."""
import numpy as np
from .snapshot import make

SIZE_CODE = {(256, 256): 0, (512, 256): 1, (256, 512): 2, (512, 512): 3}


def to555(rgb):
    rgb = np.asarray(rgb, np.int32)
    q = (rgb * 31 + 127) // 255
    return q[..., 0] | (q[..., 1] << 5) | (q[..., 2] << 10)


class EncodeError(Exception):
    pass


def _tiles(cidx):
    h, w = cidx.shape
    return cidx.reshape(h // 8, 8, w // 8, 8).transpose(0, 2, 1, 3)


def encode(layers, backdrop=(0, 0, 0), name="", solid=None, **meta):
    """layers: list (BG0 first) of dicts: rgba (uint8 [h, w, 4]), prio (0-3),
    hofs, vofs, optional bpp8 (force), optional solid (bool [h/8, w/8] cells).
    -> snapshot dict (tools/vq/snapshot.py)."""
    if len(layers) > 3:
        raise EncodeError("at most 3 layers (CBB 3 holds the maps)")
    vram = np.zeros(0x18000, np.uint8)
    pal = np.zeros(256, np.int32)
    pal[0] = to555(np.array(backdrop))
    io = np.zeros(0x60, np.uint8)
    used8 = set()
    free_bank = 15
    dispcnt = 0
    sbb = 24
    snap_solid = {}
    infos = []
    for n, L in enumerate(layers):
        rgba = np.asarray(L["rgba"], np.uint8)
        h, w = rgba.shape[:2]
        if (w, h) not in SIZE_CODE:
            raise EncodeError(f"layer {n}: size {w}x{h}")
        col = to555(rgba[..., :3])
        col = np.where(rgba[..., 3] >= 128, col, -1)
        tiles = _tiles(col)
        ty, tx = tiles.shape[:2]
        # palette: try 4bpp banks
        sets = {}
        for y in range(ty):
            for x in range(tx):
                cs = frozenset(int(c) for c in np.unique(tiles[y, x]) if c >= 0)
                sets.setdefault(cs, []).append((y, x))
        bpp8 = L.get("bpp8", False) or any(len(cs) > 15 for cs in sets)
        banks = []
        if not bpp8:
            for cs in sorted(sets, key=len, reverse=True):
                for b in banks:
                    if len(b | cs) <= 15:
                        b |= cs
                        break
                else:
                    banks.append(set(cs))
            if len(banks) > free_bank + 1 or used8 & set(range(16 * (free_bank + 1 - len(banks)), 16 * (free_bank + 1))):
                bpp8 = True
        lut = {}
        if bpp8:
            colours = sorted({int(c) for c in np.unique(col) if c >= 0})
            free = [i for i in range(1, 16 * (free_bank + 1)) if i not in used8]
            if len(colours) > len(free):
                raise EncodeError(f"layer {n}: {len(colours)} colours, {len(free)} palette entries free")
            for c, i in zip(colours, free):
                pal[i] = c
                used8.add(i)
                lut[c] = i
            cell_bank = None
        else:
            bank_ids = []
            for b in banks:
                if any(i in used8 for i in range(16 * free_bank, 16 * free_bank + 16)):
                    raise EncodeError("palette full")
                for k, c in enumerate(sorted(b)):
                    pal[16 * free_bank + 1 + k] = c
                bank_ids.append(free_bank)
                free_bank -= 1
            cell_bank = {}
            for cs, cells in sets.items():
                bi = next(i for i, b in enumerate(banks) if cs <= b)
                for c in cells:
                    cell_bank[c] = (bank_ids[bi], {cc: 1 + k for k, cc in enumerate(sorted(banks[bi]))})
        # tiles
        dic, entries = {}, np.zeros((ty, tx), np.int32)
        tdata = []
        for y in range(ty):
            for x in range(tx):
                t = tiles[y, x]
                if bpp8:
                    idx = np.vectorize(lambda c: lut.get(int(c), 0))(t) if t.max() >= 0 else np.zeros((8, 8), int)
                    pb = 0
                else:
                    pb, m = cell_bank[(y, x)]
                    idx = np.vectorize(lambda c: m.get(int(c), 0))(t)
                idx = idx.astype(np.uint8)
                for fl, v in ((0, idx), (1, idx[:, ::-1]), (2, idx[::-1, :]), (3, idx[::-1, ::-1])):
                    k = v.tobytes()
                    if k in dic:
                        entries[y, x] = dic[k] | (fl << 10) | (pb << 12)
                        break
                else:
                    dic[idx.tobytes()] = len(tdata)
                    entries[y, x] = len(tdata) | (pb << 12)
                    tdata.append(idx)
        limit = 256 if bpp8 else 512
        if len(tdata) > limit:
            raise EncodeError(f"layer {n}: {len(tdata)} unique tiles > {limit}")
        base = n * 0x4000
        for i, t in enumerate(tdata):
            if bpp8:
                vram[base + 64 * i: base + 64 * i + 64] = t.reshape(-1)
            else:
                f = t.reshape(-1)
                vram[base + 32 * i: base + 32 * i + 32] = (f[0::2] & 15) | ((f[1::2] & 15) << 4)
        nblk = (w // 256) * (h // 256)
        for y in range(ty):
            for x in range(tx):
                blk = sbb + x // 32 + (y // 32) * (w // 256)
                a = blk * 0x800 + 2 * ((y % 32) * 32 + x % 32)
                vram[a] = entries[y, x] & 255
                vram[a + 1] = entries[y, x] >> 8
        cnt = (L.get("prio", n) & 3) | (n << 2) | (0x80 if bpp8 else 0) | (sbb << 8) | (SIZE_CODE[(w, h)] << 14)
        io[8 + 2 * n], io[9 + 2 * n] = cnt & 255, cnt >> 8
        for k, v in ((0x10, L.get("hofs", 0)), (0x12, L.get("vofs", 0))):
            io[k + 4 * n], io[k + 4 * n + 1] = v & 255, (v >> 8) & 1
        if L.get("solid") is not None:
            flags = np.zeros(1024, np.uint8)
            sm = np.asarray(L["solid"], bool)
            for y in range(ty):
                for x in range(tx):
                    if sm[y, x]:
                        flags[entries[y, x] & 0x3FF] = 1
            # a tile number shared by solid and non-solid cells is flagged solid
            snap_solid[n] = flags
        dispcnt |= 0x100 << n
        sbb += nblk
        infos.append({"bpp8": bpp8, "tiles": len(tdata)})
    io[0], io[1] = dispcnt & 255, dispcnt >> 8
    palb = np.zeros(0x400, np.uint8)
    palb[0:512:2], palb[1:512:2] = pal & 255, pal >> 8
    s = make(vram.tobytes(), palb.tobytes(), io.tobytes(), solid=snap_solid, name=name, **meta)
    s["_info"] = infos
    return s
