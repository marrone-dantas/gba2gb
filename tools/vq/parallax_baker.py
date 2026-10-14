"""Phase 3.4: parallax baker. Two GBA layers scrolling at different speeds -> one DMG BG.

The DMG has a single opaque BG layer, so the near layer (GBA BGs with prio < far, merged)
and the far layer are composited offline. With near scroll x and far scroll r*x (r = 1/2
by default) the far layer is displaced by d = x - r*x pixels relative to the near tile
grid. d mod 8 is the *phase* p (8 phases), d div 8 the coarse offset k. For every phase
the composite tiles of all (cell, k) are quantized to the 4 DMG levels (shared edge-aware
cuts) and deduplicated; the codebook is shared by all phases (the DMG cannot reload a
4 KiB codebook within a frame) and, if the union exceeds K, vector-quantized to K with
solid near tiles pinned. Each (p, k) gets a 32 x rows tilemap; tilemaps of one phase are
packed into MBC5 16 KiB ROM banks, so a phase switch at runtime = select the ROM bank of
(p, k) and copy one tilemap (to the hidden BG map, then flip LCDC.3).

    python -m tools.vq.parallax_baker SCENE [--far 2] [--ratio 0.5] [--out DIR]
writes codebook.2bpp, bank_NNN.bin, layout.json and pressure.json."""
import argparse
import json
import os
import numpy as np
from .snapshot import load
from .vram_scene_dumper import render_map, bg_params, visible_bgs
from .vq_tile_compiler import luminance, edge_aware_cuts, quantize_thresholds, vq, encode_2bpp

BANK = 0x4000


def layers_from_snapshot(s, far_bg=None):
    bgs, _ = visible_bgs(s)
    prm = {n: bg_params(s, n) for n in bgs}
    if far_bg is None:                                     # lowest priority BG = far
        far_bg = max(bgs, key=lambda n: (prm[n]["prio"], n))
    near_bgs = sorted((n for n in bgs if n != far_bg), key=lambda n: (prm[n]["prio"], n), reverse=True)
    _, _, far = render_map(s, far_bg)
    near = None
    solid = None
    for n in near_bgs:                                     # back to front
        _, ent, rgba = render_map(s, n)
        if near is None:
            near = np.zeros_like(rgba)
            solid = np.zeros(rgba.shape[:2], bool)
        m = rgba[..., 3] > 0
        near[m] = rgba[m]
        f = s.get(f"solid_bg{n}")
        if f is not None:
            solid |= np.asarray(f, bool)[ent & 0x3FF] & m
    return near, solid, far, prm[near_bgs[-1]]["vofs"], prm[far_bg]["vofs"]


