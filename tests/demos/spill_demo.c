/* spill_demo (original, Thumb-only): Phase 5 A1 regression for the "spilled ROM
   pointer" miscompile. This is the affine_demo main loop before its workaround:
   it reads the ROM sine table sin_lut directly. Under register pressure GCC keeps
   &sin_lut in a stack slot, so the load base comes from `ldr rX, [sp, #d]`; before
   pointer provenance the interceptor classified that load as RAM and the GB build
   read WRAM garbage instead of the table. Results go to IWRAM (res[]) and to the
   OAM of object 0 (x = cos, y = sin) so both can be compared with the GBA.
   res[8] reads through a pointer of unknown address space (see srcs). */
#include "gba.h"
#include "assets.h"

u32 key_cur, key_prev;
int px = 104, py = 64;
volatile int res[9];
/* A pointer loaded from a ROM table: its address space (ROM or IWRAM) is unknown
   at compile time, so the GB build dispatches on the address at run time
   (HAL_DYN_ADDR); in strict mode it is a compile error. */
s16 ram_buf[16];
const s16 *const srcs[2] = {sin_lut, ram_buf};

int main(void)
{
    int i;
    for (i = 0; i < 32; i++)
        PAL_OBJ[i] = obj_pal[i];
    for (i = 0; i < SHIP_TILE_WORDS; i++)
        OBJ_TILES32[i] = ship_tiles[i];
    for (i = 0; i < 16; i++)
        ram_buf[i] = 3 * i - 7;
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
        int c = sin_lut[(ang + 64) & 255], s = sin_lut[ang];
        int inv = zoom ? 128 : 256;
        res[0] = c; res[1] = s;
        res[2] = (c * inv) >> 8;
        res[3] = (-s * inv) >> 8;
        res[4] = (s * inv) >> 8;
        res[5] = ang; res[6] = px; res[7] = py;
        res[8] = srcs[ang & 1][ang & 15];
        OAM_ATTR0(0) = ((80 + (s >> 3)) & 0xFF) | ATTR0_SQUARE;
        OAM_ATTR1(0) = ((112 + (c >> 3)) & 0x1FF) | ATTR1_SIZE_32;
        OAM_ATTR2(0) = 0;
        OAM_ATTR0(1) = py & 0xFF;
        OAM_ATTR1(1) = (px & 0x1FF) | ATTR1_SIZE_32;
        OAM_ATTR2(1) = 0;
    }
}
