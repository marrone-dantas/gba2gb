# VQ scene dataset (Phase 3.2)

No commercial ROMs were used. 14 scenes in `data/vq/scenes/*.npz` (snapshot format:
docs/vq_snapshot_format.md), rebuilt with `python -m tools.vq.dataset`. Contact sheet:
`docs/img/vq_dataset.png`.

## Sources and licenses
| pack | files (vendored in `assets/vq/kenney/`) | license |
|---|---|---|
| Kenney Tiny Ski 1.0 | sampleMap.tmx, tilemap.png | CC0 1.0 (License.txt included) |
| Kenney Tiny Dungeon 1.0 | sampleMap.tmx, tilemap.png | CC0 1.0 |
| Kenney Pixel Platformer 1.2 | tilemap-example-a/b.tmx, tilemap_packed.png, tilemap-backgrounds_packed.png | CC0 1.0 |
| Kenney 1-Bit Pack | sample_{interior,urban,fantasy,platformer}.tmx, tileset_legacy.png | CC0 1.0 |

Downloaded from https://kenney.nl/assets (2026-10-14). CC0: no attribution required; credited anyway.

## Scenes
| scene | layers (GBA BGs) | composition | collision (solid) flags |
|---|---|---|---|
| tiny-ski_0, tiny-ski_1 | BG0 objects+lift, BG1 terrain+shadows | two 240x160 views of the sample map | all object/lift cells |
| tiny-dungeon_0, _1 | BG0 objects+carts, BG1 dungeon | two views | objects + dungeon cells that are not one of the 4 most frequent (floor) tiles = walls |
| platformer_a, _b | BG0 decoration, BG1 terrain, BG2 far background strip (hofs 40) | bottom 160 rows of the sample map; 18 px tiles cropped to the central 16x16; character layer (24 px sprites) dropped | all terrain cells |
| 1bit_{interior,urban,fantasy,platformer} | BG0 | centre view; sheet background colour (71,45,60) keyed out = backdrop | all non-empty cells |
| proc_hills | BG0 brick platforms, BG1 hills, BG2 8bpp gradient sky | procedural | bricks |
| proc_cave | BG0 8bpp value-noise rock | procedural, posterized | cells > 50 % rock |
| proc_glyphs | BG0 200 random glyph tiles on a checker | procedural worst case for the codebook (≈400 distinct tiles) | none |
| brin_demo | BG0 | Phase 2 demo, frame 40 from the Unicorn reference | all non-empty tiles |

## Supplying own dumps
Put raw `vram.bin` (96 KiB), `pal.bin` (1 KiB) and `io.bin` (≥ 0x60 bytes from 0x04000000)
from an emulator into a directory (optionally `solid_bg<n>.bin`: 1024 bytes, 1 = tile number
is solid) and pass that directory wherever a `.npz` scene is accepted.
