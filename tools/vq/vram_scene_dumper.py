"""Reconstruct the visible GBA background layers of a snapshot (tools/vq/snapshot.py).

Supported: video modes 0 (BG0-BG3 text) and 1 (BG0-BG1 text; affine BG2 is reported
as unsupported), 4bpp (16 palette banks) and 8bpp tiles, horizontal/vertical flips,
all four text BG sizes (256/512 x 256/512 with the screen-block layout), scroll
(BGxHOFS/BGxVOFS, 9 bits), priorities (BGxCNT bits 0-1, ties -> lower BG on top),
transparency (colour index 0) and the backdrop (BG palette entry 0).
Objects, windows, blending and mosaic are ignored.

    python -m tools.vq.vram_scene_dumper SNAPSHOT [--out DIR]
writes layer<n>.png (RGBA), composite.png and scene.json (layer parameters)."""
import argparse
import json
import os
import numpy as np

W, H = 240, 160
TEXT_SIZES = {0: (256, 256), 1: (512, 256), 2: (256, 512), 3: (512, 512)}


def u16(a, off):
    return int(a[off]) | (int(a[off + 1]) << 8)


def bgr555_to_rgb(c):
    c = np.asarray(c, np.int32)
    r, g, b = c & 31, (c >> 5) & 31, (c >> 10) & 31
    return (np.stack([r, g, b], -1) * 255 // 31).astype(np.uint8)


def bg_params(s, n):
    io = s["io"]
    cnt = u16(io, 8 + 2 * n)
    return {"bg": n, "prio": cnt & 3, "cbb": (cnt >> 2) & 3, "bpp8": bool(cnt & 0x80),
            "sbb": (cnt >> 8) & 31, "size": TEXT_SIZES[cnt >> 14],
            "hofs": u16(io, 0x10 + 4 * n) & 511, "vofs": u16(io, 0x12 + 4 * n) & 511}


def visible_bgs(s):
    dcnt = u16(s["io"], 0)
    mode = dcnt & 7
    out, unsupported = [], []
    for n in range(4):
        if not dcnt & (0x100 << n):
            continue
        if mode == 0 or (mode == 1 and n < 2):
            out.append(n)
        else:
            unsupported.append(n)
    if mode > 2:
        unsupported.append(f"bitmap mode {mode}")
    return out, unsupported


def render_map(s, n):
    """Whole map of text BG n (map size, no scroll) -> (ci, entry, rgba)."""
    p = dict(bg_params(s, n), hofs=0, vofs=0)
    bw, bh = p["size"]
    ci, ent = render_bg(s, p, bw, bh)
    pal = np.array([u16(s["pal"], 2 * i) for i in range(256)])
    rgba = np.zeros((bh, bw, 4), np.uint8)
    rgba[..., :3] = bgr555_to_rgb(pal)[ci]
    rgba[..., 3] = np.where(ci != 0, 255, 0)
    return ci, ent, rgba


def render_bg(s, p, W=W, H=H):
    """-> (colour index 0-255 incl. palette bank, uint16 [H, W]; 0 = transparent),
          map entry per pixel (uint16 [H, W])."""
    vram, sbb = s["vram"], p["sbb"]
    bw, bh = p["size"]
    ys, xs = np.mgrid[0:H, 0:W]
    mx, my = (xs + p["hofs"]) % bw, (ys + p["vofs"]) % bh
    blk = sbb + (mx // 256) + (my // 256) * (bw // 256)
    eaddr = blk * 0x800 + 2 * (((my % 256) // 8) * 32 + (mx % 256) // 8)
    eaddr = eaddr % 0x10000
    ent = vram[eaddr].astype(np.uint16) | (vram[eaddr + 1].astype(np.uint16) << 8)
    tile = ent & 0x3FF
    px = np.where(ent & 0x400, 7 - (mx & 7), mx & 7)
    py = np.where(ent & 0x800, 7 - (my & 7), my & 7)
    base = p["cbb"] * 0x4000
    if p["bpp8"]:
        addr = (base + tile.astype(np.int64) * 64 + py * 8 + px) % 0x10000
        ci = vram[addr].astype(np.uint16)
    else:
        addr = (base + tile.astype(np.int64) * 32 + py * 4 + px // 2) % 0x10000
        ci = (vram[addr] >> (4 * (px & 1))).astype(np.uint16) & 15
        ci = np.where(ci != 0, ci | ((ent >> 12) << 4), 0)
    return ci, ent


def dump(s):
    """-> dict: layers {n: {"params", "ci", "entry", "rgba"}}, order (top first),
    composite (RGB uint8 [H, W, 3]), owner (BG number per pixel, -1 = backdrop),
    solid (bool [H, W]: pixel from a solid-flagged tile), unsupported."""
    pal = np.array([u16(s["pal"], 2 * i) for i in range(256)])
    rgb_pal = bgr555_to_rgb(pal)
    bgs, unsupported = visible_bgs(s)
    layers = {}
    for n in bgs:
        p = bg_params(s, n)
        ci, ent = render_bg(s, p)
        rgba = np.zeros((H, W, 4), np.uint8)
        rgba[..., :3] = rgb_pal[ci]
        rgba[..., 3] = np.where(ci != 0, 255, 0)
        layers[n] = {"params": p, "ci": ci, "entry": ent, "rgba": rgba}
    order = sorted(layers, key=lambda n: (layers[n]["params"]["prio"], n))
    comp = np.broadcast_to(rgb_pal[0], (H, W, 3)).copy()
    owner = np.full((H, W), -1, np.int8)
    solid = np.zeros((H, W), bool)
    for n in reversed(order):
        L = layers[n]
        m = L["ci"] != 0
        comp[m] = L["rgba"][..., :3][m]
        owner[m] = n
        flags = s.get(f"solid_bg{n}")
        if flags is not None:
            sm = np.asarray(flags, bool)[L["entry"] & 0x3FF]
            solid = np.where(m, sm, solid)
    return {"layers": layers, "order": order, "composite": comp, "owner": owner,
            "solid": solid, "unsupported": unsupported}


def main():
    from PIL import Image
    from .snapshot import load
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--out", default="build/vq/dump")
    a = ap.parse_args()
    d = dump(load(a.snapshot))
    os.makedirs(a.out, exist_ok=True)
    for n, L in d["layers"].items():
        Image.fromarray(L["rgba"], "RGBA").save(os.path.join(a.out, f"layer{n}.png"))
    Image.fromarray(d["composite"]).save(os.path.join(a.out, "composite.png"))
    json.dump({"order": d["order"], "unsupported": d["unsupported"],
               "layers": {n: {**L["params"], "size": list(L["params"]["size"])} for n, L in d["layers"].items()}},
              open(os.path.join(a.out, "scene.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
