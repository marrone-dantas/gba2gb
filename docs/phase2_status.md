# Phase 2 status
Done: 2.1 interceptor, 2.2 shims, 2.3 spatial OAM, 2.4 demos (all rewritten, see
tests/demos/README.md), 2.5 tests. Details and limits: docs/hal.md.

Lockstep (tests/test_oam_lockstep.py, 300 frames, same inputs, PyBoy DMG):
| demo | frames exact | VRAM/OAM writes outside VBlank/HBlank | max sprites/line | vblanks/vsyncs |
|---|---|---|---|---|
| obj_demo | 300/300 | 0 | 10 | 300/300 |
| key_demo | 300/300 | 0 | 6 | 300/300 |
| brin_demo | 300/300 | 0 | 0 | 300/300 |
| oam_stress | 300/300 | 0 | 12 (dropped in 146 frames) | 680/300 |

Screenshots (GBA reference | GB DMG): docs/img/*.png.
