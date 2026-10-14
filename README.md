# gba2gb-aot

Pipeline assistido para portar jogos de GBA para Game Boy (DMG/GBC, MBC5).

## Fases
1. Lifting + perfil (Ghidra/angr, mGBA Lua) — `tools/lift`, `tools/profile`
2. Poda de largura de bits (SSA + Z3) — `tools/prune`
3. Codebook de tiles 2bpp (k-means/VQ) — `tools/vq`
4. Backend SM83 (RGBDS) — `tools/backend`
5. Runtime base MBC5, shims PPU/OAM/APU — `runtime`
6. Build, link e auditoria de ciclos (SameBoy) — `tests`

Cada fase tem critério de aceite e um commit em português.
