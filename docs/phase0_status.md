# Phase 0 — status

**Result: 20/20 kernels passing**, 1000 seeds per kernel (4 fixed edge cases + 996
deterministic random seeds per kernel), R0 compared bit for bit (Unicorn × PyBoy, HRAM
`$FF80-$FF83`). Full run: ~7 s (`.venv/bin/python -m pytest tests/`).
`LOCKSTEP_SEEDS=N` reduces the number of seeds.

## Measured cost (SM83 M-cycles per call, average over 1000 seeds)
Measured with the runtime timer (4 M-cycle resolution; includes ISR overhead).
See `build/cycles.csv` after running the test.

| kernel | M-cycles | kernel | M-cycles |
|---|---|---|---|
| k01_fibonacci | 13452 | k11_shifts_var | 4705 |
| k02_crc16 | 163467 | k12_clamp_sat | 7155 |
| k03_enemy_fsm | 73439 | k13_abs_minmax | 2281 |
| k04_aabb | 2646 | k14_isqrt | 13336 |
| k05_sort | 28253 | k15_bitrev | 31231 |
| k06_bubble_u8 | 20834 | k16_carry64 | 1844 |
| k07_popcount | 10249 | k17_calls | 8748 |
| k08_gcd | 18484 | k18_bytes_half | 11409 |
| k09_mul_acc | 7618 | k19_tilemap_hash | 248660 |
| k10_xorshift | 15880 | k20_fixed_point | 43757 |

Overall average ≈ 36,400 M-cycles (≈ 2.1 frames of 17,556 M-cycles).

## Known limitations
- Every `BX` and `POP {..,PC}` is treated as a return (SM83 `ret`); no indirect jumps,
  ARM interworking, `MOV PC` or jump tables (kernels are built with `-fno-jump-tables`).
- ARM memory is mapped onto an 8 KiB WRAM window (`$C000 | addr&$1FFF`); stack/locals only.
  No globals/.data/.rodata other than literal pools (resolved at translation time).
  Unaligned accesses and crossing the 8 KiB window are not handled.
- No division/libgcc (`__aeabi_*`), no SWI, no 32-bit ARM mode.
- The C flag after `MULS` is not modeled (unpredictable on ARMv4; N/Z only).
- Shifts and MUL use iterative routines (slow: MUL ~32 iterations); every 32-bit op
  is inline byte by byte — no register allocation or width pruning (planned for Phase 2).
- The test compares only R0; flags and other registers are not checked.
