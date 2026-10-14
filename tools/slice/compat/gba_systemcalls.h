#ifndef COMPAT_GBA_SYSTEMCALLS_H
#define COMPAT_GBA_SYSTEMCALLS_H
#include "gba_types.h"
#ifdef __cplusplus
extern "C" {
#endif
#define COPY32 (1<<26)
#define FILL (1<<24)
static inline void VBlankIntrWait(void) { __asm__ volatile("swi 5" ::: "r0","r1","r2","r3","memory"); }
/* CpuFastSet as a plain word loop (the HAL only supports swi 5). */
void CpuFastSet(const void *src, void *dst, u32 mode);
#ifdef __cplusplus
}
#endif
#endif
