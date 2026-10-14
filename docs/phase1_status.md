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
