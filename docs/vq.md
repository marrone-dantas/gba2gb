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
     luminances. It minimises the squared error plus a penalty for every neighbouring pixel
     pair at a solid pixel whose luminances differ by more than 0.05 but end up in the same level.
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
