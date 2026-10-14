# gba2gb-aot

Assisted pipeline for porting GBA games to the Game Boy (DMG/GBC, MBC5).

## Phases
1. Lifting + profiling (Ghidra/angr, mGBA Lua) — `tools/lift`, `tools/profile`
2. Bit-width pruning (SSA + Z3) — `tools/prune`
3. 2bpp tile codebook (k-means/VQ) — `tools/vq`
4. SM83 backend (RGBDS) — `tools/backend`
5. MBC5 base runtime, PPU/OAM/APU shims — `runtime`
6. Build, link and cycle audit (SameBoy) — `tests`

Each phase has an acceptance criterion and one commit per deliverable.

## Phase 0 (headless Thumb -> SM83 AOT core)
```sh
./scripts/setup.sh                       # toolchain
.venv/bin/python -m pytest tests/        # 20 kernels x 1000 seeds, lockstep Unicorn x PyBoy
.venv/bin/python -m tools.backend build/kernels/k01_fibonacci.elf -o fib.gbc
```
See `docs/hram_map.md` and `docs/phase0_status.md`.
