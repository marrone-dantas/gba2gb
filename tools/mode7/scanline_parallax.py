"""Phase 4.2: per-line SCX parallax on one BG layer (the option deferred in 3.4),
using the HBlank stack-blasting ISR of runtime/hblank_mode7.asm on a VQ-compiled
CC0 scene (tests/demos/scanline_parallax.asm, docs/mode7.md)."""
from __future__ import annotations
import os
import subprocess
import numpy as np
from tools.vq.vq_tile_compiler import compile_scene

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCY0, BAND1, BAND2 = 8, 56, 96


def scx_of_line(y, cam):
    return cam // 4 if y < BAND1 else cam // 2 if y < BAND2 else cam


def expected(recon, cam):
    out = np.zeros((144, 160), np.uint8)
    for y in range(144):
        x = scx_of_line(y, cam)
        out[y] = recon[y + SCY0, x:x + 160]
    return out


def build_rom(scene, out):
    res = compile_scene(scene)
    st = res["stats"]
    mw, mh = st["map_w"], st["map_h"]
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "px_tiles.2bpp"), "wb").write(res["tiles_2bpp"])
    open(os.path.join(out, "px_map.bin"), "wb").write(res["tilemap"].tobytes())
    max_cam = mw * 8 - 160
    inc = [f"DEF MAP_W EQU {mw}", f"DEF MAP_H EQU {mh}", f"DEF NTILES EQU {len(res['codebook'])}",
           f"DEF SCY0 EQU {SCY0}", f"DEF BAND1 EQU {BAND1}", f"DEF BAND2 EQU {BAND2}", f"DEF MAX_CAM EQU {max_cam}",
           'SECTION "px_gfx", ROM0', 'Tiles:: INCBIN "px_tiles.2bpp"', 'Tilemap:: INCBIN "px_map.bin"']
    open(os.path.join(out, "px_data.inc"), "w").write("\n".join(inc) + "\n")
    o, rom = os.path.join(out, "scanline_parallax.o"), os.path.join(out, "scanline_parallax.gb")
    subprocess.run(["rgbasm", "-I", os.path.join(ROOT, "runtime"), "-I", out, "-o", o,
                    os.path.join(ROOT, "tests", "demos", "scanline_parallax.asm")], check=True)
    subprocess.run(["rgblink", "-o", rom, "-n", rom[:-3] + ".sym", o], check=True)
    subprocess.run(["rgbfix", "-v", "-p", "0xFF", "-m", "0x19", "-t", "PARALLAX", rom], check=True, capture_output=True)
    return rom, res, max_cam
