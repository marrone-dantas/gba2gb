"""Phase 3.3: VQ tile compiler, GBA scene -> DMG 2bpp tile bank + tilemap.

    python -m tools.vq.vq_tile_compiler SCENE [--out DIR] [--k 256] [--reserve 0]
        [--dither] [--levels adaptive|uniform] [--fov scroll|downscale|crop] [--crop X,Y]

Pipeline
 1. scene: tools/vq/vram_scene_dumper.dump(snapshot) -> 240x160 composite + solid mask.
 2. field of view (240x160 -> DMG 160x144):
      scroll    (default) keep every pixel and the 8x8 grid: a 30x20 tile map (fits the
                32x32 GB map); the 160x144 screen is a window moved with SCX/SCY.
      downscale resample to 160x144 (aspect 1.5 -> 1.11; Lanczos on luminance), 20x18 map.
      crop      static 160x144 window at --crop X,Y (multiples of 8 keep the GBA grid).
 3. luminance Y = 0.299 R + 0.587 G + 0.114 B, quantized to 4 levels (0 = white ... 3 =
    black, DMG BGP identity). adaptive (default): 1-D k-means on the scene's luminance
    histogram; uniform: 4 equal bins. Optional ordered Bayer 2x2 dithering between
    neighbouring levels (non-solid cells only). Solid (collision) cells use edge-preserving
    local levels (solid_local_levels): visibly different colours of a solid tile never merge.
 4. codebook: unique 8x8 level tiles. If more than K (= 256 - reserve, reserve = tiles kept
    for sprites/HUD), weighted k-means++ + Lloyd (PyTorch, CPU) on the tiles with weight
    count * (1 + a * Sobel saliency + b * solid); solid (collision) tiles are pinned as exact
    codewords while they fit in pin_frac * K; then VQ refinement: codewords snapped to
    integer levels, tiles reassigned, codewords re-estimated (round of the weighted mean is
    the optimal integer under squared error), until stable.
 5. export: tiles.2bpp (GB format, codeword i = GB tile reserve + i), tilemap.bin (one byte
    per cell, row-major, width w), classes.bin (uint16 source-cell class per map cell),
    lut_tile_remap.bin (uint8 GB tile per source class: the runtime remap table, one page
    per 256 classes), compile.json (parameters and statistics)."""
import argparse
import json
import os
import numpy as np
import torch
from .snapshot import load
from .vram_scene_dumper import dump

MIN_GAP = 0.12
BAYER2 = np.array([[0, 2], [3, 1]]) / 4.0 + 0.125 - 0.5      # -0.375 .. 0.375


