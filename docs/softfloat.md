# Native soft-float and integer helpers (Phase 5 B2)

Thumb code built with GCC calls libgcc for `float`/`double` arithmetic, for
32-bit division and for 64-bit multiplication. On the GBA these helpers are ARM
code (reached through `____X_from_thumb` veneers) or Thumb code. The lifter
(`tools/lift/lift.py`, `NATIVES`) does not translate them. A `bl` to one of them
becomes `call NAT_<name>`, a hand-written SM83 routine in
`runtime/gb_softfloat.asm`. That routine is linked into every ROM, in both kernel
and HAL mode.

| AEABI helper | native | notes |
|---|---|---|
| `__aeabi_dadd/dsub/dmul` | `NAT_dadd/dsub/dmul` | binary64, RNE, subnormals |
| `__aeabi_fadd/fsub/fmul` | `NAT_fadd/fsub/fmul` | binary32 |
| `__aeabi_i2d/i2f/f2d/d2f` | conversions | |
| `__aeabi_f2iz` | truncation | saturating, NaN → 0 |
| `__aeabi_fcmpeq/lt/gt` | 0/1 in r0 | NaN unordered → 0, ±0 equal |
| `__aeabi_idiv/idivmod` | restoring division | r0 = q, r1 = r; /0 like libgcc |
| `__aeabi_lmul` | 64×64 → low 64 | quarter-square 8×8 table |

**Calling convention.** Arguments are in R0-R3 (HRAM $FF80+), with doubles as
R0:R1 and R2:R3. The result goes to R0 (R0:R1 for 64-bit results). R4-R11, SP
and LR are preserved. Scratch memory is WRAM $D300-$D343 (`sf_state`). 8×8
products use a 1 KiB quarter-square table in ROMX bank 1.

**NaNs.** The routines reproduce what libgcc's `ieee754-df.S`/`ieee754-sf.S`
actually do, as observed in lockstep:
- A NaN operand is returned quieted. The first operand wins.
- inf − inf returns the default NaN with the first operand's sign.
- inf + NaN returns the default NaN.
- 0 × inf returns the infinity operand, quieted.
- `d2f(NaN)` returns +default NaN.
- `f2d(NaN)` keeps the payload.

**Validation.** `tests/test_softfloat.py` runs each helper behind its own
Thumb kernel (`tests/softfloat/s_*.c`, linked with the real libgcc) on Unicorn
and on PyBoy, and compares R0 and R1 bit for bit. Inputs are all pairs of about
18 edge values plus 300 random cases per op (`SOFTFLOAT_SEEDS`; also verified
with 5000). Worst-case cost over the test inputs, in T-cycles:
- dmul ≈ 8.7k
- dadd ≈ 5.5k
- fadd ≈ 4.6k
- idiv ≈ 5.7k
- lmul ≈ 5.7k
- fcmp ≈ 0.6k

The figures are in `build/softfloat/cycles.csv`.

## Timers (runtime/gb_timer_shims.asm)

The HAL now emulates TM0/TM1:
- Writing `TMxCNT_L` sets the reload value.
- Writing `TMxCNT_H` starts the timer on the enable edge and freezes it on stop.
- Reading `TMxCNT_L` returns the current value.

The clock is the GB TIMA at 4096 Hz, extended in the VBlank ISR. DIV bits 0-1
supply the 16384 Hz sub-phase, so the resolution is 1/16384 s (16 ticks of a
262144 Hz timer).

Limits:
- Overflow reload is exact only for reload 0.
- No cascade and no timer IRQs.
- The clock drifts while a DirectSound stream (which reprograms TIMA) plays.

Covered by `tests/test_timer.py` (`tests/demos/timer_demo.c`).
