# Memory map (Phase 2)

## GB WRAM ($C000-$DFFF, 8 KiB, DMG)
| range | use |
|---|---|
| `$C000-$CFFF` | emulated ARM memory window: every RAM access of the ARM code goes to `$C000 \| (addr & $0FFF)` |
| `$D000-$D09F` | shadow OAM (40 x 4 bytes, page-aligned: OAM DMA source page `$D0`) |
| `$D100-$D1FF` | HAL: GBA OAM mirror (32 objects x 8 bytes) |
| `$D200-$D2FF` | HAL state (input byte, latched scroll, flags, counters) |
| `$D300-$DFFF` | native SM83 stack (initial SP `$E000`, grows downward) |

Before Phase 2 the ARM window was `$C000 | (addr & $1FFF)` (all of WRAM) with the
native stack starting at `$D000`, i.e. inside the window; a shadow OAM could not be
placed safely. The window is now 4 KiB and nothing else lives in it.

ARM side: `.data`/`.bss` are linked at `0x03000000` (IWRAM) and land at `$C000`
upward; the initial ARM SP is `0x03000F00` (`$CF00`), growing down towards the
globals. Addresses alias modulo 4 KiB (EWRAM `0x02xxxxxx` aliases IWRAM), so programs
must keep data + stack under 4 KiB and use IWRAM only.

## Other ARM regions (resolved at compile time, tools/hal/intercept.py)
| ARM range | GB side |
|---|---|
| `0x04000000-0x040003FF` I/O | shim calls (constant addresses only) |
| `0x07000000-0x070003FF` OAM | GBA OAM mirror + spatial OAM shim (constant addresses only) |
| `0x06000000-0x06017FFF` VRAM | 4bpp -> 2bpp converter shim into GB VRAM `$8000-$97FF` / map `$9800` |
| `0x05000000-0x050003FF` palette | luminance shim (4 levels) |
| `0x08000000-...` ROM (loads) | copy of the ARM image in GB ROM0 |

## HRAM
`$FF80-$FFD5`: register file (docs/hram_map.md); `$FFE0-$FFEB`: OAM DMA routine
(copied from ROM at start-up).
