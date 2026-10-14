# Phase 2 demos

The Tonc demo sources (`obj_demo`, `key_demo`, `brin_demo`) are not available as complete
files in the libtonc (MIT) or tonc book (CC BY-NC-SA 4.0) repositories, and they depend on
libtonc ARM/IWRAM routines, BIOS calls and (key_demo) a mode-4 bitmap. **All demos here are
original Thumb-only rewrites** with the same behaviour, written for this project; no Tonc
code or art is copied. Artwork is procedural (`tools/hal/make_assets.py` → `assets.h`).

| demo | status | what it exercises |
|---|---|---|
| obj_demo.c | rewritten (Tonc obj_demo equivalent) | sprite moved by D-pad, flips with A/B, VCOUNT wait |
| key_demo.c | rewritten (sprite version instead of mode 4) | KEYINPUT state per key, `swi 5` |
| brin_demo.c | rewritten (own brick art, 32x32 map, SBB 30) | BG0 tiles/map, scroll |
| oam_stress.c | original | >40 sprites, >10 per line |
| input_test.c | original | all 256 KEYINPUT combinations |
