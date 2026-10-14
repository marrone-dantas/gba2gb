; runtime/hram.inc — HRAM map used by the generated SM83 code (see docs/hram_map.md)
; ARM registers R0..R15: 4 bytes each, little-endian, at $FF80-$FFBF.
DEF HR_R0  EQU $FF80
DEF HR_R1  EQU $FF84
DEF HR_R2  EQU $FF88
DEF HR_R3  EQU $FF8C
DEF HR_R4  EQU $FF90
DEF HR_R5  EQU $FF94
DEF HR_R6  EQU $FF98
DEF HR_R7  EQU $FF9C
DEF HR_R8  EQU $FFA0
DEF HR_R9  EQU $FFA4
DEF HR_R10 EQU $FFA8
DEF HR_R11 EQU $FFAC
DEF HR_R12 EQU $FFB0
DEF HR_SP  EQU $FFB4   ; R13
DEF HR_LR  EQU $FFB8   ; R14
DEF HR_PC  EQU $FFBC   ; R15 (not maintained at run time; reserved)
; CPSR flags, one byte each (0 or 1)
DEF HR_FN  EQU $FFC0
DEF HR_FZ  EQU $FFC1
DEF HR_FC  EQU $FFC2
DEF HR_FV  EQU $FFC3
; Backend 32-bit temporaries
DEF HR_T0  EQU $FFC4
DEF HR_T1  EQU $FFC8
DEF HR_T2  EQU $FFCC
; Harness control (lockstep test)
DEF HR_START EQU $FFD0 ; harness writes 1 to start the kernel
DEF HR_DONE  EQU $FFD1 ; runtime writes 1 at the end (end marker)
DEF HR_TCNT  EQU $FFD2 ; timer overflow counter (16-bit LE)
DEF HR_TIMA  EQU $FFD4 ; TIMA sampled at the end
DEF HR_GUARD EQU $FFD5 ; id of the failed range guard (DONE = 2)
; WRAM map (docs/memory_map.md):
;   $C000-$CFFF emulated ARM memory window: ARM address -> $C000 | (addr & $0FFF)
;   $D000-$D09F shadow OAM (page-aligned, OAM DMA source)
;   $D100-$D2FF HAL state (GBA OAM mirror, input, VBlank flags)
;   $D300-$DFFF native SM83 stack (starts at $E000, grows downward)
