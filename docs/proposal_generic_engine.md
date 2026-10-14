# Proposal: a generic translation + optimisation engine for playable GBA -> DMG ports

Status: design proposal (no code). Supersedes the *architecture choice* of
[proposal_playable_port.md](proposal_playable_port.md) (option A, an SMW/SMA2-specific native
engine). The diagnosis there (§1: 17-100x shortfall for pure instruction-level AOT on SMA2)
is kept and is the baseline for every number below.

Goal: one toolchain that works on many games. Game-specific knowledge is limited to small
plug-in manifests and, when nothing else works, override functions.

Legality is unchanged. The tool consumes the user's own ROM. Extracted data, traces and
manifests that embed ROM bytes are never committed. The output ROM is never distributed.

## 1. Baseline numbers (measured, from repo docs)

| item | value | source |
|---|---|---|
| DMG budget | 17,556 M-cycles/frame; 35,112 per 30 Hz tick | hardware |
| sound narrowing vs phase0 | -64% total M-cycles (728k -> 265k), 20 kernels | phase1_report |
| entry ABI frame bytes | -55% | phase1_5_report |
| Snek lag | 92.1% of frames, ~5 Hz screen | snek_slice |
| Snek 76-object compose | ~91k T = ~22.8k M-cycles per iteration | snek_slice |
| Snek runtime-resolved OAM stores | ~600 per frame; 130 float->int per frame | snek_slice |
| VQ | SSIM luma 0.916, mean 110 unique tiles per FOV, remap 3.0 M/tile | vq_commercial_eval |
| parallax | 5-7x the 256-tile budget | vq_commercial_eval |

Snek iteration ~ 3 DMG frames when idle and ~12 at the screen rate, so ~50-210k M-cycles.
SMA2 is estimated (not yet measured) at 0.6-3.6M M-cycles per game frame.

## 2. Architecture

```
user ROM ─► disassembly + CFG ─► [P] profile/coverage traces (reference emulator)
                 │
                 ▼
   (1) idiom recogniser ──► HAL calls (OAM, DMA/CpuSet, BG stream, fixmath, mixer)
                 │
   (2) whole-program IR (SSA): width inference, pointer provenance, SoA, ROM hoisting, DCE
                 │
   (3) PGO specialisation + hot-trace superblocks with guards ─► fallback to generic lift
                 │
   (6) override registry (per-game SM83/C-like functions, by address + hash)
                 ▼
          SM83 backend (existing lifter, peephole, banking)
                 │
   (4) runtime: logic/render decoupled scheduler, dirty-tracked compose
   (5) data transpilers: VQ per scene, tilemaps, sprites, audio  ◄── plug-in manifest
                 ▼
            MBC5 ROM (≤ 8 MiB) + SRAM paging
```

The plug-in manifest is per game, about 50-300 lines of JSON plus optional Python hooks.
It names what auto-detection missed or got wrong: the address of the actor table, the
level-stream decoder entry, scene boundaries for VQ, the music engine type, idioms to force
or forbid, and the override list. It holds no ROM bytes, only addresses, hashes and
parameters.

## 3. Techniques and honest expected speedups

Speedups apply to the share of time each technique affects. Ranges are estimates, apart
from rows that cite measurements.

| # | technique | what it attacks | expected effect | confidence |
|---|---|---|---|---|
| 1 | Idiom → HAL lifting | OAM builders, CpuSet/DMA loops, tilemap streaming, fixmath helpers, sound mixer | 5-20x on the matched code. Snek compose 22.8k → ~2-4k M. A DirectSound mixer → PSG driver removes the mixer from the frame entirely. Library-style code is often 30-60% of a frame. | medium (Snek), low (commercial: idioms vary by compiler/SDK) |
| 2a | Whole-program width inference | 32-bit ALU on 8-bit CPU | Kernels already -64% local; interprocedural adds 1.3-2x on the rest | medium |
| 2b | Pointer provenance at compile time | runtime address decode/bank select (~600 OAM stores/frame in Snek) | 2-4x on memory-heavy code; each resolved store ~4-8 M instead of ~30-60 | medium |
| 2c | Struct-of-arrays + 8-bit indexing | actor tables `base+i*stride` | 1.5-2x on actor loops | medium |
| 2d | ROM hoisting of const data + coverage-based DCE | WRAM pressure, bank switches, code size | small speed gain (1.1x), large size/bank win | high |
| 3 | PGO specialisation + hot-trace superblocks | 10% of code that takes 90% of time | 1.3-2x on hot paths, with guards falling back to the generic lift | medium |
| 4a | Logic 30 Hz, render 60 Hz | budget | exactly 2x budget (35k per tick); game speed preserved by running logic at the original rate / 2 with doubled per-tick deltas only where the manifest allows. Otherwise the game runs at half speed. | high (budget), medium (correctness) |
| 4b | Dirty-tracked compose | re-uploading unchanged OAM/BG | 2-5x on render in static scenes, ~1x in heavy scrolling | high |
| 5 | Data transpilers | runtime decompression and format conversion | moves work to build time. Tile remap is already 3 M/tile. | high |
| 6 | Hand-written overrides | whatever is left | per routine 5-30x. Costs human effort. | high |

Combined (not simply multiplicative, since techniques overlap):

* **Generic (1-5), no overrides:** about 5-15x less work per game frame, ×2 budget from
  decoupling, so **10-30x effective**.
* **With overrides on the top 5-20 hotspots:** 20-60x effective.

Mapped to targets:

* **Snek** needs ~6-12x for 30 Hz logic, so it **becomes playable with generic only**. This
  is the main proof point.
