"""Evaluate externally captured scenes (e.g. tools/gba_capture dumps) with the Phase 3
pipeline. Images and per-scene artefacts go to an output directory outside the repo;
the markdown report contains numbers only.

    python -m tools.vq.eval_scenes MANIFEST.json --out DIR [--md REPORT.md]

MANIFEST: {"scenes": {name: {"path": snapshot dir/npz, "solid_bg": [1] (heuristic
collision layers, optional), "hud_bg": [3] (excluded from parallax), "parallax":
{"far": 2, "near": [1]} (optional), "rom": true (optional), "how": "free text"}}}

Per scene: dumper composite vs. the emulator frame (screen.ppm in the snapshot dir, if
present; compared at 5-bit colour precision, so sprites, blending and per-line effects
show up as mismatches), compile_scene + scene_metrics (same defaults as Phase 3),
optional parallax pressure (parallax_baker) and an optional DMG ROM run in PyBoy."""
import argparse
import json
import os
import numpy as np
from PIL import Image
from .snapshot import load
from .vram_scene_dumper import dump, u16
from .vq_tile_compiler import compile_scene
from .metrics import scene_metrics
from .visualize import panel, side_by_side, rom_check
from .parallax_baker import bake, export as pexport


def heuristic_solid(s, bgs):
    """Flag every non-empty tile number (map entry != tile 0 and drawn pixels) of the given
    BGs as solid. Heuristic: SMW-style engines put level geometry on one 'layer 1' BG, but
    that BG also carries non-solid decoration."""
    d = dump(s)
    for n in bgs:
        if n not in d["layers"]:
            continue
        L = d["layers"][n]
        flags = np.zeros(1024, np.uint8)
        t = (L["entry"] & 0x3FF)[L["ci"] > 0]
        flags[np.unique(t)] = 1
        s[f"solid_bg{n}"] = flags
    return s


def frame_agreement(s, path):
    ppm = os.path.join(path, "screen.ppm") if os.path.isdir(path) else None
    if not ppm or not os.path.exists(ppm):
        return None
    scr = np.asarray(Image.open(ppm).convert("RGB")).astype(int) >> 3
    comp = dump(s)["composite"].astype(int) >> 3
    return float((scr == comp).all(-1).mean())


def evaluate(manifest, out, run_roms=True):
    os.makedirs(os.path.join(out, "img"), exist_ok=True)
    rep = {"scenes": {}, "parallax": {}, "roms": {}}
    for name, cfg in manifest["scenes"].items():
        s = load(cfg["path"])
        s["name"] = name
        if cfg.get("solid_bg"):
            s = heuristic_solid(s, cfg["solid_bg"])
        d = dump(s)
        io = s["io"]
        info = {"how": cfg.get("how", ""), "dispcnt": hex(u16(io, 0)), "bldcnt": hex(u16(io, 0x50)),
                "bgs": {n: {k: (list(v) if isinstance(v, tuple) else v) for k, v in L["params"].items()}
                        for n, L in d["layers"].items()},
                "unsupported": d["unsupported"], "frame_agreement": frame_agreement(s, cfg["path"])}
        res = compile_scene(s)
        m = scene_metrics(res)
        m.update({k: res["stats"][k] for k in ("unique_tiles", "codewords", "exact", "classes")})
        for kw, tag in (({"dither": True}, "dither"), ({"fov": "downscale"}, "downscale")):
            m["ssim_luma_" + tag] = scene_metrics(compile_scene(s, **kw))["ssim_luma"]
        rep["scenes"][name] = {**info, **m}
        side_by_side(panel(res), ["GBA original (BG layers)", "luminance", "DMG reconstruction",
                                  "solid (heuristic): red lost / blue added edge"],
                     os.path.join(out, "img", f"{name}_vq.png"))
        if cfg.get("parallax"):
            p = cfg["parallax"]
            r = bake(s, far_bg=p["far"], near_bgs=p["near"])
            rep["parallax"][name] = pexport(r, os.path.join(out, "parallax", name))
        if cfg.get("rom") and run_roms:
            rep["roms"][name] = rom_check(name, res, os.path.join(out, "img"), os.path.join(out, "rom"))
    json.dump(rep, open(os.path.join(out, "eval.json"), "w"), indent=1, default=str)
    return rep


def markdown(rep, title, ref=None):
    L = [f"# {title}", "", "Numbers only (no images or game data in this repository).", "",
         "| scene | BGs | frame agreement | unique tiles | codewords | SSIM luma | SSIM display | solid cells | Edge IoU solid | SSIM luma dither | SSIM luma downscale |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, m in rep["scenes"].items():
        fa = "n/a" if m["frame_agreement"] is None else f"{m['frame_agreement']:.3f}"
        eiou = f"{m['edge_iou_solid']:.3f}" if m["solid_cells"] else "n/a"
        L.append(f"| {n} | {len(m['bgs'])} | {fa} | {m['unique_tiles']} | {m['codewords']} | {m['ssim_luma']:.3f} | "
                 f"{m['ssim_display']:.3f} | {m['solid_cells']} | {eiou} | {m['ssim_luma_dither']:.3f} | "
                 f"{m['ssim_luma_downscale']:.3f} |")
    sc = rep["scenes"].values()
    solid = [m for m in sc if m["solid_cells"]]
    L += ["", f"Means: SSIM luma {np.mean([m['ssim_luma'] for m in sc]):.3f}, SSIM display "
          f"{np.mean([m['ssim_display'] for m in sc]):.3f}, Edge IoU (scenes with solid cells) "
          f"{np.mean([m['edge_iou_solid'] for m in solid]):.3f}, unique tiles "
          f"{np.mean([m['unique_tiles'] for m in sc]):.0f}, scenes over 256 tiles: "
          f"{sum(m['unique_tiles'] > 256 for m in sc)}/{len(rep['scenes'])}."]
    if rep["parallax"]:
        L += ["", "## Parallax codebook pressure", "",
              "| scene | map | static tiles (d=0) | unique per phase | union | pressure | codewords | tile MSE | ROM banks |",
              "|---|---|---|---|---|---|---|---|---|"]
        for n, i in rep["parallax"].items():
            pp = i["unique_tiles_per_phase"].values()
            L.append(f"| {n} | {i['map'][1]}x{i['map'][0]} | {i['static_unique_tiles_d0']} | {min(pp)}-{max(pp)} | "
                     f"{i['unique_tiles_union']} | {i['pressure_union']:.2f} | {i['codewords']} | "
                     f"{i['tile_mse_levels']:.4f} | {i['rom_banks']} |")
    if rep["roms"]:
        L += ["", "## DMG ROMs in PyBoy (cgb=False)", "",
              "| scene | class ids | remap loop M/tile | LUT lookup M/tile | screen == reconstruction |", "|---|---|---|---|---|"]
        for n, r in rep["roms"].items():
            L.append(f"| {n} | {'16-bit' if r['class16'] else '8-bit'} ({r['classes']}) | {r['remap_loop_m_per_tile']:.2f} | "
                     f"{r['lookup_m_per_tile']:.2f} | {', '.join(f'{v:.3f}' for v in r['screen_match'])} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--out", required=True)
    ap.add_argument("--md")
    ap.add_argument("--title", default="Scene evaluation")
    a = ap.parse_args()
    rep = evaluate(json.load(open(a.manifest)), a.out)
    md = markdown(rep, a.title)
    open(a.md or os.path.join(a.out, "eval.md"), "w").write(md)
    print(md)


if __name__ == "__main__":
    main()
