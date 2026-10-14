# Affine OBJ baking (Phase 4.1)

The DMG cannot rotate or scale sprites. `tools/affine/affine_lut_baker.py` turns a
program's affine sprite into pre-rotated frames at build time. It runs automatically
from `build(..., hal=True)` (`lower.hal_sections`). Options go in `affine={...}`:
`nrot` (32), `scales` ((1.0, 2.0)), `chunk` (128), and `mode` (auto/resident/stream).
CLI: `python -m tools.affine.affine_lut_baker build/demos/affine_demo.elf --rot 32 --scales 1,2`.

## Detection
* **OBJ_AFFINE writes.** The static I/O interceptor resolves every OAM access to a
  constant address. A store to an OAM offset that is 6 mod 8 is an affine parameter:
  group `o // 32`, parameter `(o % 32) // 8` = pa/pb/pc/pd. These stores are listed
  in the report (`param_writes`).
* **Affine flag.** A short GBA reference run (Unicorn, 4 frames, no input) shows which
  objects have attr0 bit 8 set, along with their size and tile number. Their 4bpp
  tiles and OBJ palette are read from that snapshot. Baking therefore uses the
  sprite pixels and palette as they are at frame 4. A program that changes the
  affine sprite's graphics later is not supported.

## Baking
Each frame is rendered with the exact GBA rule for a non-double-size box: texture =
P·(screen − centre) + centre, with P = (pa pb; pc pd) and pa = cos/s, pb = −sin/s,
pc = sin/s, pd = cos/s rounded to 8.8. That gives `nrot` angles × len(scales) frames.
Frames are converted to 2bpp with the Phase 2 OBJ luminance levels and stored in 1D
tile order, starting at MBC5 bank 3 (`FRAME_BANK0`). The demo uses 32 × 2 frames of
32×32 pixels: 64 × 256 B = 16 KiB, which is exactly one bank.

## O(1) frame selection
After every pa or pb store, the translated code calls `HAL_AFFINE_SEL`; the matrix
values still go to the OAM mirror. The shim quantises each value as
`q = clamp(v >> shift, −32, 31)`, with shift = 3 for scales ≥ 1. It then reads one
byte from a 64×64 LUT in ROMX bank 2 (`AffLut`, 4 KiB), indexed by `qa·64 + qb`, which
gives the nearest (angle, scale) frame. Measured cost: **113-118 M-cycles** per call,
two calls per frame. pc/pd are ignored: only rotation with uniform scale is modelled.
The worst angle error measured over 300 frames is 7.2°. That is half a step (5.6°)
plus the LUT cell error.

## Getting frames into VRAM
OAM tile data lives in VRAM, so switching ROM banks alone changes nothing on screen.
* **Resident mode** (chosen when `base + frames·tiles ≤ 256` OBJ tiles): `AffInit`
  copies every frame into VRAM at boot while the LCD is off. Selecting a frame is
  then just a tile-index swap (`AffRes` table → `wAffTile`).
* **Stream mode** (the demo: 1024 tiles do not fit): two VRAM slots (tiles 224-239 and
  240-255). During VBlank, the ISR copies `chunk` bytes (128) of the selected frame
  from ROMX into the back slot, using unrolled `ld a,[hl+] / ld [de],a / inc e`. When
  the frame is complete it swaps the slots (`wAffTile`). A new frame only starts once
  the hardware OAM no longer shows the back slot (`wAffShown` is set after the OAM
  DMA), so the slot on screen is never overwritten.

### VBlank budget (stream mode, measured in PyBoy DMG)
| item | M-cycles |
|---|---|
| VBlank period (10 lines) | 1140 |
| OAM DMA + ISR base (Phase 2) | ~221 |
| one 128-byte chunk (`AffStream.go` → return) | 764-805 |
| idle check (nothing to copy) | 28 |

A 256-byte frame takes 2 VBlanks. The display lags the selection by at most 2 frames
(measured), so rotation is capped at 30 new frames per second. Every chunk copy
starts and ends inside VBlank (the strict checker hooks `AffStream.cp`/`.cpend`, with
zero violations). A chunk of 192 B or more would not fit next to the DMA.

## Runtime state
`wAffTile`, `wAffWant`, `wAffHave`, `wAffShown`, and so on live in the HAL state page
($D2xx). In `Compose`, an affine object (attr0 bit 8) uses `wAffTile` as its tile base
with 1D stride and no flips. The attr1 bits 9-13 are the group, not flips.

## Demo and tests
`tests/demos/affine_demo.c` is original Thumb code. It rotates a 32×32 ship by 1/256
turn per frame; A toggles 2× zoom, B reverses the rotation, and the D-pad moves it.
`tests/test_affine.py` drives the GB program with a 300-frame input sequence,
recording the keys the GB program actually read in each loop iteration. It then
feeds those same keys to the GBA reference and checks, per iteration (at `Compose`):
the selected frame equals the exact LUT model applied to the GBA pa/pb; the angle
error is ≤ 5.6° + 4.5°; the displayed slot holds the baked frame `wAffHave` byte for
byte; the shadow OAM equals the spatial OAM model; the stream never writes the
displayed slot; and every VRAM/OAM write is in VBlank/HBlank.

Screenshots (GBA | DMG): `docs/img/affine_demo_f{001,040,120,200,300}.png`.

## Limits
* One affine group per program. All objects in that group must share size and tiles.
* Double-size affine objects (attr0 bits 8+9) are rejected at bake time.
* Graphics and palette are frozen at bake time (reference frame 4).
* Shear and non-uniform scale (pc/pd) are not represented.
* The OBJ outline colour can merge with a dark backdrop (Phase 2 luminance rule).
* Iterations are compared by iteration count, not by GB vsync. The demo's loop
  sometimes takes longer than one GB frame (331 VBlanks for 300 iterations), as the
  Phase 2 HAL allows.
* Interceptor limit found while writing the demo: a ROM table pointer that GCC spills
  to the stack is classified as RAM, so the read goes to WRAM silently. The demo
  copies its sine table to IWRAM to avoid this. Handling stack spills properly in the
  interceptor is still open.
