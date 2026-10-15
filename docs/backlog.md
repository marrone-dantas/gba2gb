
## Commercial dump front-end (deferred)

Deferred until the source-based engine is finished.

Pipeline for a `.gba` dump without source:

1. SHA-1 of the dump matched against public decompilations (pret, SAT-R/sa2,
   metroidret/mzm). On a match, build the decomp C and use the source path.
2. Otherwise: Ghidra headless + GhidraGBA loader (functions, CFG, jump tables,
   Function ID signatures generated from the decomp SDK libraries), mGBA headless Lua
   tracing (PC trace, value ranges, VRAM/OAM captures), gbadisasm cross-check, and
   LZ77/Huffman asset extraction -> IR -> gba2gb -> `.gb`, lockstep-validated against
   the traces.

Ghidra pseudo-C is not used as compilable source.
