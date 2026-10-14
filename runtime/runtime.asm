; runtime/runtime.asm — runtime mínimo da Fase 0 (ROM0)
; Laço do harness: espera START, chama KernelEntry, sinaliza DONE.
; Também contém as rotinas auxiliares de 32 bits usadas pelo código gerado.
INCLUDE "hram.inc"

DEF rTIMA EQU $FF05
DEF rTMA  EQU $FF06
DEF rTAC  EQU $FF07
DEF rIF   EQU $FF0F
DEF rIE   EQU $FFFF

SECTION "vec_timer", ROM0[$50]
    jp TimerISR

SECTION "entry", ROM0[$100]
    nop
    jp Start
    ds $150 - @, 0

SECTION "runtime", ROM0
Start:
    di
    ld sp, $D000
    xor a
    ldh [HR_START], a
    ldh [HR_DONE], a
    ldh [rTMA], a
    ld a, $05            ; timer ligado, 262144 Hz (1 tick = 4 M-cycles)
    ldh [rTAC], a
    ld a, $04
    ldh [rIE], a
.wait:
    ldh a, [HR_START]
    or a
    jr z, .wait
    di
    xor a
    ldh [HR_START], a
    ldh [HR_TCNT], a
    ldh [HR_TCNT+1], a
    ldh [rIF], a
    ldh [rTIMA], a
    ei
    call KernelEntry
    ldh a, [rTIMA]
    di
    ldh [HR_TIMA], a
    ld a, 1
    ldh [HR_DONE], a     ; marcador de fim
    jr .wait

TimerISR:
    push af
    ldh a, [HR_TCNT]
    inc a
    ldh [HR_TCNT], a
    jr nz, .s
    ldh a, [HR_TCNT+1]
    inc a
    ldh [HR_TCNT+1], a
.s: pop af
    reti

; ---- flags -------------------------------------------------------------
; NZ_T0: N = bit31(T0), Z = (T0 == 0)
NZ_T0::
    ldh a, [HR_T0+3]
    rlca
    and 1
    ldh [HR_FN], a
    ldh a, [HR_T0]
    ld b, a
    ldh a, [HR_T0+1]
    or b
    ld b, a
    ldh a, [HR_T0+2]
    or b
    ld b, a
    ldh a, [HR_T0+3]
    or b
    sub 1                ; carry <=> zero
    ld a, 0
    rla
    ldh [HR_FZ], a
    ret

; V_ADD: d = byte alto de A, e = byte alto de B, resultado em T0
V_ADD::
    ldh a, [HR_T0+3]
    xor d
    ld b, a
    ldh a, [HR_T0+3]
    xor e
    and b
    rlca
    and 1
    ldh [HR_FV], a
    ret

; V_SUB (A - B): V = ((A^B) & (A^R)) bit 31
V_SUB::
    ldh a, [HR_T0+3]
    xor d
    ld b, a
    ld a, d
    xor e
    and b
    rlca
    and 1
    ldh [HR_FV], a
    ret

; ---- deslocamentos sobre T0, quantidade em b ---------------------------
; Atualizam C só se b != 0 (semântica ARM de deslocamento por registrador).
SH_LSL::
    ld a, b
    or a
    ret z
    cp 34
    jr c, .ok
    ld b, 33             ; 33 passos já zeram tudo e dão C=0
.ok:
    ld hl, HR_T0
.lp:
    sla [hl]
    inc l
    rl [hl]
    inc l
    rl [hl]
    inc l
    rl [hl]
    ld l, LOW(HR_T0)
    dec b
    jr nz, .lp
    jr StoreC

SH_LSR::
    ld a, b
    or a
    ret z
    cp 34
    jr c, .ok
    ld b, 33
.ok:
    ld hl, HR_T0+3
.lp:
    srl [hl]
    dec l
    rr [hl]
    dec l
    rr [hl]
    dec l
    rr [hl]
    ld l, LOW(HR_T0+3)
    dec b
    jr nz, .lp
    jr StoreC

SH_ASR::
    ld a, b
    or a
    ret z
    cp 33
    jr c, .ok
    ld b, 32             ; >=32: todos os bits = sinal, C = sinal
.ok:
    ld hl, HR_T0+3
.lp:
    sra [hl]
    dec l
    rr [hl]
    dec l
    rr [hl]
    dec l
    rr [hl]
    ld l, LOW(HR_T0+3)
    dec b
    jr nz, .lp
    jr StoreC

SH_ROR::
    ld a, b
    or a
    ret z
    and 31
    jr nz, .ok
    ld a, 32
.ok:
    ld b, a
.lp:
    ldh a, [HR_T0]
    rrca                 ; carry = bit 0
    ld hl, HR_T0+3
    rr [hl]
    dec l
    rr [hl]
    dec l
    rr [hl]
    dec l
    rr [hl]
    dec b
    jr nz, .lp
    ; fallthrough
StoreC:
    ld a, 0
    rla
    ldh [HR_FC], a
    ret

; ---- MUL: T0 = T1 * T2 (32 bits baixos); destrói T1, T2 ----------------
MUL32::
    xor a
    ldh [HR_T0], a
    ldh [HR_T0+1], a
    ldh [HR_T0+2], a
    ldh [HR_T0+3], a
    ld c, 32
.lp:
    ; T2 >>= 1, bit que sai em carry
    ld hl, HR_T2+3
    srl [hl]
    dec l
    rr [hl]
    dec l
    rr [hl]
    dec l
    rr [hl]
    jr nc, .skip
    ld hl, HR_T1
    ldh a, [HR_T0]
    add [hl]
    ldh [HR_T0], a
    inc l
    ldh a, [HR_T0+1]
    adc [hl]
    ldh [HR_T0+1], a
    inc l
    ldh a, [HR_T0+2]
    adc [hl]
    ldh [HR_T0+2], a
    inc l
    ldh a, [HR_T0+3]
    adc [hl]
    ldh [HR_T0+3], a
.skip:
    ld hl, HR_T1
    sla [hl]
    inc l
    rl [hl]
    inc l
    rl [hl]
    inc l
    rl [hl]
    dec c
    jr nz, .lp
    ret
