/* input_test (test program): copies REG_KEYINPUT to a global every frame and shows
   one 8x8 sprite per pressed key (index = key bit). */
#include "gba.h"
#include "assets.h"

volatile u32 keys_seen;

#define KEY_OBJ(n) do { OAM_ATTR0(n) = (k & (1u << (n))) ? 64 : ATTR0_HIDE; \
                        OAM_ATTR1(n) = 24 + 16 * (n); OAM_ATTR2(n) = 35; } while (0)

int main(void)
{
    int i;
    for (i = 0; i < 16; i++)
        PAL_OBJ[i] = key_pal[i];
    for (i = 0; i < KEY_TILE_WORDS; i++)
        OBJ_TILES32[32 * 8 + i] = key_tiles[i];
    REG_DISPCNT = DCNT_MODE0 | DCNT_OBJ | DCNT_OBJ_1D;
    while (1) {
        vid_vsync();
        u32 raw = REG_KEYINPUT;
        keys_seen = raw;
        u32 k = ~raw & KEY_MASK;
        KEY_OBJ(0); KEY_OBJ(1); KEY_OBJ(2); KEY_OBJ(3); KEY_OBJ(4);
        KEY_OBJ(5); KEY_OBJ(6); KEY_OBJ(7); KEY_OBJ(8); KEY_OBJ(9);
    }
}
