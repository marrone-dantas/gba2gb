# Per-line raster tables: mode-7-like track and scanline parallax (Phase 4.2)

The DMG cannot scale or rotate lines. It can only change SCX/SCY between lines.
`runtime/hblank_mode7.asm` changes them on every line from a table, using the LCD
STAT mode-0 (HBlank) interrupt.

## Table format and frame flow
* A table has 145 little-endian words, word i = `SCY | SCX << 8` for screen line i.
  Word 144 is padding. That is 290 bytes per table.
* Tables live in ROMX (MBC5 bank given by `wM7NextBank`) or in WRAM (bank 0).
* The VBlank ISR does three things: runs `M7FrameWork`, which selects the next
  table; maps that table's bank and writes line 0; and points the HBlank ISR at
  word 1.
* The mode-0 interrupt of line L writes the values for line L+1, which gives 144
  interrupts per frame (measured).

## Two ISRs
| variant | code | M-cycles per line (measured in PyBoy) |
|---|---|---|
| stack blasting (default) | `jp` at $48 → WRAM ISR: push af/hl, `ld [rest+1],sp`, `ld sp,ptr` (self-modifying operand), `pop hl`, write SCY/SCX, `ld [ptr+1],sp`, `ld sp,saved`, pop, `reti` | 45 to `reti` (incl. the vector `jp`) + 4 `reti` + 5 dispatch = **54** |
| pinned HL (`-DM7_PINNED`) | at $48: `ld a,[hl+]; ldh [SCY],a; ld a,[hl+]; ldh [SCX],a; reti`; HL holds the table pointer all frame | 10 + 4 + 5 = **19** |

The **≤ 20 M-cycle target is met only by the pinned variant.** It needs a main
thread that only runs `halt` while the screen is drawn, with all game work done in
VBlank (`M7FrameWork`), and it clobbers A. The stack-blasting variant does what the
spec describes (save SP, POP from the LUT, write, restore). It needs no cooperation
from the main thread, but it costs 54 M per line, which is 44 % of the frame
(144 × 54 / 17556). The pinned variant costs 15.6 %.

How it was measured: PyBoy hooks at $48 and at the ISR's `reti` (`M7HblRet`)
give the measured part. The 5 M dispatch and the 4 M `reti` come from the SM83
timing; PyBoy cannot place a hook inside them.

### Interrupt latency and mid-line safety
* PyBoy puts the HBlank ISR entry 232-240 dots (stack variant) or 252-260 dots
  (pinned) after the VBlank ISR entry phase. The 8-dot jitter is the main-thread
  instruction that was running when the interrupt arrived (`halt` / `jr`).
* Latency from the mode-0 edge = 5 M dispatch, plus up to the rest of the current
  instruction (≤ 5 M, more if the main thread runs with interrupts off).
* The writes are safe as long as they land before the next line's mode 3:
  HBlank (87-204 dots) + mode 2 (80 dots) ≥ 167 dots ≈ 41 M after the mode-0 edge.
  * Pinned: SCX write ≈ 5 + 10 = 15 M → safe with a large margin.
  * Stack: SCX write ≈ 5 + 31 = 36 M → safe with no sprites (the case in both
    demos, where HBlank is about 200 dots). In the worst case (10 sprites on a line
    and a 5-M instruction being interrupted) it reaches about 41 M, which is
    marginal. **The stack variant is not guaranteed mid-line safe under heavy
    sprite load.**
* PyBoy draws a whole line at once and so cannot show mid-line tearing. This
  analysis comes from timing, not from pixels; check it on a cycle-accurate emulator
  (SameBoy, not available headless here) or on hardware.

## mode7_track demo (original)
* Files: `tests/demos/mode7_track.asm` (GB side) and `tools/mode7/mode7_tables.py`
  (tables, texture, reference).
* The texture rows encode **30 road half-width classes × 8 stripe phases**, plus 16
  sky rows. Per screen line, the table picks the row whose width and stripe phase
  match the true ground projection at that depth, and an SCX that puts the road
  centre where the projection puts it.
* That gives perspective narrowing, stripes moving towards the camera, and a
  yaw-dependent slant. It does not rotate the texture: the stripes stay horizontal.
* Tables: 32 yaws (±30°) × 8 phases = 256 tables × 290 B = 74 KiB in MBC5 banks 1-5.
  Selection is O(1) (`AddrTab`, 3 bytes per table).
* The D-pad steers and the phase advances every frame.
* The reference is simplified and in Python, not a Thumb program: `true_view` renders
  the same world with a real per-pixel projection, with rotation and perspective
  scaling, which is what GBA mode 1/2 with per-line affine parameters would show.
* Test: the PyBoy screen equals the exact table model pixel for pixel at yaws
  0/8/16/24/31.

**SSIM(true projection, DMG)**: 0.96 straight ahead (yaw 16), 0.58-0.63 at the other
yaws. The DMG cannot rotate the stripes, so that loss is inherent to the method.

Screenshots (left: true projection reference, right: PyBoy DMG):
`docs/img/mode7_track_yaw{00,08,16,24,31}.png`.

## Per-line parallax on one BG layer
`tests/demos/scanline_parallax.asm` with `tools/mode7/scanline_parallax.py`:
* The CC0 scene `platformer_b` (Kenney, Phase 3 dataset) is VQ-compiled
  (`compile_scene`) into one BG layer.
* The main thread rebuilds a WRAM table every frame (double buffered), using the
  stack-blasting ISR because the main thread is busy.
* Three bands scroll at different speeds: lines 0-55 at cam/4, 56-95 at cam/2,
  96-143 at cam.
* Test: pixel-exact against the model at cam 0/23/40/80.

This is the cheap parallax option deferred in 3.4. It needs no extra tile banks,
but it only works when the layers are separated by screen line. The Phase 3.4 baker
handles layers that overlap on the same line.

Screenshots (left: reconstruction without parallax, right: PyBoy DMG):
`docs/img/scanline_parallax_cam{00,40,80}.png`.
