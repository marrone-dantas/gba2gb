# Homebrew port mode

`build(..., port=...)` (tools/backend/gba2gbc_core.py) turns the generic AOT
pipeline into a *port*: a GBA homebrew ELF is lifted as usual, but selected
platform functions are replaced by hand-written SM83 natives and the memory
layout is adapted to large images. No game source or data lives in this repo;
the port description only knows about a platform library.

## Port description

A dict returned by e.g. `tools/ports/pico8gba.py:port_config()`:

| key | meaning |
|---|---|
| `overrides` | `{function name: native}`; a `BL` to the function (C or Itanium-mangled C++ name, `_Z<len><name>...`) becomes `call NAT_<native>` (tools/lift/lift.py `EXTRA_NATIVES`) |
| `asm` | extra RGBDS sources linked into the ROM (the natives, `PortInit`, `PortVBlank`) |
| `inc` | include directory for generated data (e.g. prebaked tiles) |
| `defines` | `-D` symbols for runtime/gb_hal_shims.asm |

### Defines

* `ROM_SRAM` – the ARM image is stored in ROMX chunks and copied to SRAM banks
  0-7 at boot; ROM loads are redirected to that window (`CONFIG["rom_sram"]`,
  tools/hal/intercept.py). EWRAM `.bss` must then sit above the image
  (0x02018000 = SRAM bank 12).
* `VRAM_SHADOW` – GBA VRAM writes go to a readable shadow (SRAM banks 8-11,
  region `vsh`) so games that read their tile map back (collision) still work.
* `PORT_OAM` – the port owns OAM: two shadow pages ($D000/$D400) flipped by the
  port on its frame boundary; the generic sprite compose is skipped and
  `PortVBlank` runs from the VBlank ISR.
* `PORT_BGMAP` – only the displayed screen block is mirrored to $9800; tiles
  are prebaked at build time.
* `PROFILE` – LYC sampler (every 9 lines) writing PCs/banks to a ring at $D700;
  read by tools/ports/profile.py, which folds lifted labels back to ELF
  functions and source lines.

## Fixed-point source transform

tools/fixpt/float2fix.py rewrites `float` code to the 16.16 `fix16` class
(tools/fixpt/fix16.hpp, compiled as C++) so the game runs without softfloat;
it matches the PICO-8 number model. Ternaries inside `#define`s are wrapped in
`FIX16_TERN`, constant divisions are reduced to a multiply by a fraction.

## PICO-8 GBA platform (tools/ports/pico8gba.py)

Natives in runtime/ports/pico8gba_dmg.asm for `spr`, `pal`, `camera`,
`update_screen`, `CpuFastSet`; `rectfill` (BG0 overlay boxes) is a no-op.
Colours are mapped to 2bpp by luminance terciles; sprites and font are
prebaked. `wP8Flips` counts composed frames (effective frame rate).

## Running / measuring

`python -m tools.ports.play ROM --plan plan.json --frames N --fps-from F`
replays inputs in PyBoy (DMG), reports fps per 1-s window (avg/min/max), and
can save screenshots (`--shot`), a GIF (`--gif`) and watch memory (`--watch`).

## Known limits

40 sprites / 10 per line (long text lines lose characters), BG0 overlay and
extra BG layers are not shown, palettes are approximate, no audio (audio
subsystem removed by default, docs/audio.md "Audio off"). Lifted
Thumb code is roughly 10-30x slower per instruction than the original CPU, so
float-heavy or per-object loops dominate frame time.

## Cosmetic loops, array caps, OAM ranges

* `cosmetic` (manifest; ports default `{"cap": 0}`): tools/lift/cosmetic.py finds
  loops that walk one global array with a pointer stride, store only through that
  pointer (or the stack), call only drawing natives (`draw_calls`, e.g. `spr`),
  arithmetic helpers or an RNG-like helper, read no I/O register and leave no live
  register at their exit. Cap 0 patches the loop header into a branch to the exit
  (the body is not lifted); `{"cap": K}` or `{"caps": {array: K}}` keeps K elements.
* `array_caps` ({array: K or (K, elem)}): tools/lift/array_cap.py lowers loop bounds
  over any global array: end-pointer literals that are only compared, `movs/adds`
  end computations, and `cmp rN, #count`. Each patch is reported in `prog.cosmetic`.
* `oam_drop` ((lo, hi)): constant-address OAM stores to GBA objects lo..hi-1 are
  dropped (never-stored objects are not composed), for games that keep effects in a
  dedicated OAM slot range. Only the BG layer chosen by `display_bg` is composed, so
  a dedicated effect BG layer is already omitted.
* Already in the HAL: dirty-tracked OAM compose (Phase P1, per-object dirty bits)
  and hardware X/Y flip (GBA flip bits -> GB OAM attributes, also in port natives).
