# Range profile format (`gba2gb-range-profile/1`)

Produced by `tools/profile/range_tracer.py` (Unicorn, authoritative) and, best-effort and
untested, by `tools/profile/mgba_range_tracer.lua`. One JSON file per kernel:
`build/profiles/<kernel>.json`.

```sh
.venv/bin/python -m tools.profile.range_tracer --all          # 20 kernels x 1000 seeds
.venv/bin/python -m tools.profile.range_tracer k.elf -n 100 -o out.json
```
Seeds are the same as the lockstep test (`tools/profile/seeds.py`).

```json
{
 "format": "gba2gb-range-profile/1",
 "kernel": "k01_fibonacci",
 "elf": "build/kernels/k01_fibonacci.elf",
 "entry": "0x8000000",
 "seeds": 1000,
 "regs": { "0x08000004:r3": { ...stat... } },
 "mem":  { "0x03001ef0":    { ...stat..., "sizes": [4] } }
}
```

## Keys
- `regs`: `"<pc>:r<n>"` — the value of register `rn` **right after** the instruction at
  `pc` executed (one entry per destination register; `pop`/`ldm` produce several; for `bl`
  only `lr` is recorded, since the callee runs next). PC (r15) is not recorded.
  These keys map 1:1 to non-phi SSA values in `tools/prune/range_analysis.py`.
- `mem`: start address of each data access (reads and writes, any size). Literal-pool
  reads from `.text` are skipped. A multi-byte access is recorded once under its start
  address with the zero-extended value of that size; `sizes` lists the access sizes seen.

## Stat object
| field        | meaning |
|--------------|---------|
| `count`      | number of observations |
| `umin/umax`  | min/max as unsigned |
| `smin/smax`  | min/max as signed two's complement (of the access size; 32 bits for registers) |
| `bitmask_or` | OR of every observed value (bits that were ever 1) |
| `stride`     | gcd of all deltas between observed values; every value ≡ `umin` (mod `stride`). 0 = constant |

Dynamic ranges are **hints** (only cover the executed seeds); static ranges from
`tools/prune` are the sound ones.
