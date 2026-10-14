# Phase 1 — status

## Part A (range analysis)
- **A1** `tools/profile/range_tracer.py`: dynamic tracer (Unicorn hooks), format in
  `docs/profile_format.md`; `tools/profile/mgba_range_tracer.lua` is best-effort and
  **untested** (mGBA scripting is not available headless here).
- **A2** `tools/prune/range_analysis.py`: SSA (phi on dominance frontiers + pi-nodes on
  `cmp`/`b<cc>` edges), dual unsigned/signed intervals, widening, exact enumeration of
  basic induction variables. `proven_range` (static, sound) and `observed_range`
  (dynamic hint) are stored separately in `build/ranges/<kernel>.json`.

```sh
.venv/bin/python -m tools.profile.range_tracer --all   # build/profiles/*.json
.venv/bin/python -m tools.prune.range_analysis          # table + build/ranges/*.json
```

### Width table (1000 seeds; "8" = u8/i8, "16" = u16/i16)
Counted values: instruction and phi definitions of data registers (no SP/LR, parameters,
pi copies or BL clobber placeholders). Dynamic class for phis is derived from the
incoming values.

| kernel | SSA values | static 8 | static 16 | static 32 | dyn 8 | dyn 16 | dyn 32 | unobserved |
|---|---|---|---|---|---|---|---|---|
| k01_fibonacci | 18 | 5 | 0 | 13 | 8 | 0 | 10 | 0 |
| k02_crc16 | 43 | 15 | 10 | 18 | 19 | 10 | 14 | 0 |
| k03_enemy_fsm | 111 | 48 | 1 | 62 | 86 | 12 | 13 | 0 |
| k04_aabb | 43 | 25 | 4 | 14 | 32 | 5 | 6 | 0 |
| k05_sort | 45 | 10 | 0 | 35 | 15 | 0 | 30 | 0 |
| k06_bubble_u8 | 17 | 2 | 0 | 15 | 7 | 0 | 10 | 0 |
| k07_popcount | 13 | 2 | 0 | 11 | 5 | 0 | 8 | 0 |
| k08_gcd | 17 | 0 | 5 | 12 | 0 | 15 | 2 | 0 |
| k09_mul_acc | 5 | 0 | 0 | 5 | 0 | 0 | 5 | 0 |
| k10_xorshift | 14 | 4 | 1 | 9 | 4 | 1 | 9 | 0 |
| k11_shifts_var | 18 | 5 | 0 | 13 | 7 | 0 | 11 | 0 |
| k12_clamp_sat | 25 | 6 | 11 | 8 | 6 | 11 | 8 | 0 |
| k13_abs_minmax | 12 | 1 | 0 | 11 | 2 | 0 | 10 | 0 |
| k14_isqrt | 21 | 2 | 0 | 19 | 2 | 0 | 19 | 0 |
| k15_bitrev | 16 | 7 | 0 | 9 | 9 | 0 | 7 | 0 |
| k16_carry64 | 16 | 0 | 0 | 16 | 2 | 0 | 14 | 0 |
| k17_calls | 24 | 2 | 1 | 21 | 5 | 3 | 16 | 0 |
| k18_bytes_half | 38 | 12 | 4 | 22 | 16 | 4 | 18 | 0 |
| k19_tilemap_hash | 38 | 16 | 3 | 19 | 25 | 5 | 8 | 0 |
| k20_fixed_point | 46 | 10 | 5 | 31 | 22 | 16 | 8 | 0 |
| **total** | 580 | 172 | 45 | 363 | 272 | 82 | 226 | 0 |

Soundness is checked by `tests/test_range_analysis.py`: every value observed at an
instruction definition (200 seeds) lies inside its proven range, for all 20 kernels.

### Known gaps (static vs dynamic)
- Interprocedural ranges (B0) cover direct BL only: callee params = join of call-site
  args, BL r0 = join of callee returns (k17: `sq` param proven u12; product still i32).
- Memory is not tracked: every `ldr`/`pop` result is TOP (k05/k06 arrays on the stack).
- Data-dependent loops (gcd, isqrt, popcount, `while (n--)` with `subs`/`bne`) are not
  bounded: only `cmp`-guarded counters with constant init/step are enumerated exactly.
- ADC/SBC/ROR results are TOP (k16 64-bit arithmetic).

## Part B (pruning + narrowed backend)
- **B0** interprocedural ranges for direct BL (small gain: +1 narrow value in k17).
  Stack-slot tracking was **not** implemented: the only push/pop spills in the 20 kernels
  are callee-saved registers whose values are the caller's (TOP), so it would not narrow
  anything without a memory/alias analysis of the stack arrays.
- **B1** `tools/prune/bitwidth_pruning.py` — see `docs/bitwidth_pruning.md`.
- **B2** `tools/backend/narrow.py` + `tools/backend/flags.py`; report in
  `docs/phase1_report.md` (`python -m tools.prune.report`). Lockstep: 20/20 kernels ×
  1000 seeds pass in phase0, sound and profile modes (no guard fired).

