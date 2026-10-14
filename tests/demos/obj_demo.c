/* obj_demo (Thumb-only rewrite of the Tonc obj_demo behaviour, see README.md):
   a 32x32 4bpp sprite moved with the D-pad (wraps around the 9-bit X / 8-bit Y
   space), A/B flip it, Select swaps its palette, Start toggles 1D/2D mapping,
   L/R change the start tile. Three 16x16 sprites orbit to exercise splitting. */
#include "gba.h"
#include "assets.h"

u32 key_cur, key_prev;   /* .bss */
int px = 96, py = 32;     /* .data */

int main(void)
{
    int i;
    for (i = 0; i < 32; i++)
        PAL_OBJ[i] = obj_pal[i];
    for (i = 0; i < OBJ_TILE_WORDS; i++)
        OBJ_TILES32[i] = obj_tiles[i];
    OAM_ATTR0(1) = ATTR0_HIDE; OAM_ATTR0(2) = ATTR0_HIDE; OAM_ATTR0(3) = ATTR0_HIDE;
    u32 dcnt = DCNT_MODE0 | DCNT_OBJ | DCNT_OBJ_1D;
    REG_DISPCNT = dcnt;
    u32 hflip = 0, vflip = 0, pb = 0, tid = 0, t = 0;
    while (1) {
        vid_vsync();
        key_prev = key_cur;
        key_cur = ~REG_KEYINPUT & KEY_MASK;
        u32 hit = key_cur & ~key_prev;
        px += ((key_cur >> 4) & 1) - ((key_cur >> 5) & 1);
        py += ((key_cur >> 7) & 1) - ((key_cur >> 6) & 1);
        if (hit & KEY_A) hflip ^= ATTR1_HFLIP;
        if (hit & KEY_B) vflip ^= ATTR1_VFLIP;
        if (hit & KEY_SELECT) pb ^= 1;
        if (hit & KEY_START) { dcnt ^= DCNT_OBJ_1D; REG_DISPCNT = dcnt; }
        if (hit & KEY_L) tid--;
        if (hit & KEY_R) tid++;
        t++;
        OAM_ATTR0(0) = (py & 0xFF) | ATTR0_SQUARE;
        OAM_ATTR1(0) = (px & 0x1FF) | hflip | vflip | ATTR1_SIZE_32;
        OAM_ATTR2(0) = (tid & 0x3FF) | (pb << 12);
        OAM_ATTR0(1) = ((py + 40) & 0xFF);
        OAM_ATTR1(1) = ((px + t) & 0x1FF) | ATTR1_SIZE_16;
        OAM_ATTR2(1) = 16;
        OAM_ATTR0(2) = ((py - 24 + (t >> 1)) & 0xFF);
        OAM_ATTR1(2) = ((px + 48) & 0x1FF) | ATTR1_SIZE_16 | ATTR1_HFLIP;
        OAM_ATTR2(2) = 16;
        OAM_ATTR0(3) = ((200 + t) & 0xFF);
        OAM_ATTR1(3) = ((500 + 2 * t) & 0x1FF) | ATTR1_SIZE_16;
        OAM_ATTR2(3) = 16 | (1 << 12);
    }
}
