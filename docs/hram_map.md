# HRAM map (Phase 0)

The generated SM83 code keeps the ARM7 (Thumb mode) CPU state in HRAM, accessible with
`ldh` (fast, 3 M-cycles) and also via `[hl]` with `h=$FF`.

| Address         | Contents                                   |
|-----------------|--------------------------------------------|
| `$FF80-$FFBF`   | R0..R15, 4 bytes each, little-endian (Rn at `$FF80+4n`) |
| `$FFC0`         | N flag (0/1)                               |
| `$FFC1`         | Z flag (0/1)                               |
| `$FFC2`         | C flag (0/1) — ARM semantics (C=1 = no borrow on subtraction) |
| `$FFC3`         | V flag (0/1)                               |
| `$FFC4-$FFC7`   | T0: 32-bit temporary/result                |
| `$FFC8-$FFCB`   | T1: temporary (immediates, addresses)      |
| `$FFCC-$FFCF`   | T2: temporary (multiplication)             |
| `$FFD0`         | START: harness writes 1 to run             |
| `$FFD1`         | DONE: runtime writes 1 when finished (end marker) |
| `$FFD2-$FFD3`   | timer overflow counter (cycle measurement) |
| `$FFD4`         | TIMA sampled at the end                    |
| `$FFD5`         | GUARD: id of a failed range guard (then DONE = 2) |

R15 (PC) is not materialized: control flow is translated statically.
R14 (LR) receives the ARM return address on `BL`, but the actual return uses the SM83
stack (`call`/`ret`).

## ARM memory
Every LDR/STR/PUSH/POP access is mapped to WRAM: `$C000 | (addr & $1FFF)`.
In Phase 0 only the stack (initial SP `0x03001F00` → `$DF00`) is used by the kernels.
The native SM83 stack starts at `$D000`.

## Cycle measurement
Timer at 262144 Hz (TAC=5, 1 tick = 4 M-cycles); the ISR counts TIMA overflows.
Cost ≈ (TCNT·256 + TIMA)·4 M-cycles.

## Phase 1.5 item 4: slot allocation per value group (`hram_alloc`, default on)
With pruning enabled, the R0-R12 slots are no longer tied to one ARM register for the
whole program: `tools/prune/regalloc.py` assigns each web (SSA values of one register
joined by phi/pi) a 4-byte slot from liveness-based interference, and renames the IR
accordingly. Webs fixed by the ABI or by multi-register instructions stay in their
home slot (arguments, values live at returns, push/pop/ldm/stm/bl operands, SP, LR,
PC, every web of a non-entry function), so the slots seen by callers are unchanged:
R0 = result, R0-R3 = arguments, and under AAPCS R4-R11 are preserved. The coloring
minimises new referenced bytes (byte width from the storage class), and the backend
keeps the allocation only if it does not increase the referenced HRAM bytes.
