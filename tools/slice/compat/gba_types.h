/* Minimal libgba-compatible headers (own implementation, for building homebrew
   sources against the gba2gb toolchain without devkitPro). Only what the ports use. */
#ifndef COMPAT_GBA_TYPES_H
#define COMPAT_GBA_TYPES_H
#include <stdint.h>
#include <stdbool.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32;
typedef int8_t s8; typedef int16_t s16; typedef int32_t s32;
typedef volatile u16 vu16; typedef volatile u32 vu32;
#define ALIGN(n) __attribute__((aligned(n)))
#define IWRAM_CODE
#define EWRAM_DATA
#define REG_BASE 0x04000000
#endif
