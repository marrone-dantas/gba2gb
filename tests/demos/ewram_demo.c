/* ewram_demo (original, Thumb-only): Phase 5 A2 test program ("kernel") using
   more than 8 KiB of EWRAM (about 26 KiB in five objects). On the GB build
   EWRAM lives in MBC5 SRAM (16 x 8 KiB banks, tools/sram/ewram_alloc.py places
   the objects): buf_a and buf_b do not fit one bank together, big spans two banks
   (run-time bank selection) and pick[] holds pointers of unknown provenance
   (run-time address-space dispatch). Results go to IWRAM res[]; done = 1 when the
   init work is finished, then each frame updates a running checksum. */
#include "gba.h"

#define EWRAM(n) __attribute__((section(".ewram." #n)))
#define N 6000

EWRAM(buf_a) u8 buf_a[N];
EWRAM(buf_b) u8 buf_b[N];
EWRAM(hist) u32 hist[256];
EWRAM(big) u16 big[6144];          /* 12 KiB: two banks */
EWRAM(lut) u16 lut[64];
volatile u32 res[8];
volatile u32 done;
u8 *const pick[2] = {buf_a, buf_b};

static u32 mix(u32 h, u32 v) { return (h ^ v) * 0x01000193u; }

int main(void)
{
    u32 i, h;
    for (i = 0; i < N; i++)                         /* single bank: switch hoisted */
        buf_a[i] = (u8)(i * 7 + (i >> 5));
    for (i = 0; i < N; i++)                         /* two banks in one loop */
        buf_b[i] = buf_a[N - 1 - i] ^ 0x5A;
    for (i = 0; i < 256; i++)
        hist[i] = 0;
    for (i = 0; i < N; i++)
        hist[buf_b[i]]++;
    for (i = 0; i < 6144; i++)                      /* spans banks: run-time bank */
        big[i] = (u16)(i * 3 + 1);
    for (i = 0; i < 64; i++)
        lut[i] = (u16)(i * i);
    h = 2166136261u;
    for (i = 0; i < 256; i++)
        h = mix(h, hist[i]);
    res[0] = h;
    h = 0;
    for (i = 0; i < 6144; i += 7)
        h += big[i];
    res[1] = h;
    res[2] = buf_a[1234] | (buf_b[4321] << 8) | (lut[17] << 16);
    h = 0;
    for (i = 0; i < 64; i++)
        h += pick[i & 1][i * 90];                     /* pointer from a ROM table */
    res[3] = h;
    done = 1;
    u32 k = 0, ia = 0, ib = 0;
    while (1) {
        vid_vsync();
        k++;
        ia += 97; if (ia >= 6144) ia -= 6144;
        ib += 13; if (ib >= N) ib -= N;
        big[ia] += (u16)k;
        buf_b[ib] = (u8)k;
        res[4] = mix(res[4], big[ia] + buf_b[ib] + pick[k & 1][ib]);
        res[5] = k;
    }
}
