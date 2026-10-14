# Bit-width pruning (Phase 1 B1)

`tools/prune/bitwidth_pruning.py` turns range-analysis results into a storage plan for
the backend.

```sh
.venv/bin/python -m tools.prune.bitwidth_pruning k.elf                      # sound (default)
.venv/bin/python -m tools.prune.bitwidth_pruning k.elf --profile-guided build/profiles/k.json
.venv/bin/python -m tools.prune.bitwidth_pruning jump_q16.elf --requant-q88 jump_q88.elf
```

## Modes
| mode | source of ranges | safety |
|---|---|---|
| `sound` (default) | proven (static) ranges | always exact |
| `profile` (opt-in) | observed ranges for instruction values whose observed class is narrower than the proven one; the analysis is re-run with these assumptions | every assumed value is computed at full width and **guarded**; a violation jumps to `GuardTrap` (`HR_DONE=2`, guard id in `HR_GUARD=$FFD5`) |

Storage classes: `u8`/`i8` → 1 byte, `u16`/`i16` → 2 bytes, otherwise 4. Values tied by
phi/pi nodes (a *web*) share a register slot and therefore one width (join of their
ranges). Parameters, SP/LR, `pop`/`ldm` results and call results are always 4 bytes.
Bytes above the storage width are undefined in the slot and are re-materialized by
consumers that need them (`ret`, `bl` arguments, `push`, word stores, 32-bit ops).

## Dead-extension elimination / extension fusion
`lsls rX, rY, #24|#16` + `lsrs|asrs rX, rX, #same` is fused into a single
`uxtb/sxtb/uxth/sxth` of rY when the LSL result has no other reader and no flag reader
sits in between (the LSL is deleted). If rY is already proven inside the extension
range the pair is *dead* and becomes a plain copy. GCC -O2 rarely leaves provably dead
pairs (0 in the 20 kernels; covered by a unit test); fusion fires in k03, k12, k18, k20.

## Q16.16 → Q8.8 requantization (opt-in, CHANGES SEMANTICS)
Heuristic: every `asr #16` whose operand is not an `lsl #16` is a fixed-point →
integer conversion. The fixed-point *web* is the set of SSA values connected to those
operands through `add/sub/mov/cmp/cmn`, phi/pi nodes and `asr #k` (k ≠ 16). The patch:
- constants of the web (literal-pool words and `movs #imm; lsls #k` pairs) are divided
  by 256 (must be exact; otherwise the tool refuses),
- the `asr #16` sites become `asr #8`.
The output is a new ELF that can be run on Unicorn and translated like any kernel.
Precision is NOT preserved in general (fractional bits are lost, the range shrinks to
±128 integer units in i16); it must be validated per use case — see
`tests/test_physics_q88.py` (acceptance: ≤ 1 px over 600 frames).
