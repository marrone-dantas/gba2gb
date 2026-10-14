# Phase 5 A4: candidate open-source GBA games for the first full vertical slice

Criteria: the license must allow redistributing a derivative (transpiled) ROM,
the source must be C (mostly Thumb), the game should use tile modes 0/1, and it
should be small. A heavy sound engine (maxmod) and C++ (butano) count against a
candidate. Every URL below was verified on 2026-10-14 by cloning the repository
(commit and date are listed). The clones are kept outside the repo in
`/workspace/private/candidates/`, and nothing from them is committed here. Line
counts cover all .c/.h/.cpp/.s files in the repository, including data arrays.

| # | Game | URL (commit) | License | Size | Language / toolchain | Video | BIOS / ARM / IWRAM | Sound | Feasibility | Main blockers |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Snek GBA** (snake) | https://github.com/blueOkiris/Snek-GBA (b7c8751, 2020-12-15) | GPL-3.0 | ~970 lines, 3 C files | C, bare registers (own `gba.h`), devkitARM `gba.specs` crt0, `-mthumb -O2` | mode 0, BG0+BG1, OBJ 1D | none: no `swi`, no ARM code, no IWRAM sections, no IRQ (timer 1 polled for the seed) | none | **High** | `float` positions (soft-float libgcc helpers must be lifted: `__aeabi_fadd/fmul/f2iz`); newlib `rand`/`srand`; `%` → `__aeabi_idivmod`; timer 1 read (TM1CNT/TM1D shim) |
| 2 | **Flappy Bird GBA** | https://github.com/tullrich/flappybird-gba (3cb9ae0, 2017-11-02) | MIT (text in LICENSE.txt) | 880 lines of C in src/ (1,817 with headers), 53.6 KB prebuilt ROM | C, own register headers, CMake + grit assets, `.s` syscall stubs | mode 0 tiled BGs, OBJ + **affine OBJ** (bird rotation) | `VBlankIntrWait` (`swi`), ARM `IN_IWRAM` IRQ handler (replaced by the HAL ISR), DMA3 copies, cascaded timers | DirectSound A/B with a 4-channel software mixer in the main loop, DMA1 FIFO + PSG square for SFX | **Medium-high** | DMA3 (`dma3_copy/fill`) shim needed; software mixer is CPU-heavy (stub, or pre-render through the Phase 4.3 DirectSound path); timer IRQs; affine OBJ goes through the Phase 4.1 LUT; `rand` |
| 3 | **gbatris** (Tetris) | https://github.com/jtsiomb/gbatris (fc9e934, 2019-02-27) | GPL-3.0 | ~1,900 lines of C (4,267 total) | C, no libraries ("just the C compiler"), own `gbaregs.h`, `-mthumb -O1` | game in mode 0 (BG0); name/score screens in **mode 3** bitmap | ARM-mode IRQ handler (`target("arm")`), debug `swi 0xff0000`; SRAM high-score table (`sramcpy`) | DirectSound music via DMA1 FIFO_A + timers | **Medium** | mode 3 UI screens (no bitmap support: redraw as tiles or skip them); ARM ISR; DMA sound music; `malloc`/`sprintf`/`printf` from newlib; SRAM save (0x0E000000 → MBC5 SRAM, alongside A2) |
| 4 | **Where is the ball?** (GBA Jam 2021) | https://github.com/johedan20012/WhereIsTheBall (0e24e78, 2021-07-21) | MIT | ~1,600 lines | **C++** (classes, `new`, singletons) + libtonc | mode 0, BG0-BG3 + OBJ | `VBlankIntrWait`, libtonc `irqInit`; SRAM save | none | Medium | C++ runtime (operator new → malloc, vtables / indirect calls, static constructors); libtonc must be lifted along (ARM parts of libtonc such as the IRQ dispatcher in IWRAM) |
| 5 | **Quantum Survival** (GBA Jam 2021) | https://github.com/LarkSkwared/Quantum-Survival (624add1, 2021-09-12) | GPL-3.0 (asset licenses in licenses/) | 363 lines of game C + 2.5 MB repo of converted assets | C + libtonc | mode 0 BG0 + OBJ in game; **mode 3** title/end screens | none found | none | Medium | mode 3 screens; large bitmap assets; `printf` (libtonc tte?); very simple gameplay (less useful as a slice) |
| 6 | Pong-Homebrew-GBA | https://github.com/ZeroDayArcade/Pong-Homebrew-GBA (c784b60, 2023-10-25) | MIT | 985 lines, 1 C file, 8.9 KB ROM | C + libgba | **mode 3** bitmap only | `VBlankIntrWait`, libgba `irqInit` | none | Low for our pipeline | Bitmap mode 3 for everything; would need a framebuffer → tile conversion layer |

Rejected after inspection:

* **Celeste Classic GBA** (https://github.com/JeffRuLz/Celeste-Classic-GBA, 6d4051f). It is technically attractive (C, mode 0, about 5.7k lines), but the repository has **no license file**, and the original PICO-8 game is not openly licensed, so we cannot redistribute a derivative ROM. It also uses maxmod (`mmInit`/`mmStart`) and `float`.
* **dcpr** (https://github.com/MilanFIN/dcpr, MIT): raycaster in **mode 4** with ARM/IWRAM code. Wrong rendering model.
* **tambler-gba** (https://github.com/pomettini/tambler-gba, MIT): **mode 4** bitmap.
* **gba-cascade7** (https://github.com/mick-schroeder/gba-cascade7, MIT): butano (C++) + maxmod.
* **World of Zoink** (https://github.com/colonelsalt/zoink): C++ with maxmod, and the assets are stripped from the repository.

## Recommendation

1. **Snek GBA**. This is the smallest real game that fits the pipeline as-is:
   pure Thumb C, mode 0 tiles + OBJ, no BIOS calls, no ARM code, no interrupts,
   no sound. The new work it needs is generic and reusable: lifting the libgcc
   soft-float and division helpers (Thumb) and newlib `rand`, plus a TM1 read shim.
   GPL-3.0 allows distributing the transpiled ROM, provided we ship the source
   (ours and the original) with it.
2. **Flappy Bird GBA**. MIT-licensed, C, mode 0 with an affine OBJ (it exercises
   the Phase 4.1 LUT path), and a complete game loop with title, score and
   collision. The blockers are the subsystems we already partly have: the ARM IRQ
   handler is replaced by the HAL ISR, `VBlankIntrWait` is already supported, and
   the DirectSound output is covered by Phase 4.3 in principle. The new work is a
   DMA3 shim, timer interrupts, and a decision on the main-loop software mixer
   (stub it for the first slice).

gbatris is the natural third. Its core game is a mode 0 tile game with no
libraries, but its mode 3 menu screens and ARM ISR make it a worse first target.
