#include "gba_interrupt.h"
#include "gba_input.h"
#include "gba_systemcalls.h"
static u16 cur, prev;
void scanKeys(void) { prev = cur; cur = ~REG_KEYINPUT & 0x3ff; }
u16 keysHeld(void) { return cur; }
u16 keysDown(void) { return cur & ~prev; }
void CpuFastSet(const void *src, void *dst, u32 mode)
{
    const u32 *s = src; u32 *d = dst; u32 n = mode & 0x1fffff;
    if (mode & FILL) { u32 v = *s; while (n--) *d++ = v; }
    else while (n--) *d++ = *s++;
}

#define REG_IE (*(vu16*)0x04000200)
#define REG_IME (*(vu16*)0x04000208)
#define REG_DISPSTAT (*(vu16*)0x04000004)
#define IRQ_HANDLER (*(void (**)(void))0x03007FFC)
extern void compat_irq_handler(void);
void irqInit(void) { REG_IME = 0; IRQ_HANDLER = compat_irq_handler; REG_IME = 1; }
void irqEnable(int mask)
{
    if (mask & 1) REG_DISPSTAT |= 1 << 3;
    REG_IE |= mask;
}
