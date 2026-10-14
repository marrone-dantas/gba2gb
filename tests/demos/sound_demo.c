/* sound_demo (original, Thumb-only, Phase 4.3): a short loop on the four PSG
   channels plus a DirectSound SFX.
   - ch1: square lead (duty 50 %, decaying envelope, a sweep on every 4th note)
   - ch2: square bass (duty 25 %)
   - ch3: wave channel; two waveforms in the two wave RAM banks (bank-switched)
   - ch4: noise hi-hat
   - DirectSound A: an 8-bit 8192 Hz "zap" played through FIFO A, timer 0 and DMA1
     at frames 90 and 210.
   All registers are written with 16-bit or 32-bit stores at constant addresses. */
#include "gba.h"
#include "assets.h"

#define REG32(a) (*(volatile u32 *)(a))
#define SOUND1CNT_L REG16(0x04000060)
#define SOUND1CNT_H REG16(0x04000062)
#define SOUND1CNT_X REG16(0x04000064)
#define SOUND2CNT_L REG16(0x04000068)
#define SOUND2CNT_H REG16(0x0400006C)
#define SOUND3CNT_L REG16(0x04000070)
#define SOUND3CNT_H REG16(0x04000072)
#define SOUND3CNT_X REG16(0x04000074)
#define SOUND4CNT_L REG16(0x04000078)
#define SOUND4CNT_H REG16(0x0400007C)
#define SOUNDCNT_L  REG16(0x04000080)
#define SOUNDCNT_H  REG16(0x04000082)
#define SOUNDCNT_X  REG16(0x04000084)
#define WAVE_RAM(i) REG16(0x04000090 + 2 * (i))
#define DMA1SAD     REG32(0x040000BC)
#define DMA1DAD     REG32(0x040000C0)
#define DMA1CNT_H   REG16(0x040000C6)
#define TM0CNT_L    REG16(0x04000100)
#define TM0CNT_H    REG16(0x04000102)

static const u16 lead[16] = { 1546, 1602, 1650, 1673, 1714, 1750, 1783, 1798,
                              1783, 1750, 1714, 1673, 1650, 1602, 1546, 1602 };
static const u16 bass[4] = { 1046, 1155, 1253, 1155 };

u32 t;

int main(void)
{
    int i;
    SOUNDCNT_X = 0x0080;                       /* master enable */
    SOUNDCNT_L = 0xFF77;                       /* all PSG channels L+R, volume 7 */
    SOUNDCNT_H = 0x0B06;                       /* PSG 100 %, DMA A 100 %, A -> L+R, timer 0, reset FIFO A */
    SOUND3CNT_L = 0x0040;                      /* play bank 1: the CPU writes bank 0 */
    for (i = 0; i < 8; i++)                    /* bank 0: triangle */
        WAVE_RAM(i) = (u16)(((i < 4 ? 2 * i : 14 - 2 * i) * 0x11) | (((i < 4 ? 2 * i + 1 : 15 - 2 * i) * 0x11) << 8));
    SOUND3CNT_L = 0x0080;                      /* enable, play bank 0: the CPU writes bank 1 */
    for (i = 0; i < 8; i++)                    /* bank 1: saw */
        WAVE_RAM(i) = (u16)((2 * i * 0x10 + 2 * i) | ((2 * i + 1) * 0x11) << 8);
    REG_DISPCNT = DCNT_MODE0;
    t = 0;
    while (1) {
        vid_vsync();
        if ((t & 15) == 0) {
            u32 n = (t >> 4) & 15;
            SOUND1CNT_L = (n & 3) == 3 ? 0x0016 : 0x0008;   /* sweep up on every 4th note */
            SOUND1CNT_H = 0xC380;                           /* vol 12, decrease, step 3, duty 50 % */
            SOUND1CNT_X = 0x8000 | lead[n];
        }
        if ((t & 31) == 0) {
            SOUND2CNT_L = 0xA440;                           /* vol 10, decrease, step 4, duty 25 % */
            SOUND2CNT_H = 0x8000 | bass[(t >> 5) & 3];
        }
        if ((t & 63) == 32) {                               /* alternate the wave banks */
            SOUND3CNT_L = ((t >> 6) & 1) ? 0x00C0 : 0x0080;
            SOUND3CNT_H = 0x2000;                           /* 100 % */
            SOUND3CNT_X = 0x8000 | 1797;
        }
        if ((t & 15) == 8) {
            SOUND4CNT_L = 0x7100;                           /* vol 7, decrease, step 1 */
            SOUND4CNT_H = 0x8000 | 0x0021;                  /* shift 2, 15-bit, ratio 1 */
        }
        if (t == 90 || t == 210) {                          /* DirectSound SFX start */
            SOUNDCNT_H = 0x0B06;                            /* reset FIFO A */
            DMA1SAD = (u32)sfx_zap;
            DMA1DAD = 0x040000A0;
            DMA1CNT_H = 0xB640;                             /* enable, FIFO timing, 32-bit, repeat, dest fixed */
            TM0CNT_L = 65536 - 2048;                        /* 16.78 MHz / 2048 = 8192 Hz */
            TM0CNT_H = 0x0080;
        }
        if (t == 90 + SFX_LEN * 60 / 8192 + 1 || t == 210 + SFX_LEN * 60 / 8192 + 1) {
            TM0CNT_H = 0;                                   /* SFX stop */
            DMA1CNT_H = 0;
        }
        t++;
    }
}
