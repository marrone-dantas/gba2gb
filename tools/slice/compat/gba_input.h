#ifndef COMPAT_GBA_INPUT_H
#define COMPAT_GBA_INPUT_H
#include "gba_types.h"
#ifdef __cplusplus
extern "C" {
#endif
#define REG_KEYINPUT (*(vu16*)0x04000130)
enum { KEY_A=1, KEY_B=2, KEY_SELECT=4, KEY_START=8, KEY_RIGHT=16, KEY_LEFT=32,
       KEY_UP=64, KEY_DOWN=128, KEY_R=256, KEY_L=512 };
void scanKeys(void);
u16 keysHeld(void);
u16 keysDown(void);
#ifdef __cplusplus
}
#endif
#endif
