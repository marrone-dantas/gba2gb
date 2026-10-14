# Phase 5 Part B: Snek GBA vertical slice

Game: Snek GBA by blueOkiris, https://github.com/blueOkiris/Snek-GBA (GPL-3.0),
vendored unmodified in `third_party/snek-gba/` (see UPSTREAM.md). Everything built
from it is GPL-3.0; ROMs are built into `build/` and not committed.

## B1: original GBA build and mGBA reference

`make -f tools/slice/Makefile.snek` → `build/snek/snek.{elf,gba}`:
arm-none-eabi-gcc 14.2, `-mcpu=arm7tdmi -mthumb -Os`, our ARM crt0 + link script
(`tests/demos/crt0.s`, `gba.ld`), libgcc (soft-float, division) and
`tools/slice/snek_libc.c` (newlib's rand/srand algorithm without newlib's reentrancy
and stdio dependencies). `-Os` instead of upstream's `-O2` keeps .text + .data at
8128 bytes, inside the HAL's 8 KiB ARM image window (`-O2`: 9016 bytes).

`python -m tools.slice.snek_ref` runs it in the headless mGBA capturer (title, START,
gameplay, turn, death): `docs/img/snek_gba_ref.png`.

Game facts that matter for the port:
* no vsync at all: the main loop runs free and scales the movement by the elapsed
  time read from timer 0 (262144 Hz), in `double`/`float` (soft-float helpers);
* timer 1 (16384 Hz) seeds `rand` when START is pressed on the title;
* all OAM accesses go through pointers stored in `g_state` (non-constant addresses);
  76 objects (head, 64 body slots, frog, 10 score digits);
* BG0 (playfield, SBB 1) plus BG1 overlays (SBB 2 "SNEK", SBB 3 "DEAD") selected by
  BG1CNT priority.
