# SM83 peephole optimizer (Phase 5 A3)

`tools/backend/peephole.py` rewrites the generated kernel assembly (not the
hand-written runtime / HAL shims) before it is assembled. It is on by default in
`build()`; `GBA2GB_PEEPHOLE=0` or `build(..., peephole=False)` disables it. Passes,
iterated to a fixpoint:

1. **Redundant loads/stores** (A / HRAM value tracking in straight-line code; reset
   at labels, calls, returns, any jump): drop `ld a, n` if A = n, `ldh a, [X]` if
   A = [X], `ldh [X], a` if [X] = A. Only HRAM $FF80-$FFFE is tracked (I/O registers
   are never removed); any other memory write forgets all HRAM knowledge.
2. **×2 with `add a, a`**: the narrowed 8-bit `lsl #k` (`ldh [T], a` + k×`ld hl, T /
   sla [hl]` + `ldh a, [T]`, 7k+6 M) becomes k×`add a, a` + `ldh [T], a` (k+3 M);
   Z/N/C are identical, H is never read. `ld hl, T` is kept if hl is live.
3. **LDI/LDD fusion**: `ld [hl], a` / `ld a, [hl]` + `inc hl` / `dec hl` → `[hl+]` / `[hl-]`.
4. **Jump threading**: jumps to a `jp L2` go to L2; `jp L` before `L:` removed;
   `jp cc, L1 / jp L2 / L1:` → `jp !cc, L2`.
5. `ld a, 0` → `xor a` when the flags are provably dead.

Measured with `python -m tools.backend.peephole_bench --seeds 100` (kernels:
average M-cycles per run with the runtime timer and the same seeds as the
lockstep test, R0 checked against the ARM reference in both builds; demos:
average M-cycles of game code per frame over 120 frames, see the module
docstring; bytes = size of the generated "kernel" section).

**Summary.** 20 kernels, sound backend: −2.3 % M-cycles in total (geometric mean
−3.0 %), −5.3 % code. Phase 0 backend: −0.9 % (geo −1.2 %), −4.2 % code. 9 demos:
−2.0 % active M-cycles per frame, −5.3 % code. All lockstep tests stay green with
the pass on (it is the default in the test suite). Most of the gain comes from
pass 1 (and pass 5 for size). Pass 3 never fires, because codegen already emits `[hl+]`.
Pass 4 fires once per program. The ×2 rewrite only matches 8-bit narrowed shifts.
Larger wins would need register allocation of A/HL across ARM instructions in the
backend itself, not more peephole rules.

