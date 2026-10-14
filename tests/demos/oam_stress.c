/* oam_stress (test program, not a Tonc demo): 12 32x32 objects = 192 GB hardware
   sprites, more than the 40-sprite limit and more than 10 per line; they drift with
   the frame counter (9-bit X / 8-bit Y wrap-around) and the D-pad moves all of them. */
#include "gba.h"
#include "assets.h"

#define OBJ(n, x, y)                                               \
    do {                                                           \
        OAM_ATTR0(n) = (y) & 0xFF;                                 \
        OAM_ATTR1(n) = ((x) & 0x1FF) | ATTR1_SIZE_32 | (((n) & 1) ? ATTR1_HFLIP : 0); \
        OAM_ATTR2(n) = 0;                                          \
    } while (0)

int main(void)
{
    int i;
    for (i = 0; i < 32; i++)
        PAL_OBJ[i] = obj_pal[i];
    for (i = 0; i < OBJ_TILE_WORDS; i++)
        OBJ_TILES32[i] = obj_tiles[i];
    REG_DISPCNT = DCNT_MODE0 | DCNT_OBJ | DCNT_OBJ_1D;
    int t = 0, dx = 0, dy = 0;
    while (1) {
        vid_vsync();
        u32 k = ~REG_KEYINPUT & KEY_MASK;
        dx += ((k >> 4) & 1) - ((k >> 5) & 1);
        dy += ((k >> 7) & 1) - ((k >> 6) & 1);
        t++;
        int x = dx + t, y = dy + (t >> 1);
        OBJ(0, x, y);        OBJ(1, x + 40, y);       OBJ(2, x + 80, y);
        OBJ(3, x + 120, y);  OBJ(4, x + 160, y);      OBJ(5, x + 200, y);
        OBJ(6, x, y + 40);   OBJ(7, x + 60, y + 40);  OBJ(8, x + 120, y + 40);
        OBJ(9, x + 30, y + 90); OBJ(10, x + 90, y + 90); OBJ(11, 480 - x, 140 - y);
    }
}
