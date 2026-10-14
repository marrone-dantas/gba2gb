/* timer_demo (test program): timer 0 at 262144 Hz (prescaler 64) and timer 1 at
   16384 Hz (prescaler 1024), like Snek GBA. Every frame the values of both timers
   and the frame count are logged to a 64-entry ring at 0x03000000. Timer 1 is
   stopped at frame 30 (its value must freeze). */
#include "gba.h"

#define TM0D  (*(volatile u16 *)0x04000100)
#define TM0CNT (*(volatile u16 *)0x04000102)
#define TM1D  (*(volatile u16 *)0x04000104)
#define TM1CNT (*(volatile u16 *)0x04000106)

volatile u16 log_t0[64];
volatile u16 log_t1[64];
volatile u32 frames;

int main(void)
{
    u32 n = 0;
    TM0CNT = 0;
    TM0D = 0;
    TM0CNT = 0x0081;
    TM1D = 0;
    TM1CNT = 0x0083;
    REG_DISPCNT = DCNT_MODE0;
    while (1) {
        vid_vsync();
        log_t0[n & 63] = TM0D;
        log_t1[n & 63] = TM1D;
        n++;
        frames = n;
        if (n == 30)
            TM1CNT = 0;
    }
}
