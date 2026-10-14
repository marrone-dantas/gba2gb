#ifndef COMPAT_GBA_INTERRUPT_H
#define COMPAT_GBA_INTERRUPT_H
#include "gba_types.h"
#define IRQ_VBLANK 1
#ifdef __cplusplus
extern "C" {
#endif
/* irqInit installs an ARM handler that acknowledges all interrupts (enough for
   VBlankIntrWait); irqEnable(IRQ_VBLANK) enables the VBlank IRQ. irqSet is ignored. */
void irqInit(void);
void irqEnable(int mask);
#ifdef __cplusplus
}
#endif
#define irqSet(a,b) ((void)0)
#endif
