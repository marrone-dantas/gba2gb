"""Phase 3.5: side-by-side visualizer (original vs reconstruction) and the metrics report.

    python -m tools.vq.visualize [--scenes data/vq/scenes] [--img docs/img] [--report build/reports]

Per scene: docs/img/vq_<scene>.png = original GBA composite | original luminance |
DMG reconstruction (scroll FOV, default options) | solid cells + edge errors (red = edge
lost, blue = edge added). Metrics (tools/vq/metrics.py) for the default compile and for
the dither / downscale / uniform-level variants go to build/reports/vq_metrics.json and
docs/vq_metrics.md. A few scenes are also built into DMG ROMs (tools/vq/scene_rom.py),
run in PyBoy (cgb=False) and screenshotted: docs/img/vq_rom_<scene>.png = expected
window of the reconstruction | PyBoy screen."""
import argparse
import json
import os
import numpy as np
from PIL import Image, ImageDraw
from .vq_tile_compiler import compile_scene, shade
from .metrics import scene_metrics, edges, solid_pixel_mask, EDGE_T

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DMG = np.array([[224, 248, 208], [136, 192, 112], [52, 104, 86], [8, 24, 32]], np.uint8)   # display tint
GREYS = np.array([[255] * 3, [170] * 3, [85] * 3, [0] * 3], np.uint8)          # PyBoy DMG greys
ROM_SCENES = ("platformer_b", "tiny-ski_0", "proc_glyphs")


def grey(y):
    return np.repeat((np.clip(y, 0, 1) * 255).astype(np.uint8)[..., None], 3, -1)


def panel(res):
    rgb = res["rgb"]
    rec = DMG[res["recon"]]
    m = solid_pixel_mask(res)
    ea, eb = edges(res["y"], EDGE_T) & m, edges(res["recon"].astype(float), 0.5) & m
    err = grey(res["y"] * 0.5 + 0.25)
    err[m] = (err[m] * 0.6 + np.array([90, 140, 90]) * 0.4).astype(np.uint8)
    err[ea & ~eb] = (255, 0, 0)
    err[eb & ~ea] = (0, 80, 255)
    return [rgb, grey(res["y"]), rec, err]


def side_by_side(images, titles, path, scale=2):
    w = sum(i.shape[1] for i in images) + 6 * (len(images) - 1)
    h = max(i.shape[0] for i in images) + 12
    out = Image.new("RGB", (w, h), (30, 30, 30))
    d = ImageDraw.Draw(out)
    x = 0
    for im, t in zip(images, titles):
        out.paste(Image.fromarray(im), (x, 12))
        d.text((x + 2, 0), t, fill=(255, 255, 255))
        x += im.shape[1] + 6
    out.resize((w * scale, h * scale), Image.NEAREST).save(path)


def rom_check(name, res, img_dir, out_dir, frames=(0, 120, 300)):
    from .scene_rom import build_rom, SceneRun
    rom, info = build_rom(res, os.path.join(out_dir, name), name)
    g = SceneRun(rom)
    g.tick(300)                                  # DMG boot ROM + scene load
    remap, copy = g.loop_mcycles()
    cells = res["stats"]["map_w"] * res["stats"]["map_h"]
    match, shots = [], []
    for i, f in enumerate(frames):
        g.tick(max(f - (frames[i - 1] if i else 0), 0) + 1)
        x, y = g.scroll()
        g.tick(1)
        exp = res["recon"][y:y + 144, x:x + 160]
        got = g.screen_levels()
        match.append(float((got == exp).mean()))
        p = os.path.join(img_dir, f"vq_rom_{name}_scx{x:02d}.png")
        side_by_side([GREYS[exp], np.asarray(g.pb.screen.image.convert("RGB"))],
                     [f"expected window SCX={x} SCY={y}", "PyBoy DMG (cgb=False)"], p, 3)
        shots.append(p)
    g.stop()
    return {"rom": rom, **info, "cells": cells, "remap_loop_m_per_tile": remap / cells,
            "copy_loop_m_per_tile": copy / cells, "lookup_m_per_tile": (remap - copy) / cells,
            "screen_match": match, "screenshots": shots}