### Acceptance targets (vs Phase 0)
| target | result | status |
|---|---|---|
| −55% M-cycles | −64% total, −60.7% mean per kernel (sound) | **met** |
| −50% WRAM | −5% (442 → 418 bytes touched) | **not met** |

Where the cycle gain comes from (honest breakdown, see the `flags` column): most of it is
*not* bit-width related — flag elision and cheaper constant shifts/multiplies already give
−57% total; narrowing to 8/16-bit storage adds the remaining ~7 points (much more on
byte-heavy kernels: k12 −88%, k18 −83%, k02 −74%). k09 (−5%) is pure 32×32 MUL with
unknown operands.

Why WRAM did not move: WRAM holds the *emulated ARM stack* (callee-saved spills, LR,
local arrays) plus a few bytes of SM83 return addresses. Its layout is fixed by the
ARM code (SP-relative addresses), and register narrowing never touches it. The HRAM
register file barely shrinks either (−1%) because r0-r3 arrive as 32-bit arguments and
each register keeps the width of its widest SSA value. What would close the gap:
1. do not spill LR (returns use the SM83 call stack): −4 B per frame;
2. treat the kernel entry as a whole-program root and drop callee-saved spills/restores
   of registers whose caller values are dead (needs an ABI opt-out at the entry);
3. stack-frame re-layout: memory SSA over SP-relative slots + proof that no slot
   address escapes, then narrow each slot/array element to its proven width
   (k05/k06/k18 arrays) and pack the frame;
4. register-file allocation by SSA web instead of a fixed 4-byte slot per ARM register.

## B3 — physics precision (tests/test_physics_q88.py)
Jump parabola (gravity, ground bounce with 3/4 restitution, re-jump, friction) in
Q16.16 (`tests/physics/jump_q16.c`) vs the opt-in Q8.8 requantization (10 patches:
8 constants, 2 `asr #16 → #8`), profile-guided pruned (11 guards; 14 one-byte and 9
two-byte values) and run on PyBoy. Every frame 1..600, both axes (1200 samples):
**max screen-position error 0 px** (acceptance ≤ 1 px), no guard fired. Cost on a
sample of 24 calls: 366,829 → 226,720 M-cycles per call (−38%) vs the Phase 0 Q16.16
build. The error is 0 because every constant is a multiple of 1/256 and the only lossy
step (`vy >> 2` at bounces) never shifts a whole pixel; constants that are not
Q8.8-exact are rejected by the tool instead of silently rounded.

Late fix included in B3: dead phi nodes (e.g. a register merged at the function exit
with its incoming argument but never read) no longer join storage webs — this let the
physics loop registers become i16 and improved sound-mode cycles from −62% to −64%.

## Phase 1.5 — WRAM / HRAM gap (docs/phase1_5_report.md, 1000 seeds)
Totals over the 20 kernels (WRAM over 3 seeds; R0 matched Unicorn on every seed in
every configuration):

| config | WRAM touched | WRAM peak | HRAM reg bytes | M-cycles | code bytes |
|---|---|---|---|---|---|
| Phase 0 | 442 | 454 | 636 | 728,157 | 25,691 |
| Phase 1 (sound) | 418 | 430 | 633 | 265,396 | 18,263 |
| default ABI (items 1+3+4) | 366 (−17%) | 370 (−19%) | 593 (−7%) | 264,832 (−64%) | 17,873 (−30%) |
| entry ABI opt-in (items 1-4) | 198 (−55%) | 198 (−56%) | 567 (−11%) | 261,690 (−64%) | 16,522 (−36%) |

Per-item contribution (cumulative, totals):
* item 1, LR save elision: touched −52 B, peak −52 B, HRAM −40 B, code −390 B;
* item 3, frame padding trim: peak −8 B (k02, k18), touched 0 (padding is never written);
* item 4, HRAM allocation per web: 0 B with the default ABI (every candidate web's home
  slot is already referenced by the AAPCS push/pop, so moving it cannot free a slot);
  −11 B HRAM with the entry ABI (k05 −3, k18 −8), plus k02 −987 cycles; k18 +84 cycles;
* item 2, entry ABI (opt-in): touched −168 B, peak −172 B, HRAM −15 B, code −1,360 B.

**Target −50% WRAM vs Phase 0: met only with the opt-in entry ABI (−55% touched,
−56% peak). Not met with the default ABI (−17% / −19%).**

Remaining limits:
* with AAPCS, callee-saved spills (r4-r11 pushed at entry) are the bulk of the remaining
  WRAM; they are required by the ABI unless the caller accepts the entry ABI;
* item 3 only removes unreachable padding; arrays are not narrowed (k05 stores full
  32-bit values and walks its array with a pointer that escapes the interval analysis;
  k06 already uses bytes; k18 aliases a volatile buffer). A 50-seed Unicorn trace shows
  no dead stack stores in any kernel;
* item 4 allocates whole 4-byte slots and pins every web of non-entry functions and
  every ABI-visible value; the "keep only if not worse" check makes it a heuristic;
* WRAM is measured over 3 seeds (pattern fill); HRAM is a static count of referenced
  bytes and always includes the argument slots R0-R3 and SP.
