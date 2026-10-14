/* affine_demo (original, Thumb-only): a 32x32 affine sprite (OBJ 0, affine group 0)
   rotates by 1/256 turn per frame; A toggles 2x zoom, the D-pad moves it, B
   reverses the rotation. OBJ 1 is a regular (non-affine) copy for reference.
   The matrix follows the usual convention pa = cos/s, pb = -sin/s, pc = sin/s,
   pd = cos/s (8.8 fixed point). Phase 4.1: on the GB side the matrix writes are
   replaced by a pre-rotated frame selection (tools/affine/affine_lut_baker.py). */
#include "gba.h"
#include "assets.h"

#define OAM_PA(g) REG16(0x07000006 + 32 * (g))
#define OAM_PB(g) REG16(0x0700000E + 32 * (g))
#define OAM_PC(g) REG16(0x07000016 + 32 * (g))
#define OAM_PD(g) REG16(0x0700001E + 32 * (g))
#define ATTR0_AFFINE 0x0100

u32 key_cur, key_prev;
/* The sine table is copied to IWRAM (.bss): a ROM pointer that GCC spills to the
   stack is not tracked by the interceptor (docs/affine.md, limits). */
s16 sin_tab[256];
int px = 104, py = 64;

int main(void)
{
    int i;
    for (i = 0; i < 32; i++)
        PAL_OBJ[i] = obj_pal[i];
    for (i = 0; i < SHIP_TILE_WORDS; i++)
        OBJ_TILES32[i] = ship_tiles[i];
    for (i = 0; i < 256; i++)
        sin_tab[i] = sin_lut[i];
    REG_DISPCNT = DCNT_MODE0 | DCNT_OBJ | DCNT_OBJ_1D;
    u32 ang = 0, zoom = 0, dir = 1;
    while (1) {
        vid_vsync();
        key_prev = key_cur;
        key_cur = ~REG_KEYINPUT & KEY_MASK;
        u32 hit = key_cur & ~key_prev;
        px += ((key_cur >> 4) & 1) - ((key_cur >> 5) & 1);
        py += ((key_cur >> 7) & 1) - ((key_cur >> 6) & 1);
        if (hit & KEY_A) zoom ^= 1;
        if (hit & KEY_B) dir = -dir;
        ang = (ang + dir) & 255;
        int c = sin_tab[(ang + 64) & 255], s = sin_tab[ang];
        int inv = zoom ? 128 : 256;
        OAM_PA(0) = (c * inv) >> 8;
        OAM_PB(0) = (-s * inv) >> 8;
        OAM_PC(0) = (s * inv) >> 8;
        OAM_PD(0) = (c * inv) >> 8;
        OAM_ATTR0(0) = (py & 0xFF) | ATTR0_SQUARE | ATTR0_AFFINE;
        OAM_ATTR1(0) = (px & 0x1FF) | ATTR1_SIZE_32;          /* affine group 0 */
        OAM_ATTR2(0) = 0;
        OAM_ATTR0(1) = 16;
        OAM_ATTR1(1) = 16 | ATTR1_SIZE_32;
        OAM_ATTR2(1) = 0;
    }
}
