# GBA scene snapshot format (Phase 3.1)

Input of `tools/vq/vram_scene_dumper.py` and the VQ compiler. Defined in `tools/vq/snapshot.py`.

| field | size | content |
|---|---|---|
| `vram` | 96 KiB | 0x06000000-0x06017FFF |
| `pal` | 1 KiB | 0x05000000-0x050003FF (BG palette = first 512 bytes) |
| `io` | ≥ 0x60 bytes | I/O from 0x04000000 (DISPCNT, BG0-3CNT, BG0-3HOFS/VOFS) |
| `oam` | 1 KiB, optional | not used by the BG dumper |
| `solid_bg<n>` | 1024 bytes, optional | 1 = GBA tile number (map entry bits 0-9) of BG n is solid (collision) |
| `name`, `source`, `license` | strings, optional | provenance |

On disk: either one `.npz` with these arrays, or a directory with `vram.bin`, `pal.bin`,
`io.bin` (and optionally `oam.bin`, `solid_bg<n>.bin`, `meta.json`). Raw memory dumps from
any emulator (e.g. mGBA's memory viewer export) can be dropped into such a directory.

## Dumper
`python -m tools.vq.vram_scene_dumper SNAPSHOT --out DIR` writes `layer<n>.png` (RGBA),
`composite.png` and `scene.json`.
Supported: modes 0 and 1 text BGs (BG0-BG3), 4bpp with 16 palette banks and 8bpp, h/v flips,
all text sizes with the screen-block layout, 9-bit scroll, priorities (ties: lower BG number
on top), transparency and backdrop. Not supported: affine BGs (mode 1 BG2, mode 2), bitmap
modes 3-5 (reported in `unsupported`), objects, windows, blending, mosaic.

Tests (`tests/test_scene_dumper.py`): encoder → dumper round trip on a 3-layer scene
(4bpp single/multi-bank, 8bpp, 512x256 and 256x512 maps, scroll, priorities), flips and
banks actually used, solid mask, and equality with the Unicorn reference renderer on
`brin_demo`.
