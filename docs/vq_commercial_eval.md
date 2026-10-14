# VQ evaluation on a commercial game: Super Mario Advance 2 – Super Mario World (USA, Australia)

The user supplied a ROM they own. **Nothing from the game is in this repository**: no ROM, save
states, VRAM/palette dumps, tiles or screenshots. All of that is kept outside the repo, and
`.gitignore` blocks `*.gba`, `*.ss0`, `*.ppm`, `*.zip`, `private/` and `sma2/`. This page holds numbers only.

## Capture
* Emulator: mGBA 0.10.5 (libmgba built from source), driven headlessly by
  `tools/gba_capture/mgba_capture` scripts with key presses, save states and memory pokes.
  Each snapshot holds VRAM, palette, I/O, OAM and the emulator frame.
* Menus: Start → A (Super Mario World) → A → file A → intro text → overworld (new file).
* Yoshi's Island 1 was played with scripted right/jump input.
* Other levels were entered from the Yoshi's Island 1 map tile. Before pressing A, the tile's
  level-id byte in the overworld level table in EWRAM (0x02003483, found by a RAM search) was patched.
  Level ids come from Data Crystal's SMA2 notes:
  * YI4 0x02, Iggy's Castle 0x01, VD1 0x1A, VGH 0x07, FoI1 0x1E, DS2 0x0B, YI3 0x03, VD3 0x0A.
* Castle and ghost house interiors were **not** reached: the door leads back to YI1 when the
  map entry is patched. Their entrance scenes are used instead. No water level was played
  under water; YI4 is a water-surface level.

| scene | how |
|---|---|
| title | SMW title screen over the attract-mode demo (frame about 1100) |
| overworld | Yoshi's Island map, new file |
| yi1 | Yoshi's Island 1 after about 360 frames of scripted play (grassland, BG2 at half speed: parallax) |
| yi4 | Yoshi's Island 4 (water surface, BG2 parallax) |
| vd1 | Vanilla Dome 1 (cave) |
| foi1 | Forest of Illusion 1 (forest) |
| ds2 | Donut Secret 2 (ice cave) |
| yi3 | Yoshi's Island 3 |
| vd3 | Vanilla Dome 3 (lava cave, BG2 at half speed) |
| castle | Iggy's Castle entrance (exterior) |
| ghost | Vanilla Ghost House entrance (alpha blending active) |

## Method and caveats
* Same pipeline and defaults as Phase 3 (docs/vq.md, docs/vq_metrics.md): scroll FOV,
  edge-aware levels, K = 256, metrics from `tools/vq/metrics.py`; run by `tools.vq.eval_scenes`.
* Every scene is video mode 0 with four 512x512 4bpp text BGs: BG3 = HUD (priority 0),
  BG1 = SMW "layer 1" level geometry, BG2 = background, BG0 = layer 3 effects. No affine modes
  were hit. The dumper ignores objects (Mario, enemies, coins), blending/brightness (BLDCNT),
  windows and per-scanline effects.
* *Frame agreement* = fraction of pixels where the dumper's BG composite equals mGBA's frame
  at 5-bit colour precision. It is 0.93–0.995 for most scenes, with the misses being sprites. The ghost
  house reaches only 0.695 because of alpha blending. The evaluation scores the BG composite, not the full frame.
* **Collision mask is heuristic**: every non-empty tile number on BG1 (VD3: BG0 + BG1) counts as
  solid. This includes non-solid layer-1 decoration such as bushes and also catches the HUD-free
  part of the title demo. The overworld has no solid layer.
* Parallax: BG1 (near) over BG2 (far, scrolled at exactly 1/2 of BG1 in yi1, yi4, vd3). The maps
  are 512 px wide, giving 64 coarse offsets × 8 phases and 64x18 maps.
* Remap cost is measured in PyBoy on the DMG ROM's LUT loop, the same as Phase 3.

## Results

