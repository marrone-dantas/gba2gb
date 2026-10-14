; runtime/gb_timer_shims.asm - Phase 5 B2: GBA timers 0/1 (TMxCNT_L / TMxCNT_H) read
; and write shims (docs/hal.md "Timers").
;
; Time base: the GB TIMA runs free at 4096 Hz (TAC = 4) and TmSync extends it to a
; 24-bit tick count wTick (it is called from the VBlank ISR, every 16.7 ms, well
; inside TIMA's 62.5 ms wrap, and from every read). DIV bits 0-1 are the 16384 Hz
; phase inside a 4096 Hz tick (DIV and TIMA are both taps of the same internal
; counter), so "now" = wTick * 4 + (DIV & 3) in 16384 Hz units.
; A GBA timer value is reload + ((now - start) << s) with s = 10 / 4 / 2 / 0 for the
; prescalers 1 / 64 / 256 / 1024 (16.78 MHz / 262144 / 65536 / 16384 Hz), so its
; resolution is 1/16384 s (16 TM0 ticks at prescaler 64).
; Limits: overflow reload is exact only for reload = 0 (otherwise the wrap period
; is 65536 instead of 65536 - reload); count-up (cascade) and timer IRQs are not
; supported; while a DirectSound stream plays (gb_audio_shims.asm reprograms TIMA)
; the clock drifts.

DEF rDIV_T EQU $FF04
DEF rTIMA_T EQU $FF05
DEF rTAC_T EQU $FF07

SECTION "tm_state", WRAMX
wTick:: ds 3                  ; 4096 Hz ticks
wTimaLast: ds 1
; per timer (x = 0, 1): ctl, reload lo/hi, start (3 bytes, 16384 Hz), frozen lo/hi
DEF TM_CTL EQU 0
DEF TM_RLD EQU 1
DEF TM_START EQU 3
DEF TM_FRZ EQU 6
DEF TM_SIZE EQU 8
wTm0: ds TM_SIZE
wTm1: ds TM_SIZE
wNow: ds 3

SECTION "tm_code", ROMX, BANK[1]

TimerInit::
    ld hl, wTick
    ld b, 4 + 2 * TM_SIZE
    xor a
.c:
    ld [hl+], a
    dec b
    jr nz, .c
    ldh [rTIMA_T], a
    ld a, 4                       ; TIMA on, 4096 Hz
    ldh [rTAC_T], a
    ret

; wTick += (TIMA - wTimaLast). Preserves all registers but af.
TmSync::
    push bc
    push hl
    ldh a, [rTIMA_T]
    ld b, a
    ld hl, wTimaLast
    sub [hl]
    ld [hl], b
    ld hl, wTick
    add a, [hl]
    ld [hl+], a
    jr nc, .d
    inc [hl]
    jr nz, .d
    inc hl
    inc [hl]
.d:
    pop hl
    pop bc
    ret

; wNow = wTick * 4 + (DIV & 3), consistent snapshot
TmNow:
    di
.again:
    call TmSync
    ldh a, [rDIV_T]
    and 3
    ld b, a
    ldh a, [rTIMA_T]
    ld hl, wTimaLast
    cp [hl]
    jr nz, .again                 ; TIMA ticked between the two reads
    ld hl, wTick
    ld a, [hl+]
    ld e, a
    ld a, [hl+]
    ld d, a
    ld c, [hl]
    ei
    ; c:d:e <<= 2, | b
    sla e
    rl d
    rl c
    sla e
    rl d
    rl c
    ld a, e
    or b
    ld [wNow], a
    ld a, d
    ld [wNow + 1], a
    ld a, c
    ld [wNow + 2], a
    ret

; hl = timer struct -> de = current 16-bit value
TmValue:
    ld a, [hl]
    bit 7, a
    jr nz, .run
    ld de, TM_FRZ
    add hl, de
    ld a, [hl+]
    ld d, [hl]
    ld e, a
    ret
.run:
    push hl
    push af
    call TmNow
    pop af
    pop hl
    and 3
    ld b, a                       ; prescaler
    push hl
    ld de, TM_START
    add hl, de
    ld a, [wNow]
    sub [hl]
    ld e, a
    inc hl
    ld a, [wNow + 1]
    sbc [hl]
    ld d, a                       ; de = (now - start) & $FFFF
    ld a, b
    or a
    jr z, .s10
    dec a
    jr z, .s4
    dec a
    jr z, .s2
    jr .add
.s10:
    ld d, e                       ; << 8
    ld e, 0
    sla e
    rl d
.s2:
    sla e
    rl d
    sla e
    rl d
    jr .add
.s4:
    REPT 4
    sla e
    rl d
    ENDR
.add:
    pop hl
    inc hl                        ; reload
    ld a, [hl+]
    add a, e
    ld e, a
    ld a, [hl]
    adc d
    ld d, a
    ret

; de -> HRAM slot c (zero-extended to 32 bits)
TmOut:
    ld a, e
    ldh [c], a
    inc c
    ld a, d
    ldh [c], a
    inc c
    xor a
    ldh [c], a
    inc c
    ldh [c], a
    ret

HAL_TM0D::
    push bc
    ld hl, wTm0
    call TmValue
    pop bc
    jr TmOut
HAL_TM1D::
    push bc
    ld hl, wTm1
    call TmValue
    pop bc
    jr TmOut

; TMxCNT_L write: the reload value (the counter itself changes only on start)
HAL_WR_TM0D::
    ld hl, wTm0 + TM_RLD
    jr TmReload
HAL_WR_TM1D::
    ld hl, wTm1 + TM_RLD
TmReload:
    ldh a, [c]
    ld [hl+], a
    inc c
    ldh a, [c]
    ld [hl], a
    ret

; TMxCNT_H write: start on 0 -> 1 of bit 7, freeze the value on 1 -> 0
HAL_WR_TM0CNT_TIMER::
    ld hl, wTm0
    jr TmCtl
HAL_WR_TM1CNT_H::
    ld hl, wTm1
TmCtl:
    ldh a, [c]
    ld b, a                       ; new
    ld a, [hl]                    ; old
    xor b
    bit 7, a
    jr z, .store                  ; enable unchanged
    bit 7, b
    jr z, .stop
    ; start: start = now
    push hl
    push bc
    call TmNow
    pop bc
    pop hl
    push hl
    ld de, TM_START
    add hl, de
    ld a, [wNow]
    ld [hl+], a
    ld a, [wNow + 1]
    ld [hl+], a
    ld a, [wNow + 2]
    ld [hl], a
    pop hl
    jr .store
.stop:
    push hl
    push bc
    call TmValue
    pop bc
    pop hl
    push hl
    push de
    ld de, TM_FRZ
    add hl, de
    pop de
    ld a, e
    ld [hl+], a
    ld [hl], d
    pop hl
.store:
    ld [hl], b
    ret
