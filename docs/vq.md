# Phase 3: VQ tile compiler (GBA scene -> DMG tiles)

## 3.3 Compiler (`tools/vq/vq_tile_compiler.py`)
`python -m tools.vq.vq_tile_compiler SCENE [--out DIR] [--k 256] [--reserve N] [--dither]
[--levels edge|adaptive|uniform] [--fov scroll|downscale|crop] [--crop X,Y]`

1. **Scene**: `vram_scene_dumper.dump()` → 240x160 composite plus solid (collision) mask.
2. **Field of view** (240x160 vs. DMG 160x144):
   * `scroll` (**default**): every pixel and the GBA 8x8 grid are kept. The 30x20 tile map
     fits the 32x32 GB BG map, and the 160x144 screen is a window moved with SCX/SCY.
     Nothing is resampled, so tiles stay identical and the codebook stays small. The cost
     is that the player sees 2/3 of the width and 9/10 of the height at a time; the game
     (or the HAL scroll shim) has to move the window.
   * `downscale`: Lanczos resample to 160x144 (a non-uniform 2/3 x 9/10 scale) into a 20x18 map.
     The whole view is visible, but pixel art loses its grid: about 2x more unique tiles,
     blur, and lower SSIM (see the 3.5 table).
   * `crop`: a static 160x144 window (`--crop X,Y`).
3. **Luminance** Y = 0.299R + 0.587G + 0.114B, mapped to 4 levels (0 = white … 3 = black,
   BGP identity):
   * `edge` (**default**): exhaustive search of the 3 cut points over the scene's distinct
     luminances (binned to at most 96; empty levels allowed). It minimises the squared error
     plus 1000 × (edges lost + edges added), counted over neighbouring pixel pairs at a solid
     pixel: lost = the pair differs by more than 0.05 but lands in one level; added = it differs
     by at most 0.05 but a cut separates it.
   * `adaptive`: 1-D k-means with centres at least 0.12 apart, plus edge-preserving local levels in solid cells.
   * `uniform`: 4 equal bins.

   `--dither` applies ordered Bayer 2x2 dithering to non-solid cells.
4. **Codebook** K = 256 − reserve, where `--reserve` keeps tiles free for sprites/HUD (for example 128 when
   the HAL OBJ tiles share $8800-$8FFF). With at most K unique tiles the result is exact. Otherwise:
   * Solid unique tiles are pinned as exact codewords, up to 0.75K.
   * Weighted k-means++ then Lloyd (PyTorch, CPU), with weight = count · (1 + 4·Sobel saliency + 8·solid).
   * VQ refinement: codewords are snapped to integer levels, tiles reassigned and codewords
     re-estimated (rounding the weighted mean) until stable. Seeded and deterministic.
5. **Export**:
   * `tiles.2bpp`: GB tile format; codeword i is GB tile reserve+i.
   * `tilemap.bin`: 1 byte per cell, row-major.
   * `classes.bin`: uint16 source class per cell, where a class is a distinct GBA composite 8x8 cell.
   * `lut_tile_remap.bin`: uint8 GB tile per class, the runtime remap table (one 256-byte page per 256 classes).
   * `compile.json`.

## 3.4 Parallax baker (`tools/vq/parallax_baker.py`)
The DMG has one opaque BG layer, so the two layers are composited offline:
* The far layer is the lowest-priority BG (or `--far N`). All the other BGs are merged into the near layer.
* Near scroll is x and far scroll is r·x (default r = 1/2), which offsets the far layer by d = x − r·x
  relative to the near tile grid: phase p = d mod 8, coarse k = d div 8 (32 values for a 256 px far map).
* For each of the 8 phases, the composite tiles of every (cell, k) are quantized with shared
  edge-aware cuts and deduplicated.
* The codebook is **shared by all phases** because a DMG cannot reload a 4 KiB codebook within
  a frame (no HDMA). When the union is bigger than K = 256, it is vector-quantized (solid near tiles pinned).
* Each (p, k) gets a 32x18 tilemap (576 B). The maps are packed into MBC5 16 KiB banks
  (28 maps per bank, 256 maps = 10 banks); `layout.json` gives bank and address per (p, k).
* Runtime plan, not implemented in a ROM yet: on a phase change, select the bank, copy the 576 B map
  into the hidden BG map ($9800/$9C00) during mode 0/1 over about 1–2 frames, then flip LCDC.3.
  With r = 1/2, d changes every 2 frames at 1 px/frame.

Codebook pressure (`pressure_union` = unique composite tiles over all phases and offsets / 256):

| scene | static tiles (d=0) | unique per phase | union | pressure | codewords | exact | tile MSE (levels²/px) | ROM banks |
|---|---|---|---|---|---|---|---|---|
| platformer_a | 133 | 133-133 | 133 | 0.52 | 133 | yes | 0.0000 | 10 |
| platformer_b | 110 | 149-163 | 532 | 2.08 | 256 | no | 0.0028 | 10 |
| proc_hills | 49 | 49-49 | 82 | 0.32 | 82 | yes | 0.0000 | 10 |
| tiny-ski_0 | 105 | 292-364 | 1896 | 7.41 | 255 | no | 0.0116 | 10 |
| tiny-ski_1 | 61 | 75-88 | 243 | 0.95 | 243 | yes | 0.0000 | 10 |
| tiny-dungeon_0 | 68 | 172-240 | 1316 | 5.14 | 256 | no | 0.0835 | 10 |
| tiny-dungeon_1 | 79 | 186-241 | 1205 | 4.71 | 256 | no | 0.0802 | 10 |
| proc_hills_far1 (far = hills BG1, sky off) | 42 | 46-54 | 264 | 1.03 | 256 | no | 0.0002 | 10 |

How to read the table:
* With a pressure ≤ 1 (platformer_a, proc_hills with the sky as far layer, tiny-ski_1), all phases are
  exact. In platformer_a the far strip falls into a single DMG level, so the parallax is not visible on
  the DMG at all.
* Busy far layers (tiny-ski, tiny-dungeon: the whole terrain used as far layer) need 5–10x the
  codebook. Shared VQ to 256 tiles then costs 0.01–0.08 levels² MSE per pixel.
* Even one phase alone (all coarse offsets) can exceed 256 tiles (tiny-ski_0: 292–364).
* Practical rule: bake parallax only for far layers with low tile variety (sky, distant hills).

## 3.5 Metrics, visualizer, ROM
See docs/vq_metrics.md (generated by `python -m tools.vq.visualize`) and `tools/vq/metrics.py`.
`tools/vq/scene_rom.py` + `runtime/vq_scene.asm` build a 32 KiB DMG ROM per scene:
* it loads the codebook to $8000;
* it rebuilds the BG map from the source-class map through `LUT_Tile_Remap` (page-aligned at
  $4000; 8-bit class ids when ≤ 256 classes, else 16-bit);
* it pans the window over the 240x160 scene with SCX/SCY.

`tests/test_vq.py` checks every screen pixel against the reconstruction at the current scroll.
