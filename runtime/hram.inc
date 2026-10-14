; runtime/hram.inc — mapa da HRAM usada pelo código SM83 gerado (ver docs/mapa_hram.md)
; Registradores ARM R0..R15: 4 bytes cada, little-endian, em $FF80-$FFBF.
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
DEF HR_PC  EQU $FFBC   ; R15 (não mantido em tempo de execução; reservado)
; Flags do CPSR, um byte cada (0 ou 1)
DEF HR_FN  EQU $FFC0
DEF HR_FZ  EQU $FFC1
DEF HR_FC  EQU $FFC2
DEF HR_FV  EQU $FFC3
; Temporários de 32 bits do backend
DEF HR_T0  EQU $FFC4
DEF HR_T1  EQU $FFC8
DEF HR_T2  EQU $FFCC
; Controle do harness (teste lockstep)
DEF HR_START EQU $FFD0 ; harness escreve 1 para iniciar o kernel
DEF HR_DONE  EQU $FFD1 ; runtime escreve 1 no fim (marcador de fim)
DEF HR_TCNT  EQU $FFD2 ; contador de overflows do timer (16 bits LE)
DEF HR_TIMA  EQU $FFD4 ; TIMA amostrado no fim
; Memória ARM emulada: endereço ARM -> $C000 | (addr & $1FFF) (WRAM de 8 KiB)
; Pilha SM83 nativa: começa em $D000 e cresce para baixo.