* **SMA2** needs 17-100x (estimate). Generic only gives roughly **8-15 Hz logic**, which is
  not playable. With overrides on the player physics, sprite AI dispatch and level
  collision, the low end (≤ ~40x) reaches 30 Hz. If the measured profile lands at the high
  end, 30 Hz on DMG is not reachable even then; CGB double speed (×2) becomes the fallback.

## 4. Which games become viable

| tier | examples (genre) | GBA CPU load | outcome on DMG |
|---|---|---|---|
| T1 | puzzle, turn-based RPG, card/board, menu-driven, VN | low, bursty | **Viable with generic only, 30-60 Hz.** Most of the work is the data transpilers (graphics through VQ, 4 shades). Probably the majority of games in this tier. |
| T2 | simple action, top-down, single-screen arcade, light platformers (≤ 6 actors, 1 BG layer) | medium | **Viable at 30 Hz** with generic plus a manifest, and a few overrides in some cases. Possibly a minority to roughly half of this tier, depending on the compiler/SDK. |
| T3 | commercial scrolling platformers/action (SMA2, Kirby, Metroid) | high, 2-3 BG layers, many actors | **Only with overrides** (20-60x). Parallax dropped or banded. 30 Hz logic is the realistic ceiling. A few showcase titles, not a general class. |
| T4 | 3D/affine-heavy, Mode 7 racing, FMV, heavy DirectSound | very high, per-pixel | **Not viable.** Only static affine is prebaked; anything dynamic is out of scope. |

## 5. Phases and acceptance criteria

Test targets: **Snek** (in repo), **SMA2** (user ROM, local only), plus **two open-source
GBA games** chosen in P0: one built with the Butano engine and one tonc/libgba-style C game.
They must have permissive licences so that traces and fixtures can live in CI.

| phase | content | acceptance |
|---|---|---|
| P0 Profiling infra (2-3 wk) | Per-function cycle/instruction profiler, coverage, memory-provenance traces in the reference emulator. Measure SMA2 instructions per frame. Pick the two OSS targets. | A profile report for all 4 games. The SMA2 figure in §1 is replaced by a measurement. A go/no-go table per tier is updated. |
| P1 Decoupling + dirty compose (2-3 wk) | Scheduler with logic at 30 Hz and render at 60 Hz. Dirty tracking in the HAL composer. | Snek stays logically exact against the reference (with the logic-tick mapping) and its lag drops from 92% to ≤ 60%. |
| P2 Idiom → HAL (4-6 wk) | Recogniser (CFG pattern + semantic check by symbolic execution on small inputs) for OAM build, CpuSet/DMA, fixmath, tilemap copy, mixer. Manifest can force or forbid idioms. | Snek runs at **30 Hz with 0 lag** and is exact over 36k frames. On the OSS games, ≥ 70% of the time spent in library code is matched. 0 false matches in lockstep. |
| P3 Whole-program IR (6-8 wk) | Interprocedural width inference, pointer provenance, SoA for detected tables, ROM hoisting, coverage-based DCE. | ≥ 2x on top of P2 for the OSS games' frame time, and all lockstep tests pass. One OSS game is playable at 30 Hz. |
| P4 PGO + overrides + data (4-6 wk) | Hot-trace superblocks with guards. Override registry. Generic VQ-per-scene, tilemap and audio transpilers driven by the manifest. | Second OSS game at 30 Hz. SMA2: level 1 loads, renders and scrolls with Mario controllable, with a reported Hz figure. |
| P5 SMA2 showcase (open) | Overrides for the top hotspots from the profile. | SMA2 World 1 completable at a steady 30 Hz on DMG, or a documented measured shortfall and a CGB double-speed build that reaches it. |

## 6. Risks

* **Idiom brittleness:** commercial code is compiled by different SDKs with different
  inlining, so pattern matching misses or mismatches. Mitigation: semantic verification of
  each match (symbolic or randomised equivalence, like the existing 1000-seed kernel tests)
  plus manifest overrides.
* **Soundness of whole-program assumptions:** indirect jumps, self-modifying IWRAM code and
  function pointers in tables break provenance. Mitigation: profile-guarded assumptions with
  fallback to the generic lift, which costs speed rather than correctness.
* **Frame decoupling changes game feel/timing:** some games tie physics to the 60 Hz frame.
  Mitigation: half-speed mode by default, and the manifest opts into delta scaling.
* **Coverage-based DCE removing rarely used code:** keep the generic lift for uncovered
  code, and make DCE affect only placement in banks, not existence.
* **SMA2 may stay out of reach generically:** this is accepted up front. SMA2 is the stress
  test; the generic engine's success metric is T1/T2.
* **Effort:** about 6-8 person-months to P4. Overrides for SMA2 add an open-ended cost.

## 7. Reuse

* Lifter, sound/profile narrowing and entry ABI: the backend and the generic fallback.
* Peephole, banking, SRAM paging: unchanged.
* HAL (OAM mirror, compose, camera, HBlank ISR): becomes the target of idiom lifting.
* VQ plus its metrics, the affine prebake and the audio converter: the data transpilers.
* Lockstep harness: the correctness gate for every phase.

## 8. Recommendation

Build the generic engine in the order P0 → P1 → P2. Decoupling and idiom lifting give the
biggest measured-grounded wins, and Snek is the proof point at 30 Hz. Treat T1/T2 as the
product, and SMA2 as a showcase that will need per-game overrides. Re-evaluate SMA2 after
P0 measures its real instructions per frame.
