/* brin_demo (Thumb-only rewrite of the Tonc brin_demo behaviour, see README.md):
   loads a palette, a 4bpp tileset (CBB 0) and a 32x32 map (SBB 30) and scrolls BG0
   with the D-pad, starting at (192, 64). */
#include "gba.h"
#include "assets.h"

int main(void)
{
    int i;
    for (i = 0; i < 16; i++)
        PAL_BG[i] = brin_pal[i];
    for (i = 0; i < BRIN_TILE_WORDS; i++)
        VRAM32[i] = brin_tiles[i];
    volatile u16 *se = SE_MEM(30);
    for (i = 0; i < 1024; i++)
        se[i] = brin_map[i];
    REG_BG0CNT = (0 << 2) | (30 << 8);   /* CBB 0, SBB 30, 4bpp, 32x32 */
    REG_DISPCNT = DCNT_MODE0 | DCNT_BG0;
    int x = 192, y = 64;
    while (1) {
        vid_vsync();
        u32 k = ~REG_KEYINPUT & KEY_MASK;
        x += ((k >> 4) & 1) - ((k >> 5) & 1);
        y += ((k >> 7) & 1) - ((k >> 6) & 1);
        REG_BG0HOFS = x;
        REG_BG0VOFS = y;
    }
}