def luminance(rgb):
    rgb = np.asarray(rgb, np.float64) / 255.0
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def sobel_mag(y):
    p = np.pad(y, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    return np.hypot(gx, gy) / 4.0


def apply_fov(rgb, solid, fov, crop=(40, 8)):
    if fov == "scroll":
        return rgb, solid
    if fov == "crop":
        x, y = crop
        return rgb[y:y + 144, x:x + 160], solid[y:y + 144, x:x + 160]
    if fov == "downscale":
        from PIL import Image
        r = np.asarray(Image.fromarray(rgb).resize((160, 144), Image.LANCZOS))
        s = np.asarray(Image.fromarray(solid.astype(np.uint8) * 255).resize((160, 144), Image.NEAREST)) > 0
        return r, s
    raise ValueError(fov)


def level_centres(y, mode):
    """4 luminance centres, brightest first (level 0 = white)."""
    if mode == "uniform":
        return np.array([7, 5, 3, 1]) / 8.0
    v = np.sort(y.reshape(-1))
    c = np.quantile(v, [0.875, 0.625, 0.375, 0.125])
    for _ in range(50):
        lab = np.argmin(np.abs(v[:, None] - c[None, :]), 1)
        nc = np.array([v[lab == i].mean() if (lab == i).any() else c[i] for i in range(4)])
        if np.allclose(nc, c):
            break
        c = nc
    c = np.sort(c)[::-1]
    # keep the levels distinguishable: centres at least MIN_GAP apart (k-means can
    # collapse or crowd levels in scenes with few or similar luminances)
    for _ in range(200):
        moved = False
        for i in range(3):
            d = c[i] - c[i + 1]
            if d < MIN_GAP - 1e-9:
                m = (c[i] + c[i + 1]) / 2
                c[i], c[i + 1] = m + MIN_GAP / 2, m - MIN_GAP / 2
                moved = True
        if c[0] > 1:
            c -= c[0] - 1
        if c[3] < 0:
            c -= c[3]
        if not moved:
            break
    return c


def edge_aware_cuts(y, solid, t=0.05, max_bins=96, edge_w=50.0):
    """Edge-aware 4-level partition of the scene's luminances (mode "edge", default).

    The distinct luminances (binned to at most max_bins) are split into 4 contiguous
    groups (level 0 = brightest) by an exhaustive search over the 3 cut points that
    minimises  SSE(luminance vs group mean)  +  edge_w * (number of neighbouring pixel
    pairs touching a solid pixel, differing by more than t, that land in the same
    group). Pixel art has few colours, so this keeps the outlines of solid tiles.
    -> (thresholds: 3 descending luminance thresholds, centres: 4 group means)."""
    v = y.reshape(-1)
    uq = np.unique(np.round(v, 4))
    if len(uq) > max_bins:
        edges_ = np.quantile(v, np.linspace(0, 1, max_bins + 1))
        uq = np.unique(np.round(edges_, 4))
    # bin index (ascending luminance)
    b = np.clip(np.searchsorted(uq, np.round(y, 4), side="left"), 0, len(uq) - 1)
    n = len(uq)
    if n <= 4:
        c = np.sort(uq)[::-1]
        th = [(c[i] + c[i + 1]) / 2 for i in range(len(c) - 1)] + [-1.0] * (4 - len(c))
        cen = list(c) + [c[-1]] * (4 - len(c))
        return np.array(th[:3]), np.array(cen[:4])
    cnt = np.bincount(b.reshape(-1), minlength=n).astype(float)
    sm = np.bincount(b.reshape(-1), y.reshape(-1), n)
    sq = np.bincount(b.reshape(-1), (y * y).reshape(-1), n)
    P = np.zeros((n, n))
    for a, c2 in ((b[:, :-1], b[:, 1:]), (b[:-1, :], b[1:, :])):
        ya = y[:, :-1] if a.shape[1] != b.shape[1] else y[:-1, :]
        yb = y[:, 1:] if a.shape[1] != b.shape[1] else y[1:, :]
        sa = solid[:, :-1] | solid[:, 1:] if a.shape[1] != b.shape[1] else solid[:-1, :] | solid[1:, :]
        m = sa & (np.abs(ya - yb) > t)
        np.add.at(P, (a[m], c2[m]), 1)
    P = P + P.T
    Pc = np.zeros((n + 1, n + 1))
    Pc[1:, 1:] = P.cumsum(0).cumsum(1)
    C, S, Q = (np.concatenate([[0], a.cumsum()]) for a in (cnt, sm, sq))

    def cost(lo, hi):   # bins [lo, hi): vectorised over arrays
        k = C[hi] - C[lo]
        sse = Q[hi] - Q[lo] - np.where(k > 0, (S[hi] - S[lo]) ** 2 / np.maximum(k, 1e-9), 0)
        viol = (Pc[hi, hi] - Pc[lo, hi] - Pc[hi, lo] + Pc[lo, lo]) / 2
        return sse + edge_w * viol

    best = (np.inf, None)
    for c1 in range(1, n - 2):
        for c2 in range(c1 + 1, n - 1):
            c3 = np.arange(c2 + 1, n)
            tot = cost(0, c1) + cost(c1, c2) + cost(np.full_like(c3, c2), c3) + cost(c3, np.full_like(c3, n))
            i = int(np.argmin(tot))
            if tot[i] < best[0]:
                best = (float(tot[i]), (c1, c2, int(c3[i])))
    cuts = best[1]
    bounds = [0, *cuts, n]
    cen = [(S[bounds[i + 1]] - S[bounds[i]]) / max(C[bounds[i + 1]] - C[bounds[i]], 1e-9) for i in range(4)]
    th = [(uq[c - 1] + uq[c]) / 2 for c in cuts]
    return np.array(th[::-1]), np.array(cen[::-1])


def quantize_thresholds(y, th):
    """level = number of descending thresholds above y (0 = brightest)."""
    return (y[..., None] < np.asarray(th)[None, None, :]).sum(-1).astype(np.uint8)


def quantize(y, centres, dither):
    """-> level 0..3 per pixel. Continuous level coordinate u is piecewise linear between
    the (descending) centres; plain rounding without dither, Bayer 2x2 offset with dither."""
    c = centres
    u = np.interp(-y, -c, np.arange(4.0))           # interp needs increasing x
    if dither:
        h, w = y.shape
        u = u + np.tile(BAYER2, (h // 2 + 1, w // 2 + 1))[:h, :w]
    return np.clip(np.floor(u + 0.5), 0, 3).astype(np.uint8)


def solid_local_levels(y, centres, solid_cells, th, tw, gap=0.05):
    """Edge-preserving levels for solid (collision) cells: inside each solid 8x8 cell the
    distinct luminances are grouped (gap > `gap` starts a new group, at most 4 groups by
    1-D k-means) and the groups get strictly increasing levels (order preserving), chosen
    to minimise the squared distance to their continuous level coordinate. Two colours of
    a solid tile that differ visibly therefore never merge into one level. No dithering."""
    from itertools import combinations
    u = np.interp(-y, -centres, np.arange(4.0))
    out = {}
    for i in np.flatnonzero(solid_cells):
        cy, cx = divmod(int(i), tw)
        yy = y[cy * 8:cy * 8 + 8, cx * 8:cx * 8 + 8].reshape(-1)
        uu = u[cy * 8:cy * 8 + 8, cx * 8:cx * 8 + 8].reshape(-1)
        order = np.argsort(-yy)                     # brightest first = level 0 first
        grp = np.zeros(64, int)
        g = 0
        for a, b in zip(order[:-1], order[1:]):
            if yy[a] - yy[b] > gap:
                g += 1
            grp[b] = g
        ng = g + 1
        if ng > 4:                                  # merge to 4 groups by 1-D k-means on luminance
            c = np.quantile(yy, [0.875, 0.625, 0.375, 0.125])
            for _ in range(20):
                lab = np.argmin(np.abs(yy[:, None] - c[None]), 1)
                c = np.array([yy[lab == j].mean() if (lab == j).any() else c[j] for j in range(4)])
            rank = np.argsort(np.argsort(-c))
            grp, ng = rank[lab], 4
            used = np.unique(grp)
            grp = np.searchsorted(used, grp)
            ng = len(used)
        gu = np.array([uu[grp == j].mean() for j in range(ng)])
        gw = np.bincount(grp, minlength=ng)
        best = min(combinations(range(4), ng), key=lambda L: float((gw * (gu - np.array(L)) ** 2).sum()))
        out[int(i)] = np.array(best, np.uint8)[grp].reshape(8, 8)
    return out


def to_tiles(a):
    h, w = a.shape
    return a.reshape(h // 8, 8, w // 8, 8).transpose(0, 2, 1, 3).reshape(-1, 64)


def from_tiles(t, th, tw):
    return t.reshape(th, tw, 8, 8).transpose(0, 2, 1, 3).reshape(th * 8, tw * 8)


def kmeanspp(x, w, k, gen):
    n = x.shape[0]
    idx = [int(torch.multinomial(w, 1, generator=gen))]
    d = ((x - x[idx[0]]) ** 2).sum(1)
    for _ in range(1, k):
        p = w * d
        if p.sum() <= 0:
            break
        i = int(torch.multinomial(p, 1, generator=gen))
        idx.append(i)
        d = torch.minimum(d, ((x - x[i]) ** 2).sum(1))
    return x[idx].clone()


def nearest(x, cb):
    return torch.cdist(x, cb).argmin(1)


def vq(tiles, weights, k, pinned_idx, seed=0, iters=30):
    """tiles: unique level tiles (n, 64) float; weights (n,); pinned_idx: indices kept exactly.
    -> codebook (k', 64) uint8 levels, assignment (n,)."""
    gen = torch.Generator().manual_seed(seed)
    x = torch.tensor(tiles, dtype=torch.float32)
    w = torch.tensor(weights, dtype=torch.float32)
    pin = torch.tensor(sorted(pinned_idx), dtype=torch.long)
    free = k - len(pin)
    rest = torch.ones(len(x), dtype=torch.bool)
    rest[pin] = False
    cb_pin = x[pin]
    cb = kmeanspp(x[rest], w[rest], free, gen) if free > 0 else x[:0]
    for _ in range(iters):                              # Lloyd, continuous
        full = torch.cat([cb_pin, cb])
        a = nearest(x, full)
        new = cb.clone()
        for j in range(len(cb)):
            m = a == len(cb_pin) + j
            if m.any():
                new[j] = (x[m] * w[m, None]).sum(0) / w[m].sum()
        if torch.allclose(new, cb):
            break
        cb = new
    for _ in range(iters):                              # refinement on integer levels
        cbq = torch.round(cb).clamp(0, 3)
        full = torch.cat([cb_pin, cbq])
        a = nearest(x, full)
        new = cbq.clone()
        for j in range(len(cbq)):
            m = a == len(cb_pin) + j
            if m.any():
                new[j] = torch.round((x[m] * w[m, None]).sum(0) / w[m].sum())
        if torch.equal(new, cbq):
            break
        cb = new
    full = torch.cat([cb_pin, torch.round(cb).clamp(0, 3)])
    a = nearest(x, full)
    used = torch.unique(a)
    remap = torch.full((len(full),), -1, dtype=torch.long)
    remap[used] = torch.arange(len(used))
    return full[used].to(torch.uint8).numpy(), remap[a].numpy()


def encode_2bpp(cb):
    out = bytearray()
    for t in cb.reshape(-1, 8, 8):
        for row in t:
            lo = hi = 0
            for px in range(8):
                lo |= (int(row[px]) & 1) << (7 - px)
                hi |= ((int(row[px]) >> 1) & 1) << (7 - px)
            out += bytes((lo, hi))
    return bytes(out)


def compile_scene(scene, k=256, reserve=0, dither=False, levels="edge", fov="scroll", crop=(40, 8),
                  sal_w=4.0, solid_w=8.0, pin_frac=0.75, seed=0, solid_edges=None):
    """scene: snapshot dict or path. -> result dict (numpy arrays + stats)."""
    s = load(scene) if isinstance(scene, str) else scene
    d = dump(s)
    rgb, solid = apply_fov(d["composite"], d["solid"], fov, crop)
    y = luminance(rgb)
    cells_solid = to_tiles(solid.astype(np.uint8)).mean(1) > 0.5
    th, tw = y.shape[0] // 8, y.shape[1] // 8
    solid_px = np.kron(cells_solid.reshape(th, tw), np.ones((8, 8), bool))
    if levels == "edge":
        thresholds, centres = edge_aware_cuts(y, solid_px)
        q = quantize_thresholds(y, thresholds)
        if dither:                                     # ordered dither of non-solid cells
            qd = quantize(y, centres, True)
            q = np.where(solid_px, q, qd)
    else:
        centres = level_centres(y, levels)
        q = quantize(y, centres, dither)
    if solid_edges is None:
        solid_edges = levels != "edge"
    if solid_edges:
        for i, t in solid_local_levels(y, centres, cells_solid, th, tw).items():
            cy, cx = divmod(i, tw)
            q[cy * 8:cy * 8 + 8, cx * 8:cx * 8 + 8] = t
    cells = to_tiles(q)
    cells_sal = to_tiles(sobel_mag(y)).mean(1)
    # source classes: unique composite RGB cells (what the GBA scene shows in that cell)
    src = to_tiles(rgb[..., 0].astype(np.int64) << 16 | rgb[..., 1].astype(np.int64) << 8 | rgb[..., 2])
    _, classes = np.unique(src, axis=0, return_inverse=True)
    classes = classes.reshape(-1)
    uniq, inv, cnt = np.unique(cells, axis=0, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    sal = np.bincount(inv, cells_sal, len(uniq)) / cnt
    sal = sal / (sal.max() + 1e-9)
    usolid = np.bincount(inv, cells_solid, len(uniq)) > 0
    weights = cnt * (1 + sal_w * sal + solid_w * usolid)
    kk = k - reserve
    if len(uniq) <= kk:
        cb, assign, exact, pinned = uniq.astype(np.uint8), np.arange(len(uniq)), True, int(usolid.sum())
    else:
        pin = np.flatnonzero(usolid)
        if len(pin) > pin_frac * kk:                  # too many: pin the heaviest
            pin = pin[np.argsort(-weights[pin])][:int(pin_frac * kk)]
        cb, assign = vq(uniq.astype(np.float32), weights, kk, pin.tolist(), seed)
        exact, pinned = False, len(pin)
    gb_cells = assign[inv]                               # codeword per map cell
    recon = from_tiles(cb[gb_cells].reshape(-1, 64), th, tw)
    tilemap = (gb_cells + reserve).astype(np.uint8)
    lut = np.zeros(classes.max() + 1, np.uint8)
    lut[classes] = tilemap
    err = (cb[assign].astype(np.int32) - uniq) ** 2
    stats = {"fov": fov, "solid_edges": solid_edges, "levels": levels, "dither": dither, "k": k, "reserve": reserve,
             "map_w": tw, "map_h": th, "unique_tiles": int(len(uniq)), "codewords": int(len(cb)),
             "exact": bool(exact), "pinned_solid": int(pinned), "solid_unique": int(usolid.sum()),
             "classes": int(len(lut)), "centres": [round(float(c), 4) for c in centres],
             "tile_mse_levels": float((err.sum(1) * cnt).sum() / cnt.sum() / 64),
             "solid_cells_exact": float(np.mean([(cb[assign[inv[i]]] == cells[i]).all()
                                                 for i in np.flatnonzero(cells_solid)])) if cells_solid.any() else 1.0}
    return {"y": y, "rgb": rgb, "levels": q, "recon": recon, "solid": solid, "cells_solid": cells_solid,
            "codebook": cb, "tilemap": tilemap, "classes": classes.astype(np.uint16), "lut": lut,
            "tiles_2bpp": encode_2bpp(cb), "stats": stats, "name": s.get("name", "")}


def export(res, out):
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "tiles.2bpp"), "wb").write(res["tiles_2bpp"])
    open(os.path.join(out, "tilemap.bin"), "wb").write(res["tilemap"].tobytes())
    open(os.path.join(out, "classes.bin"), "wb").write(res["classes"].astype("<u2").tobytes())
    open(os.path.join(out, "lut_tile_remap.bin"), "wb").write(res["lut"].tobytes())
    json.dump(res["stats"], open(os.path.join(out, "compile.json"), "w"), indent=1)


def shade(levels):
    """DMG level (0 white .. 3 black) -> displayed luminance 0..1."""
    return 1.0 - np.asarray(levels, np.float64) / 3.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--out", default="build/vq/out")
    ap.add_argument("--k", type=int, default=256)
    ap.add_argument("--reserve", type=int, default=0)
    ap.add_argument("--dither", action="store_true")
    ap.add_argument("--levels", default="edge", choices=["edge", "adaptive", "uniform"])
    ap.add_argument("--fov", default="scroll", choices=["scroll", "downscale", "crop"])
    ap.add_argument("--crop", default="40,8")
    a = ap.parse_args()
    res = compile_scene(a.scene, a.k, a.reserve, a.dither, a.levels, a.fov, tuple(map(int, a.crop.split(","))))
    export(res, a.out)
    print(json.dumps(res["stats"]))


if __name__ == "__main__":
    main()
