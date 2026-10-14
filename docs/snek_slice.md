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

## B2: native helpers and timers

Soft-float / integer helpers used by Snek (`dadd`, `dmul`, `f2iz`, `idiv`,
`lmul`, …) are replaced by SM83 natives in `runtime/gb_softfloat.asm` (lifter
`NATIVES`, codegen `call NAT_*`). Lockstep against the real libgcc:
`tests/test_softfloat.py` (see `docs/softfloat.md`).

GBA timers 0 and 1 (`TM0D`/`TM1D`/`TMxCNT`) are emulated by
`runtime/gb_timer_shims.asm` from the GB TIMA clock (resolution 1/16384 s).
Covered by `tests/test_timer.py`.

## B3: HAL for Snek on the DMG

Build: `python -c "from tools.slice.snek_bot import build_gb; build_gb()"` →
`build/snek/snek_dmg.gb` (+ `.sym`, `.map`). The ROM is built, never committed
(GPL-3.0: it is a derivative of `third_party/snek-gba`, whose source and LICENSE
sit next to the tools that produce it). Default backend: `prune="sound"` (flag
liveness + proven value ranges, `docs/bitwidth_pruning.md`).

What the HAL had to learn:

* **MBC5 multi-bank kernel.** The transpiled kernel is ~43 KiB. `codegen.generate()`
  packs whole functions into ROMX banks 2, 3, … (bank 1: soft-float, reached through
  ROM0 stubs `NAT_x`). Cross-bank `call` → `FarCall`, cross-bank jumps → `FarJump`,
  and a cross-bank jump to a function entry (Thumb tail call) → `call FarCall; ret`
  (`runtime/gb_bank.asm`). Splitting only at function entries matters: a function
  that spans two banks would `ret` with the wrong bank mapped (this crashed Snek
  after a few hundred frames). The one function larger than a bank (`main`) is split
  at instruction boundaries and its `ret`s in continuation banks go through
  `RetBank` (re-map the entry bank from ROM0, then return). Everything the VBlank
  ISR or several banks call (HAL, timer shims) lives in ROM0.
* **OAM mirror and pointer-based OAM.** All Snek OAM accesses go through pointers in
  `g_state`. `HAL_DYN_ADDR` / `HAL_DYN_STORE` route `$07xxxxxx` to the 128-object
  mirror `wGbaOAM` at `$D400`, track the highest object written (`wObjMax`), a
  per-object "live" bitmap and `wOamDirty`. Constant-address OAM stores set
  `wOamDirty` too.
* **Sprite composer with more than 40 objects.** Snek has 76 objects. In camera mode
  (`GbaView = 1`, enabled automatically for pointer-based OAM or > 32 objects) the
  composer draws the pinned objects first (score digits, `GbaPinLo..GbaPinHi`), then
  the rest starting at a rotating base; when the 40-sprite / 10-per-line budget
  drops objects, the base advances, so overflow shows as flicker, not as permanently
  missing body segments.
* **Camera.** GBA pixels map 1:1; the 160×144 window follows the head
  (`CamUpdate`, SCX clamped to 0..80, SCY to 0..16). Pinned objects ignore the camera.
* **BG1 sparse overlay.** "SNEK" / "DEAD" (BG1, SBB 2 / 3) are recorded as a sparse
  list of non-empty map entries (`OvRecord`) and drawn over BG0 when BG1CNT puts BG1
  in front (`Bg1Refresh` on BG1CNT / DISPCNT writes).
* **Tiles before palettes.** Snek loads tiles before palettes, so raw 4bpp tiles are
  shadowed in SRAM banks 14 (BG) / 15 (OBJ) and reconverted after palette writes;
  shades use gamma thresholds (12/36/72) in camera mode.
* **Compose on key read.** Snek never waits for vsync; the HAL composes OAM once per
  GB frame at the first KEYINPUT read after an OAM change (`HAL_KEYINPUT_END`).
* **Codegen speed-ups found on the way:** constant shifts (`lsls r1, r1, #23`) are now
  inline byte moves plus at most 7 register bit steps instead of the bit-loop helpers.

Bugs fixed during B3 (each caused a hang or a crash): `HAL_DYN_STORE .oam`
clobbered `c`/`e` (source slot / byte count), `WaitVram` clobbered `a` in the
overlay walk, a function split across banks returned into the wrong bank.

Test: `tests/test_snek_gb.py` (MBC5 header; 3000-frame bot run without crashes,
stack in `$D800-$DFFF`, ≥ 1 frog eaten, g_state identical to the Unicorn reference
at every KEYINPUT read).

Known limits: performance (see B4) — a gameplay iteration of Snek costs ~10 GB
frames, because every iteration walks all 64 body slots (float copies,
`set_obj_pos` through dynamic pointers). The game scales movement by the elapsed
timer value, so it plays at the right speed but at ~6 updates per second.

## B4: long bot run and state comparison

`python -m tools.slice.snek_bot 36000` (PyBoy, `cgb=False`, build at d34fdf3).
A greedy bot steers toward the frog and restarts with START after DEAD.

| metric | value |
|---|---|
| GB frames run | 36,000 (full target, 10 min of DMG time) |
| games / deaths | 20 / 19, max score 3 |
| KEYINPUT reads (game-loop iterations) | 2,863 (~12.6 GB frames per iteration) |
| lag frames (no compose) | 33,163 / 36,000 = **92.1 %** (title 79.7 %, game 92.8 %, dead 74.0 %) |
| crashes (PC >= $8000 or SP outside $D800-$E000) | 0; native stack low-water $DFE8 |
| Unicorn replay of the GB-read KEYINPUT/TM0D/TM1D | **2,863 / 2,863 g_state snapshots identical** (sha256 prefix 4cbd8e0af124a88e on both sides) |

The reference runs the original Thumb build in Unicorn and feeds it, in program
order, exactly the key and timer values the GB build read, so the comparison
covers positions, floats, score, the rand-driven frog and pointers. The only
non-matching counter is one extra timer read by the reference after the last
KEYINPUT (end of the replay, not compared).

Images: `docs/img/snek_side_by_side.png` (GBA via Unicorn at the same KEYINPUT
index | DMG at GB frames 120/700/1500; the DMG is still in LCD-off init at frame
120), `docs/img/snek_ref_vs_dmg.png` (mGBA reference `snek_gba_ref.png` | DMG
gameplay) and `docs/img/snek_dmg.gif` (GB frames 400-1600, every 4th frame;
identical frames merged).

Lag: game-loop iterations take ~3 GB frames when the snake does not step and
~13 when it does (64 body objects repositioned: ~600 run-time dispatched OAM
stores, 130 float->int conversions, then a 76-object compose of ~91k T-cycles).
Because Snek scales movement by the measured timer delta, game speed in
wall-clock time is preserved; only the display update rate (~5 Hz) is low.
Next steps: compile-time OAM resolution for the body array (avoid HAL_DYN_*),
incremental compose (only objects stored since the last compose).