def bake(scene, far_bg=None, ratio=0.5, rows=18, k=256, seed=0):
    s = load(scene) if isinstance(scene, str) else scene
    near, solid, far, vofs_n, vofs_f = layers_from_snapshot(s, far_bg)
    nh, nw = near.shape[:2]
    fh, fw = far.shape[:2]
    y0 = vofs_n + 8                                        # 144 of the 160 visible rows
    ys = (np.arange(rows * 8) + y0) % nh
    yf = (np.arange(rows * 8) + vofs_f + 8) % fh
    nY = luminance(near[ys][..., :3])
    nA = near[ys][..., 3] > 0
    nS = solid[ys]
    fY = luminance(far[yf][..., :3])
    cw = nw // 8
    ncoarse = fw // 8

    def composite(d):
        cols = (np.arange(nw) - d) % fw
        return np.where(nA, nY, fY[:, cols])

    sample = np.concatenate([composite(d) for d in (0, 3, 5)], 1)
    th, centres = edge_aware_cuts(sample, np.concatenate([nS] * 3, 1))
    tiles = {}                                             # (p, k) -> level tiles (cells, 64)
    for p in range(8):
        for kk in range(ncoarse):
            q = quantize_thresholds(composite(8 * kk + p), th)
            tiles[p, kk] = q.reshape(rows, 8, cw, 8).transpose(0, 2, 1, 3).reshape(-1, 64)
    cell_solid = nS.reshape(rows, 8, cw, 8).mean((1, 3)).reshape(-1) > 0.5
    allt = np.concatenate([tiles[p, kk] for p in range(8) for kk in range(ncoarse)])
    allsolid = np.concatenate([cell_solid] * (8 * ncoarse))
    uniq, inv, cnt = np.unique(allt, axis=0, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    per_phase = {}
    ncell = rows * cw
    for p in range(8):
        sl = slice(p * ncoarse * ncell, (p + 1) * ncoarse * ncell)
        per_phase[p] = int(len(np.unique(inv[sl])))
    usolid = np.bincount(inv, allsolid, len(uniq)) > 0
    if len(uniq) <= k:
        cb, assign, exact = uniq.astype(np.uint8), np.arange(len(uniq)), True
    else:
        pin = np.flatnonzero(usolid)
        w = cnt * (1 + 8.0 * usolid)
        if len(pin) > 0.75 * k:
            pin = pin[np.argsort(-w[pin])][:int(0.75 * k)]
        cb, assign = vq(uniq.astype(np.float32), w, k, pin.tolist(), seed)
        exact = False
    gb = assign[inv].astype(np.uint8)
    maps = {}
    for i, (p, kk) in enumerate((p, kk) for p in range(8) for kk in range(ncoarse)):
        maps[p, kk] = gb[i * ncell:(i + 1) * ncell].reshape(rows, cw)
    err = float(((cb[assign].astype(int) - uniq) ** 2 * cnt[:, None]).sum() / cnt.sum() / 64)
    pressure = {"scene": s.get("name", ""), "ratio": ratio, "phases": 8, "coarse_offsets": ncoarse,
                "map": [rows, cw], "unique_tiles_per_phase": per_phase,
                "unique_tiles_union": int(len(uniq)), "k": k, "codewords": int(len(cb)),
                "pressure_union": round(len(uniq) / k, 3), "exact": exact,
                "solid_unique": int(usolid.sum()), "tile_mse_levels": err,
                "static_unique_tiles_d0": int(len(np.unique(tiles[0, 0], axis=0)))}
    return {"codebook": cb, "maps": maps, "pressure": pressure, "thresholds": th, "centres": centres,
            "composite": composite, "rows": rows, "cw": cw, "ncoarse": ncoarse}


def export(res, out):
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "codebook.2bpp"), "wb").write(encode_2bpp(res["codebook"]))
    msize = res["rows"] * res["cw"]
    per_bank = BANK // msize
    layout, bank, buf = {}, 1, bytearray()
    for p in range(8):
        for kk in range(res["ncoarse"]):
            if len(buf) + msize > BANK or (kk == 0 and buf and len(buf) + res["ncoarse"] * msize > BANK and False):
                open(os.path.join(out, f"bank_{bank:03d}.bin"), "wb").write(bytes(buf))
                bank, buf = bank + 1, bytearray()
            layout[f"{p},{kk}"] = [bank, 0x4000 + len(buf)]
            buf += res["maps"][p, kk].tobytes()
    open(os.path.join(out, f"bank_{bank:03d}.bin"), "wb").write(bytes(buf))
    info = dict(res["pressure"], rom_banks=bank, maps_per_bank=per_bank, map_bytes=msize,
                tilemap_rom_bytes=8 * res["ncoarse"] * msize)
    json.dump(layout, open(os.path.join(out, "layout.json"), "w"))
    json.dump(info, open(os.path.join(out, "pressure.json"), "w"), indent=1)
    return info


def phase_of(x, ratio=0.5, fw=256):
    d = int(x - int(x * ratio)) % fw
    return d % 8, d // 8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--far", type=int, default=None)
    ap.add_argument("--ratio", type=float, default=0.5)
    ap.add_argument("--out", default="build/vq/parallax")
    a = ap.parse_args()
    print(json.dumps(export(bake(a.scene, a.far, a.ratio), a.out)))


if __name__ == "__main__":
    main()
