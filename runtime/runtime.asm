; runtime/runtime.asm — minimal Phase 0 runtime (ROM0)
; Harness loop: waits for START, calls KernelEntry, signals DONE.
; Also contains the 32-bit helper routines used by the generated code.
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
    ld a, $05            ; timer on, 262144 Hz (1 tick = 4 M-cycles)
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
    ldh [HR_DONE], a     ; end marker
    jr .wait

; GuardTrap: debug handler for failed profile-guided range guards.
; a = guard id. Records it, marks DONE = 2 and stops.
GuardTrap::
    di
    ldh [HR_GUARD], a
    ld a, 2
    ldh [HR_DONE], a
.halt:
    jr .halt

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

; V_ADD: d = high byte of A, e = high byte of B, result in T0
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

; ---- shifts on T0, amount in b ----------------------------------------
; Update C only if b != 0 (ARM register-shift semantics).
SH_LSL::
    ld a, b
    or a
    ret z
    cp 34
    jr c, .ok
    ld b, 33             ; 33 steps already clear everything and give C=0
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
    ld b, 32             ; >=32: all bits = sign, C = sign
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

; ---- MUL: T0 = T1 * T2 (low 32 bits); clobbers T1, T2 ----------------
MUL32::
    ld c, 32
; MUL32N: same, but only c iterations (c = bit length of the multiplier T2, or
; 8 * the number of result bytes needed; used by the narrowed backend)
MUL32N::
    xor a
    ldh [HR_T0], a
    ldh [HR_T0+1], a
    ldh [HR_T0+2], a
    ldh [HR_T0+3], a
.lp:
    ; T2 >>= 1, shifted-out bit goes to carry
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
