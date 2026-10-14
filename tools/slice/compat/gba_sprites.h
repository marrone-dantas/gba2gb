#ifndef COMPAT_GBA_SPRITES_H
#define COMPAT_GBA_SPRITES_H
#include "gba_types.h"
typedef struct { u16 attr0, attr1, attr2, dummy; } ALIGN(4) OBJATTR;
#define OAM ((OBJATTR*)0x07000000)
#define OBJ_Y(m) ((m) & 0x00ff)
#define OBJ_X(m) ((m) & 0x01ff)
#define OBJ_CHAR(m) ((m) & 0x03ff)
#define OBJ_PRIORITY(m) (((m) & 3) << 10)
#define ATTR2_PALETTE(n) ((n) << 12)
#define ATTR0_COLOR_16 0
#define ATTR0_SQUARE 0
#define OBJ_SQUARE 0
#define ATTR1_SIZE_8 0
#define ATTR1_FLIP_X (1<<12)
#define ATTR1_FLIP_Y (1<<13)
#define OBJ_DISABLE (1<<9)
#endif