| scene | BGs | frame agreement | unique tiles | codewords | SSIM luma | SSIM display | solid cells | Edge IoU solid | SSIM luma dither | SSIM luma downscale |
|---|---|---|---|---|---|---|---|---|---|---|
| title | 4 | 0.976 | 248 | 248 | 0.941 | 0.883 | 137 | 0.993 | 0.838 | 0.884 |
| overworld | 3 | 0.978 | 177 | 177 | 0.972 | 0.853 | 0 | n/a | 0.864 | 0.911 |
| yi1 | 4 | 0.977 | 93 | 93 | 0.949 | 0.868 | 105 | 0.973 | 0.855 | 0.913 |
| yi4 | 4 | 0.938 | 110 | 110 | 0.904 | 0.719 | 208 | 0.889 | 0.708 | 0.911 |
| vd1 | 4 | 0.991 | 39 | 39 | 0.804 | 0.741 | 396 | 1.000 | 0.679 | 0.836 |
| foi1 | 4 | 0.980 | 106 | 106 | 0.960 | 0.822 | 234 | 1.000 | 0.770 | 0.936 |
| ds2 | 4 | 0.982 | 90 | 90 | 0.988 | 0.787 | 94 | 0.928 | 0.988 | 0.895 |
| yi3 | 4 | 0.995 | 40 | 40 | 0.845 | 0.674 | 494 | 1.000 | 0.819 | 0.814 |
| vd3 | 4 | 0.933 | 94 | 94 | 0.759 | 0.330 | 30 | 0.997 | 0.671 | 0.444 |
| castle | 4 | 0.953 | 108 | 108 | 0.958 | 0.845 | 340 | 0.908 | 0.874 | 0.849 |
| ghost | 4 | 0.695 | 105 | 105 | 0.997 | 0.904 | 439 | 0.987 | 0.996 | 0.818 |

Means: SSIM luma 0.916, SSIM display 0.766, Edge IoU (scenes with solid cells) 0.967, unique tiles 110, scenes over 256 tiles: 0/11.

## Parallax codebook pressure

| scene | map | static tiles (d=0) | unique per phase | union | pressure | codewords | tile MSE | ROM banks |
|---|---|---|---|---|---|---|---|---|
| yi1 | 64x18 | 91 | 211-284 | 1627 | 6.36 | 256 | 0.0350 | 37 |
| yi4 | 64x18 | 63 | 201-347 | 1896 | 7.41 | 256 | 0.0193 | 37 |
| vd3 | 64x18 | 96 | 124-210 | 1226 | 4.79 | 256 | 0.0172 | 37 |

## DMG ROMs in PyBoy (cgb=False)

| scene | class ids | remap loop M/tile | LUT lookup M/tile | screen == reconstruction |
|---|---|---|---|---|
| overworld | 8-bit (183) | 19.70 | 3.00 | 1.000, 1.000, 1.000 |
| yi1 | 8-bit (121) | 19.70 | 3.00 | 1.000, 1.000, 1.000 |
| vd1 | 8-bit (80) | 19.70 | 3.00 | 1.000, 1.000, 1.000 |

## Comparison with the CC0 dataset (Phase 3.5, 14 scenes)
| | SMA2 (11 scenes) | CC0 dataset |
|---|---|---|
| mean SSIM luma (target ≥ 0.82) | 0.916 | 0.948 |
| mean SSIM display (fixed DMG shades) | 0.766 | 0.624 |
| mean Edge IoU, solid tiles (target ≥ 0.95) | 0.967 (10 scenes) | 0.994 (13 scenes) |
| scenes with Edge IoU < 0.95 | yi4 0.889, ds2 0.928, castle 0.908 | none |
| scenes with SSIM luma < 0.82 | vd1 0.804, vd3 0.759 | none |
| mean unique tiles (scroll FOV) | 110 (max 248, all ≤ 256 → exact) | 112 (1 scene > 256) |
| parallax pressure | 4.8–7.4 | 0.32–9.71 |
| LUT lookup per tile | 3.0 M (8-bit class ids) | 3.0 / 8.0 M |

## Targets
* **SSIM luma ≥ 0.82 (mean):** met at 0.916. Two scenes are below: VD1 and VD3, dark caves
  whose background shades collapse into one or two levels.
* **Edge IoU ≥ 0.95 on solid tiles:** met on average (0.967), but not per scene: YI4, DS2 and the
  castle are below. Their heuristic layer-1 masks include shaded and anti-aliased decoration
  with more than 4 distinct luminances per tile.
* **Remap ≤ 8 M-cycles per tile:** met at 3.0 M in all three ROMs. Every PyBoy screen matched the
  reconstruction exactly.
* **Parallax:** none of the three parallax scenes fits one 256-tile codebook (pressure 4.8–7.4).
  Shared VQ costs 0.017–0.035 levels² MSE per pixel and needs 37 MBC5 banks of tilemaps.