| kernel | mode | M-cycles base | M-cycles peephole | Δ % | bytes base | bytes peephole | Δ % | R0 ok |
|---|---|---|---|---|---|---|---|---|
| k01_fibonacci | phase0 | 13851 | 13702 | -1.1 | 545 | 511 | -6.2 | yes |
| k01_fibonacci | sound | 4982 | 4822 | -3.2 | 318 | 284 | -10.7 | yes |
| k02_crc16 | phase0 | 163391 | 161531 | -1.1 | 1829 | 1740 | -4.9 | yes |
| k02_crc16 | sound | 41110 | 38874 | -5.4 | 944 | 860 | -8.9 | yes |
| k03_enemy_fsm | phase0 | 75181 | 74220 | -1.3 | 4623 | 4397 | -4.9 | yes |
| k03_enemy_fsm | sound | 24115 | 23209 | -3.8 | 2585 | 2425 | -6.2 | yes |
| k04_aabb | phase0 | 2699 | 2534 | -6.1 | 2110 | 2037 | -3.5 | yes |
| k04_aabb | sound | 857 | 822 | -4.0 | 1049 | 1016 | -3.1 | yes |
| k05_sort | phase0 | 27821 | 27203 | -2.2 | 2382 | 2251 | -5.5 | yes |
| k05_sort | sound | 12401 | 11852 | -4.4 | 1453 | 1353 | -6.9 | yes |
| k06_bubble_u8 | phase0 | 20767 | 20335 | -2.1 | 993 | 935 | -5.8 | yes |
| k06_bubble_u8 | sound | 11154 | 10658 | -4.4 | 708 | 652 | -7.9 | yes |
| k07_popcount | phase0 | 10180 | 9892 | -2.8 | 474 | 442 | -6.8 | yes |
| k07_popcount | sound | 3899 | 3556 | -8.8 | 293 | 257 | -12.3 | yes |
| k08_gcd | phase0 | 22621 | 22606 | -0.1 | 723 | 710 | -1.8 | yes |
| k08_gcd | sound | 9957 | 9799 | -1.6 | 761 | 742 | -2.5 | yes |
| k09_mul_acc | phase0 | 7595 | 7590 | -0.1 | 286 | 283 | -1.0 | yes |
| k09_mul_acc | sound | 7231 | 7227 | -0.1 | 215 | 212 | -1.4 | yes |
| k10_xorshift | phase0 | 15880 | 15772 | -0.7 | 520 | 497 | -4.4 | yes |
| k10_xorshift | sound | 4451 | 4391 | -1.3 | 403 | 395 | -2.0 | yes |
| k11_shifts_var | phase0 | 4773 | 4749 | -0.5 | 845 | 823 | -2.6 | yes |
| k11_shifts_var | sound | 2168 | 2149 | -0.9 | 550 | 532 | -3.3 | yes |
| k12_clamp_sat | phase0 | 7159 | 7098 | -0.8 | 1138 | 1099 | -3.4 | yes |
| k12_clamp_sat | sound | 881 | 856 | -2.9 | 539 | 513 | -4.8 | yes |
| k13_abs_minmax | phase0 | 2287 | 2268 | -0.8 | 691 | 673 | -2.6 | yes |
| k13_abs_minmax | sound | 706 | 681 | -3.6 | 461 | 439 | -4.8 | yes |
| k14_isqrt | phase0 | 13259 | 13238 | -0.2 | 634 | 614 | -3.2 | yes |
| k14_isqrt | sound | 5586 | 5469 | -2.1 | 628 | 600 | -4.5 | yes |
| k15_bitrev | phase0 | 31231 | 30816 | -1.3 | 699 | 655 | -6.3 | yes |
| k15_bitrev | sound | 8709 | 8556 | -1.8 | 349 | 322 | -7.7 | yes |
| k16_carry64 | phase0 | 1844 | 1822 | -1.2 | 815 | 797 | -2.2 | yes |
| k16_carry64 | sound | 708 | 689 | -2.7 | 482 | 464 | -3.7 | yes |
| k17_calls | phase0 | 8756 | 8728 | -0.3 | 1151 | 1124 | -2.3 | yes |
| k17_calls | sound | 3396 | 3370 | -0.8 | 818 | 793 | -3.1 | yes |
| k18_bytes_half | phase0 | 11409 | 11351 | -0.5 | 1979 | 1922 | -2.9 | yes |
| k18_bytes_half | sound | 1744 | 1677 | -3.8 | 1184 | 1129 | -4.6 | yes |
| k19_tilemap_hash | phase0 | 248461 | 247496 | -0.4 | 1284 | 1218 | -5.1 | yes |
| k19_tilemap_hash | sound | 106877 | 106537 | -0.3 | 1364 | 1331 | -2.4 | yes |
| k20_fixed_point | phase0 | 43787 | 43472 | -0.7 | 1970 | 1883 | -4.4 | yes |
| k20_fixed_point | sound | 12710 | 12263 | -3.5 | 1418 | 1329 | -6.3 | yes |

| demo | active M/frame base | peephole | Δ % | bytes base | bytes peephole | Δ % | rewrites (values/x2/fuse/jumps/xor) |
|---|---|---|---|---|---|---|---|
| obj_demo | 6116 | 5932 | -3.0 | 5898 | 5637 | -4.4 | 102/0/0/1/54 |
| key_demo | 17599 | 17596 | -0.0 | 7786 | 7303 | -6.2 | 205/0/0/1/70 |
| brin_demo | 1089 | 1070 | -1.7 | 1839 | 1739 | -5.4 | 41/0/0/1/15 |
| oam_stress | 8033 | 7816 | -2.7 | 6369 | 6108 | -4.1 | 95/0/0/1/68 |
| input_test | 4318 | 4194 | -2.9 | 3863 | 3693 | -4.4 | 64/0/0/1/39 |
| affine_demo | 5133 | 4981 | -3.0 | 4021 | 3787 | -5.8 | 95/0/0/1/41 |
| sound_demo | 1094 | 1022 | -6.5 | 4324 | 4009 | -7.3 | 124/3/0/1/46 |
| spill_demo | 6652 | 6447 | -3.1 | 5333 | 5054 | -5.2 | 102/3/0/1/56 |
| ewram_demo | 2569 | 2491 | -3.0 | 5528 | 5234 | -5.3 | 115/4/0/1/41 |
