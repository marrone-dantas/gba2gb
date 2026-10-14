/* key_demo (Thumb-only rewrite of the Tonc key_demo behaviour, see README.md):
   one 8x8 indicator sprite per key (A B Sel Start Right Left Up Down R L); its tile
   shows the state: up (grey), hit (red), released (yellow), held (green). Keys are
   polled every 8th frame like the original. Vsync uses the BIOS VBlankIntrWait. */
#include "gba.h"
#include "assets.h"

u32 kcur, kprev;

#define KEY_SPR(n)                                                           \
    do {                                                                     \
        u32 b = 1u << (n);                                                   \
        u32 st = (kcur & b) ? ((kprev & b) ? 3 : 1) : ((kprev & b) ? 2 : 0); \
        OAM_ATTR0(n) = 64;                                                   \
        OAM_ATTR1(n) = (24 + 16 * (n)) | ATTR1_SIZE_8;                       \
        OAM_ATTR2(n) = 32 + st;                                              \
    } while (0)

int main(void)
{
    int i;
    for (i = 0; i < 16; i++)
        PAL_OBJ[i] = key_pal[i];
    for (i = 0; i < KEY_TILE_WORDS; i++)
        OBJ_TILES32[32 * 8 + i] = key_tiles[i];
    REG_DISPSTAT = 0x0008;  /* VBlank IRQ */
    REG_IE = 0x0001;
    REG_IME = 1;
    REG_DISPCNT = DCNT_MODE0 | DCNT_OBJ | DCNT_OBJ_1D;
    u32 frame = 0;
    while (1) {
        vblank_intr_wait();
        if ((frame & 7) == 0) {
            kprev = kcur;
            kcur = ~REG_KEYINPUT & KEY_MASK;
        }
        frame++;
        KEY_SPR(0); KEY_SPR(1); KEY_SPR(2); KEY_SPR(3); KEY_SPR(4);
        KEY_SPR(5); KEY_SPR(6); KEY_SPR(7); KEY_SPR(8); KEY_SPR(9);
    }
}
