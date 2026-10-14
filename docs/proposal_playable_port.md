# Proposal: a playable Super Mario Advance 2 on DMG

> **Update:** the architecture choice below (game-specific engine) is superseded by
> [proposal_generic_engine.md](proposal_generic_engine.md). The diagnosis in §1 still applies.

Status: design proposal (no code). Scope: turn gba2gb from "logically exact but ~5 Hz"
into "playable SMA2 at 30 Hz logic / 30 fps display on a DMG + MBC5 cart".

## 0. Legality and asset policy

* The tool takes the **user's own ROM** as input at build time. Nothing derived from the ROM
  (code, graphics, levels, music, symbol tables with embedded data) is committed or shipped.
* The repo only contains: the transpiler, hand-written engine code (clean-room, written from
  public behavioural knowledge of SMW/SMA2), format *descriptions*, and ROM hash checks.
* The output `.gb` is for personal use on hardware/emulators the user owns; never distributed.
  This mirrors the model used by snesrev/smw ("You need a copy of the ROM to extract game
  resources ... then the ROM is no longer needed").

## 1. Honest diagnosis: instruction-level AOT cannot reach 30 fps

### 1.1 Budgets

| quantity | value |
|---|---|
| DMG CPU | 4.194 MHz T = 1.048 M M-cycles/s |
| per 59.73 Hz frame | **17,556 M-cycles** (~10% lost to VBlank copies/ISR in practice) |
| per 30 Hz logic tick (2 frames) | **35,112 M-cycles** |
| CGB double speed, per 30 Hz tick | 70,224 M-cycles (optional, not DMG) |
| GBA CPU per frame | 280,896 cycles @ 16.78 MHz |

### 1.2 Measured cost of our lifting

* Phase 1 kernels: sound narrowing cut total cost 728k -> 265k M-cycles (-64%), but a single
  `k19_tilemap_hash` call is still 107k M-cycles (6 DMG frames) and `k03_enemy_fsm` 24.5k
  (1.4 frames) — the latter is roughly *one* SMA2 sprite's worth of state-machine work.
* Snek slice: 92.1% lag frames (33,163/36,000), ~5 Hz screen. One 76-object compose alone is
  ~91k T = ~22.8k M-cycles, i.e. **more than a whole DMG frame**, before game logic, ~600
  runtime-resolved OAM stores and 130 soft-float conversions.
* Observed expansion, from kernels: ~10-30 SM83 M-cycles per lifted Thumb instruction
  (32-bit ALU via HRAM regs, flag materialisation, bank-switched memory accesses).

### 1.3 Projection for SMA2 (estimate, to be confirmed by a profile run)

SMA2 is a commercial engine running ~10-12 actors, Mario physics, layer-2/3 scrolling,
collision against a 16x16 Map16 level, and DirectSound mixing. Assume conservatively it
retires **60-120k Thumb/ARM instructions per frame** (its CPU is busy a large fraction of
280k cycles). At 10-30 M/instr:

    60k x 10 = 0.6 M  ...  120k x 30 = 3.6 M M-cycles per game frame
    budget at 30 Hz  = 35k  -> shortfall 17x .. 100x
    CGB double speed = 70k  -> shortfall  9x .. 50x

Even a further 2x from whole-program narrowing leaves us an order of magnitude short.
The problem is not the backend quality; it is that **emulating the GBA engine's
*implementation* (32-bit pointers, generic OAM builder, fixed-point maths, audio mixing)
is the wrong unit of translation.** The original SNES SMW ran on a ~3.58 MHz 65816 with
8/16-bit data — the game's *design* fits 8-bit machines; the GBA port's code does not.

## 2. Prior art (what it tells us)

* **Static recompilation** (N64Recomp, XenonRecomp, jamulator): translate whole binaries to C
  for a *faster* host. Works because host >> guest. Our host is ~16x slower than the guest,
  so the lesson we keep is the tooling (symbol/function metadata, overlays, per-function
  overrides), not the "recompile everything" approach.
* **Decomp/reimplementation ports** (SM64/OoT PC ports, snesrev/smw): the game's logic is
  rewritten as readable code, assets are extracted from the user's ROM at build time. This
  is the model that scales: snesrev/smw is a full, playable SMW reimplementation in C with
  a ROM-asset extractor.
* **SMW disassemblies** (SMWDisX and earlier SMWCentral all.log disassemblies) and the
  Lunar Magic ecosystem document level formats (objects/sprites lists, Map16, layer
  modes), sprite tables and physics constants publicly. SMA2's levels are SMW's levels
  re-encoded; a format bridge SMA2 -> "SMW-like intermediate" is a reverse-engineering task
  we can do from our own tracer (we already have lockstep + memory diff tooling).
* **8-bit platformer engines** (GB homebrew, GB Studio, Super Mario Land itself, unofficial
  SMB demakes): a scrolling platformer with ~6-8 actors at 60 Hz fits a DMG when the
  engine is native 8-bit code with metatile collision and a fixed OAM layout.
* **Hardware constraints** (Pan Docs): 40 OBJs, 10 per scanline, 8x16 mode, OAM DMA;
  MBC5 maps up to 8 MiB ROM / 128 KiB SRAM; CGB double speed exists but is CGB-only.

## 3. Architectures (ranked)

### A. (Recommended) Semantic re-target: "HLE of the game engine"

Write a native SM83 platformer engine whose *behaviour* is specified by SMW/SMA2 (Mario
physics table-driven, sprite state machines, level object decoder), and feed it with data
the transpiler extracts from the user's ROM. AOT survives only for **leaf logic** where
behaviour is hard to re-specify (selected sprite AI routines, block interactions), lifted
with whole-program 8/16-bit narrowing and compile-time resolved pointers.

Pipeline:
1. **Engine identification** (offline, from user's ROM + our tracer): locate actor table,
   level header/object streams, Map16 table, player physics routine, sprite dispatch table,
   music sequence format. Output: `sma2_layout.json` (offsets/hashes only, no data).
2. **Data transpiler** (build time): levels -> pre-decoded Map16 metatile columns in MBC5
   banks; per-level **VQ tilesets** (reuse VQ: SSIM 0.916, mean 110 unique tiles per FOV)
   with column streaming; sprite graphics -> pre-shaded 2bpp 8x16 frames; music -> our
   PSG converter (drop DirectSound samples or render to short wave-channel loops).
3. **Native engine** (hand-written SM83): 8.8 fixed-point physics, 16x16 metatile collision
   via lookup, actor slots (max 8 active), fixed OAM allocation with flicker multiplexing,
   camera = SCX/SCY + column streaming in VBlank. No 32-bit types at runtime.
4. **Leaf AOT**: sprite AI functions dispatched by ID, lifted with entry ABI + narrowing; any
   routine whose profile exceeds its budget is promoted to the hand-written list.

Frame budget at 30 Hz logic (35k M-cycles per tick):

| slice | M-cycles | note |
|---|---|---|
| Mario physics + input | 2,500 | table-driven, 8.8 fixed |
| tile collision (Mario + 8 actors) | 4,000 | ~400/actor, LUT-based |
| actor AI (8 x ~1,500) | 12,000 | native or narrowed AOT leaf |
| OAM build (fixed slots, no runtime resolve) | 3,000 | vs ~22.8k for Snek's composer |
| camera + column stream (2 columns/tick) | 3,500 | 18 tiles x 2, VBlank-split |
| audio driver (both frames) | 2,000 | PSG sequencer |
| ISR/VBlank overhead, slack | 8,000 | ~23% headroom |
| **total** | **~35,000** | fits; on CGB double speed -> 60 Hz logic |

Feasibility: high technically, effort high (largest engineering cost is behavioural
fidelity per sprite). Fidelity target is "plays like SMA2", not cycle-exact.

### B. Hybrid AOT with whole-program narrowing + 30 Hz logic

Keep lifting the whole game, but: whole-program pointer resolution (every LDR/STR to a
known region becomes a direct banked access), global range analysis to 8/16 bits, HLE of
library calls (OAM build, DMA, mixing, division/BIOS), drop the GBA renderer in favour of
HAL. Best case maybe 5-10x over today; projection in 1.3 still leaves 2-20x short.
Feasibility: low for 30 fps; useful as a *fallback* for leaf routines in A.

### C. Frame-split / time-dilated execution

Run logic at 15 Hz or slower with interpolated rendering. Cheap, but even 15 Hz needs a
~8-50x speedup over pure AOT, and input latency becomes unplayable. Only acceptable
for cutscenes/map screens.

### D. Co-processor cart (out of scope, noted for completeness)

An MCU/FPGA on the cart running the GBA code and streaming tiles/OAM (like modern
flash-cart "enhancement chips"). Defeats the "runs on DMG" goal.

## 4. Display strategy (applies to A)

* **BG**: one playfield layer only on DMG; layer 2 parallax needs 5-7x the 256-tile budget
  (vq_commercial_eval), so parallax backgrounds become a flat colour or a window-band
  strip with HBlank SCX raster (reuse the HBlank raster ISR) for 1-2 bands.
* **Tiles**: per-level precomputed VQ sets (<= 192 BG tiles resident) plus per-area swap
  points at doors/pipes; streaming of 2 new columns per tick during VBlank.
* **Sprites**: 8x16 mode; Mario = 4 OBJs, typical enemy = 2-4 OBJs; fixed slot table and
  per-tick OAM rotation to turn >10/line overflow into flicker instead of dropouts.
* **Palettes**: 4 shades, OBP0/OBP1 for contrast; reuse the luma mapping from VQ.

## 5. Phases, milestones and acceptance criteria

| phase | content | milestone / acceptance |
|---|---|---|
| P0 Profile & map (2-3 wk) | Trace SMA2 in our reference emulator: instr/frame, hot functions, actor table, level stream locations. Produce `sma2_layout.json` (offsets + hashes only). | Measured instr/frame confirms or corrects §1.3; actor table and level stream decoded for World 1-1 (render level map to PNG locally, not committed). |
| P1 Data transpiler (3-4 wk) | Levels -> Map16 columns in MBC5 banks; per-level VQ tilesets; sprite frames; music -> PSG. | Static DMG ROM scrolls YI1 at 60 fps with correct terrain; tiles <= 192 resident; SSIM luma >= 0.85 vs downscaled GBA frames. |
| P2 Native Mario (4-6 wk) | Physics, collision, camera, input on DMG. | Mario run/jump trajectories within ±1 px of GBA trace over 10 recorded inputs; logic tick <= 12k M-cycles; 0 lag frames at 30 Hz. |
| P3 Actors (6-10 wk) | Actor slot system, 15-20 most common sprites (Goomba/Koopa/Rex, coins, blocks, power-ups); leaf AOT for the rest where it fits. | World 1 completable start to finish; worst-case tick <= 35k M-cycles with 8 actors; flicker but no dropped gameplay sprites. |
| P4 Breadth & polish (open) | Overworld, remaining sprites, bosses, audio, save to SRAM; optional CGB double-speed 60 Hz build. | Full game completable; lag < 2% of frames over a 30-min playthrough. |

## 6. Risks

* **Behavioural fidelity**: hand re-specified sprite AI drifts from SMA2. Mitigation: lockstep
  traces of actor RAM from the reference emulator as tests (reuse snek lockstep harness).
* **Format reverse engineering**: SMA2 encodes levels differently from SNES SMW. Mitigation:
  P0 time-boxed; fallback is capturing decoded Map16 from emulator RAM at level load.
* **VRAM pressure**: busy levels exceed 192 tiles even with VQ. Mitigation: lower VQ
  codebook per level, accept SSIM drop, area splits.
* **ROM size**: 8 MiB MBC5 is ample (pre-decoded levels ~2-3 MiB estimated) but watch bank
  fragmentation.
* **Scope creep**: ~100 sprite types in the game. Milestones target a subset first.
* **Legal**: keep extracted data out of the repo; CI uses only synthetic fixtures.

## 7. Reusable from the current pipeline

* Thumb->SM83 lifter with sound narrowing, entry ABI, peephole -> leaf AOT in A.
* Reference emulator, lockstep harness, memory diff tooling -> P0 tracing and P2/P3 tests.
* VQ tile compression + metrics -> per-level tilesets.
* HAL: OAM mirror, camera, HBlank raster ISR -> engine display layer.
* PSG/DirectSound->DMG audio converter -> music.
* EWRAM->MBC5 SRAM paging -> save data and large actor/level state.
* Soft-float: dropped from runtime (no floats in engine); kept only for leaf AOT if needed.

## 8. Recommendation

Adopt **A (semantic engine re-target)**: native 8-bit engine + ROM-driven data transpiler,
AOT restricted to leaf routines. It is the only option whose budget closes at 30 Hz on a
DMG (~35k M-cycles per tick with ~23% slack), and it reuses most of what has been built.
Start with P0 to replace the §1.3 estimate with a measured instr/frame number; abort
criterion: if P2 cannot keep Mario + camera + collision under 12k M-cycles per tick, revisit.

## Sources

* snesrev/smw — SMW C reimplementation, ROM-asset extraction model: https://github.com/snesrev/smw
* N64Recomp — static recompilation tooling: https://github.com/N64Recomp/N64Recomp
* SMWDisX — SMW disassembly: https://github.com/IsoFrieze/SMWDisX
* Pan Docs, OAM limits: https://gbdev.io/pandocs/OAM.html
* Pan Docs, MBC5 (8 MiB): https://gbdev.io/pandocs/MBC5.html
* Pan Docs, CGB registers (double speed): https://gbdev.io/pandocs/CGB_Registers.html
