#ifndef COMPAT_GBA_VIDEO_H
#define COMPAT_GBA_VIDEO_H
#include "gba_types.h"
#define RGB5(r,g,b) ((r)|((g)<<5)|((b)<<10))
#define RGB8(r,g,b) ((((b)>>3)<<10)|(((g)>>3)<<5)|((r)>>3))
#define BG_PALETTE ((u16*)0x05000000)
#define SPRITE_PALETTE ((u16*)0x05000200)
#define VRAM 0x06000000
#define TILE_BASE_ADR(n) ((void*)(VRAM + ((n) << 14)))
#define MAP_BASE_ADR(n) ((u16*)(VRAM + ((n) << 11)))
#define SPRITE_GFX ((u16*)0x06010000)
#define REG_DISPCNT (*(vu16*)0x04000000)
#define REG_BG0CNT (*(vu16*)0x04000008)
#define REG_BG1CNT (*(vu16*)0x0400000A)
#define REG_BG2CNT (*(vu16*)0x0400000C)
#define REG_BG3CNT (*(vu16*)0x0400000E)
#define REG_BG0HOFS (*(vu16*)0x04000010)
#define REG_BG0VOFS (*(vu16*)0x04000012)
#define REG_BG1HOFS (*(vu16*)0x04000014)
#define REG_BG1VOFS (*(vu16*)0x04000016)
#define REG_BG2HOFS (*(vu16*)0x04000018)
#define REG_BG2VOFS (*(vu16*)0x0400001A)
#define REG_BG3HOFS (*(vu16*)0x0400001C)
#define REG_BG3VOFS (*(vu16*)0x0400001E)
#define TILE_BASE(n) ((n) << 2)
#define MAP_BASE(n) ((n) << 8)
#define BG_16_COLOR 0
#define BG_SIZE_0 0
#define BG_PRIORITY(n) (n)
#define MODE_0 0
#define BG0_ON (1<<8)
#define BG1_ON (1<<9)
#define BG2_ON (1<<10)
#define BG3_ON (1<<11)
#define BG_ALL_ON (0xF<<8)
#define OBJ_ON (1<<12)
#define OBJ_ENABLE OBJ_ON
#define OBJ_1D_MAP (1<<6)
#define SetMode(m) (REG_DISPCNT = (m))
#endif
