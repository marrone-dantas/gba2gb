/* Minimal GBA definitions for the Phase 2 demos (Thumb-only, no libtonc). */
#ifndef GBA_H
#define GBA_H
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef signed short s16;

#define REG16(a) (*(volatile u16 *)(a))
#define REG_DISPCNT  REG16(0x04000000)
#define REG_DISPSTAT REG16(0x04000004)
#define REG_VCOUNT   REG16(0x04000006)
#define REG_BG0CNT   REG16(0x04000008)
#define REG_BG0HOFS  REG16(0x04000010)
#define REG_BG0VOFS  REG16(0x04000012)
#define REG_KEYINPUT REG16(0x04000130)
#define REG_IE       REG16(0x04000200)
#define REG_IME      REG16(0x04000208)

#define DCNT_MODE0  0x0000
#define DCNT_BG0    0x0100
#define DCNT_OBJ    0x1000
#define DCNT_OBJ_1D 0x0040

#define PAL_BG   ((volatile u16 *)0x05000000)
#define PAL_OBJ  ((volatile u16 *)0x05000200)
#define VRAM32   ((volatile u32 *)0x06000000)
#define OBJ_TILES32 ((volatile u32 *)0x06010000)
#define SE_MEM(sbb) ((volatile u16 *)(0x06000000 + (sbb) * 0x800))

/* OAM attributes: constant addresses only (the static I/O interceptor resolves
   them at compile time), hence macros with a constant object index. */
#define OAM_ATTR0(n) REG16(0x07000000 + 8 * (n))
#define OAM_ATTR1(n) REG16(0x07000002 + 8 * (n))
#define OAM_ATTR2(n) REG16(0x07000004 + 8 * (n))
#define ATTR0_HIDE   0x0200
#define ATTR0_SQUARE 0x0000
#define ATTR1_SIZE_8  0x0000
#define ATTR1_SIZE_16 0x4000
#define ATTR1_SIZE_32 0x8000
#define ATTR1_HFLIP  0x1000
#define ATTR1_VFLIP  0x2000

#define KEY_A      0x0001
#define KEY_B      0x0002
#define KEY_SELECT 0x0004
#define KEY_START  0x0008
#define KEY_RIGHT  0x0010
#define KEY_LEFT   0x0020
#define KEY_UP     0x0040
#define KEY_DOWN   0x0080
#define KEY_R      0x0100
#define KEY_L      0x0200
#define KEY_MASK   0x03FF

static inline void vid_vsync(void)
{
    while (REG_VCOUNT >= 160) ;
    while (REG_VCOUNT < 160) ;
}

static inline void vblank_intr_wait(void)
{
    __asm__ volatile("swi 5" ::: "r0", "r1", "r2", "r3", "memory");
}
#endif