def run(scenes_dir, img_dir, report_dir, rom_dir):
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(report_dir, exist_ok=True)
    names = sorted(f[:-4] for f in os.listdir(scenes_dir) if f.endswith(".npz"))
    rep = {"scenes": {}, "variants": {}, "roms": {}}
    variants = {"dither": {"dither": True}, "downscale": {"fov": "downscale"}, "uniform": {"levels": "uniform"},
                "adaptive": {"levels": "adaptive"}}
    for n in names:
        path = os.path.join(scenes_dir, n + ".npz")
        res = compile_scene(path)
        m = scene_metrics(res)
        m.update({k: res["stats"][k] for k in ("unique_tiles", "codewords", "exact", "classes")})
        rep["scenes"][n] = m
        side_by_side(panel(res), ["GBA original", "luminance", "DMG reconstruction",
                                  "solid cells: red lost / blue added edge"], os.path.join(img_dir, f"vq_{n}.png"))
        for v, kw in variants.items():
            rep["variants"].setdefault(v, {})[n] = scene_metrics(compile_scene(path, **kw))
        if n in ROM_SCENES:
            rep["roms"][n] = rom_check(n, res, img_dir, rom_dir)
    sc = rep["scenes"]
    solid = [n for n in sc if sc[n]["solid_cells"]]
    rep["summary"] = {
        "mean_ssim_luma": float(np.mean([sc[n]["ssim_luma"] for n in sc])),
        "mean_ssim_display": float(np.mean([sc[n]["ssim_display"] for n in sc])),
        "mean_edge_iou_solid": float(np.mean([sc[n]["edge_iou_solid"] for n in solid])),
        "scenes_edge_iou_below_0.95": [n for n in solid if sc[n]["edge_iou_solid"] < 0.95],
        "max_lookup_m_per_tile": max(r["lookup_m_per_tile"] for r in rep["roms"].values()) if rep["roms"] else None,
        "variants_mean_ssim_luma": {v: float(np.mean([x["ssim_luma"] for x in d.values()])) for v, d in rep["variants"].items()},
        "variants_mean_edge_iou": {v: float(np.mean([d[n]["edge_iou_solid"] for n in solid])) for v, d in rep["variants"].items()}}
    json.dump(rep, open(os.path.join(report_dir, "vq_metrics.json"), "w"), indent=1, default=str)
    return rep


def markdown(rep):
    s = rep["summary"]
    L = ["# VQ metrics (Phase 3.5)", "",
         "Generated by `python -m tools.vq.visualize` (default compile: scroll FOV, edge-aware levels, "
         "no dither, K = 256). Metric definitions: `tools/vq/metrics.py`.", "",
         "| scene | unique tiles | codewords | exact | SSIM luma | SSIM display | solid cells | Edge IoU solid |",
         "|---|---|---|---|---|---|---|---|"]
    for n, m in rep["scenes"].items():
        L.append(f"| {n} | {m['unique_tiles']} | {m['codewords']} | {'yes' if m['exact'] else 'no'} | "
                 f"{m['ssim_luma']:.3f} | {m['ssim_display']:.3f} | {m['solid_cells']} | "
                 f"{m['edge_iou_solid']:.3f} |")
    L += ["", f"Mean SSIM luma **{s['mean_ssim_luma']:.3f}** (target ≥ 0.82), mean SSIM display "
          f"{s['mean_ssim_display']:.3f}, mean Edge IoU on solid tiles **{s['mean_edge_iou_solid']:.3f}** "
          f"(target ≥ 0.95); scenes below 0.95: {', '.join(s['scenes_edge_iou_below_0.95']) or 'none'}.", "",
          "| variant | mean SSIM luma | mean Edge IoU (solid scenes) |", "|---|---|---|",
          f"| default | {s['mean_ssim_luma']:.3f} | {s['mean_edge_iou_solid']:.3f} |"]
    for v in rep["variants"]:
        L.append(f"| {v} | {s['variants_mean_ssim_luma'][v]:.3f} | {s['variants_mean_edge_iou'][v]:.3f} |")
    L += ["", "## DMG ROMs in PyBoy (cgb=False)", "",
          "| scene | class ids | remap loop M/tile | copy loop M/tile | LUT lookup M/tile | screen == reconstruction |",
          "|---|---|---|---|---|---|"]
    for n, r in rep["roms"].items():
        L.append(f"| {n} | {'16-bit' if r['class16'] else '8-bit'} ({r['classes']}) | {r['remap_loop_m_per_tile']:.2f} | "
                 f"{r['copy_loop_m_per_tile']:.2f} | **{r['lookup_m_per_tile']:.2f}** | "
                 f"{', '.join(f'{v:.3f}' for v in r['screen_match'])} |")
    L += ["", "LUT lookup = remap loop minus the identical copy loop without the lookup (measured with "
          "PyBoy PC hooks, T-cycles / 4). The full per-tile loop includes the store and loop overhead."]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", default=os.path.join(ROOT, "data", "vq", "scenes"))
    ap.add_argument("--img", default=os.path.join(ROOT, "docs", "img"))
    ap.add_argument("--report", default=os.path.join(ROOT, "build", "reports"))
    ap.add_argument("--roms", default=os.path.join(ROOT, "build", "vq", "rom"))
    ap.add_argument("--md", default=os.path.join(ROOT, "docs", "vq_metrics.md"))
    a = ap.parse_args()
    rep = run(a.scenes, a.img, a.report, a.roms)
    open(a.md, "w").write(markdown(rep))
    print(json.dumps(rep["summary"], indent=1))


if __name__ == "__main__":
    main()
