; runtime/gb_audio_shims.asm — GBA sound registers -> DMG APU (Phase 4.3, docs/audio.md).
; Included by gb_hal_shims.asm.
;
; HAL_SND_WR: b = low byte of the GBA register offset (0x60-0x9F), c = HRAM slot of
; the value, e = store width in bytes. Every byte of the store is mapped on its own
; (SndByte), so 8-, 16- and 32-bit stores behave like on the GBA. All DMG register
; writes of the PSG mapping go through SndOut (one `ldh [c], a`, hooked by the tests).
;
; DirectSound: HAL_WR_DMA1SAD / DMA1CNT_H / TM0CNT_H start a stream when DMA1 and
; timer 0 are both on: the SFX found in SfxTab (baked offline by
; tools/audio/dsound_convert.py as 4-bit, 32-sample chunks at 8192 Hz) is played on
; channel 3, one chunk per timer interrupt (256 Hz). Channel 3 is borrowed: PSG
; channel 3 writes only update the shadows meanwhile and are restored afterwards.

DEF rNR30 EQU $FF1A
DEF rNR32 EQU $FF1C
DEF rNR33 EQU $FF1D
DEF rNR34 EQU $FF1E
DEF rNR50 EQU $FF24
DEF rNR51 EQU $FF25
DEF rNR52 EQU $FF26
DEF rTIMA EQU $FF05
DEF rTMA  EQU $FF06
DEF rTAC  EQU $FF07
DEF WAVE  EQU $FF30
DEF SFX_X EQU 1792              ; ch3 period for 32 samples at 8192 Hz: 2097152 / (2048 - x)

SECTION "vec_timer", ROM0[$50]
    jp SfxTimerISR

SECTION "snd_state", WRAMX
wSnd3Ctl:: ds 1                 ; SOUND3CNT_L low byte (bank mode / select / enable)
wSnd3Sh:: ds 5                  ; shadows of NR30-NR34 as mapped
wWave:: ds 32                   ; GBA wave RAM banks 0 and 1
wSndL:: ds 1                    ; SOUNDCNT_L low (master volumes)
wSndR:: ds 1                    ; SOUNDCNT_L high (PSG routing)
wSndH:: ds 1                    ; SOUNDCNT_H low (PSG ratio, DMA volumes)
wSndH2:: ds 1                   ; SOUNDCNT_H high (DMA routing)
wSfxSrc:: ds 4                  ; DMA1SAD
wDmaOn:: ds 1
wTmOn:: ds 1
wSfxOn:: ds 1
wSfxBank:: ds 1
wSfxPtr:: ds 2
wSfxLeft:: ds 2
wSndTmp: ds 1

SECTION "snd_code", ROM0
; ---------------------------------------------------------------- PSG mapping
HAL_SND_WR::
.byte:
    ldh a, [c]
    push bc
    push de
    call SndByte
    pop de
    pop bc
    inc b
    inc c
    dec e
    jr nz, .byte
.end::
    ret

SndOut::                        ; c = DMG register low byte, a = value
    ldh [c], a
    ret

; a = value byte, b = GBA offset low byte
SndByte:
    ld d, a
    ld a, b
    cp $90
    jp nc, SndWave
    sub $60
    ret c
    add a, a
    ld l, a
    ld h, 0
    ld bc, SndTab
    add hl, bc
    ld a, [hl+]
    ld h, [hl]
    ld l, a
    ld a, d
    jp hl

SndTab:
    dw .nr10, .ign, .nr11, .nr12, .nr13, .nr14, .ign, .ign          ; 60-67
    dw .nr21, .nr22, .ign, .ign, .nr23, .nr24, .ign, .ign           ; 68-6F
    dw .s3l, .ign, .nr31, .nr32, .nr33, .nr34, .ign, .ign           ; 70-77
    dw .nr41, .nr42, .ign, .ign, .nr43, .nr44, .ign, .ign           ; 78-7F
    dw .vol, .route, .ratio, .droute, .nr52, .ign, .ign, .ign       ; 80-87
    dw .ign, .ign, .ign, .ign, .ign, .ign, .ign, .ign               ; 88-8F
.ign:
    ret
.nr10:                          ; SOUND1CNT_L: same fields (shift, direction, time)
    and $7F
    ld c, $10
    jp SndOut
.nr11:                          ; SOUND1CNT_H low: duty | length
    ld c, $11
    jp SndOut
.nr12:                          ; SOUND1CNT_H high: envelope
    ld c, $12
    jp SndOut
.nr13:
    ld c, $13
    jp SndOut
.nr14:                          ; SOUND1CNT_X high: init (15), length enable (14), freq 8-10
    and $C7
    ld c, $14
    jp SndOut
.nr21:
    ld c, $16
    jp SndOut
.nr22:
    ld c, $17
    jp SndOut
.nr23:
    ld c, $18
    jp SndOut
.nr24:
    and $C7
    ld c, $19
    jp SndOut
.s3l:                           ; SOUND3CNT_L: bit 7 DAC, bit 6 played bank, bit 5 64-digit mode
    ld b, a
    ld a, [wSnd3Ctl]
    xor b
    ld e, a                     ; changed bits
    ld a, b
    ld [wSnd3Ctl], a
    and $80
    ld [wSnd3Sh], a
    bit 6, e
    jr nz, .bank
    ld a, [wSfxOn]
    or a
    ret nz
    ld a, [wSnd3Sh]
    ld c, $1A
    jp SndOut
.bank:                          ; bank switch: reload the DMG wave RAM from the shadow
    ld a, [wSfxOn]
    or a
    ret nz
    jp Ch3Restore
.nr31:
    ld [wSnd3Sh + 1], a
    ld c, $1B
    jr .ch3
.nr32:                          ; SOUND3CNT_H high: volume bits 13-14 -> NR32 5-6; force 75 % -> 100 %
    bit 7, a
    jr z, .v
    ld a, $20
    jr .vs
.v:
    and $60
.vs:
    ld [wSnd3Sh + 2], a
    ld c, $1C
    jr .ch3
.nr33:
    ld [wSnd3Sh + 3], a
    ld c, $1D
    jr .ch3
.nr34:
    and $C7
    ld [wSnd3Sh + 4], a
    ld c, $1E
.ch3:
    ld b, a
    ld a, [wSfxOn]              ; channel 3 is borrowed by DirectSound
    or a
    ret nz
    ld a, b
    jp SndOut
.nr41:
    and $3F
    ld c, $20
    jp SndOut
.nr42:
    ld c, $21
    jp SndOut
.nr43:                          ; SOUND4CNT_H low: clock shift | width | ratio (same layout)
    ld c, $22
    jp SndOut
.nr44:
    and $C0
    ld c, $23
    jp SndOut
.vol:
    ld [wSndL], a
    jp SndNR50
.route:
    ld [wSndR], a
    jp SndNR51
.ratio:
    ld [wSndH], a
    jp SndNR50
.droute:
    ld [wSndH2], a
    jp SndNR51
.nr52:
    and $80
    ld c, $26
    jp SndOut

; wave RAM 0x90-0x9F: the CPU accesses the bank that is NOT played
SndWave:
    sub $90
    ld e, a
    ld a, [wSnd3Ctl]
    and $40
    xor $40                     ; not played bank -> offset 0 / 16 ... ($40 -> 0, 0 -> $40)
    rrca
    rrca                        ; $10 or 0
    add a, e
    ld e, a
    ld a, d
    ld d, 0
    ld hl, wWave
    add hl, de
    ld [hl], a
    ret

; NR50 = SOUNDCNT_L master volumes scaled by the PSG ratio (SOUNDCNT_H bits 0-1)
SndNR50:
    ld a, [wSndL]
    and $07
    call .scale
    ld b, a
    ld a, [wSndL]
    swap a
    and $07
    call .scale
    swap a
    or b
    ld c, $24
    jp SndOut
.scale:                         ; a = 0-7 -> (a + 1) * ratio - 1, at least 0
    inc a
    ld e, a
    ld a, [wSndH]
    and 3
    jr z, .q
    dec a
    jr z, .h
    ld a, e
    dec a
    ret
.q:
    ld a, e
    srl a
    srl a
    jr .m
.h:
    ld a, e
    srl a
.m:
    or a
    ret z
    dec a
    ret

; NR51 = PSG routing; while a SFX plays, channel 3 follows the DMA A routing (bits 8-9)
SndNR51:
    ld a, [wSfxOn]
    or a
    ld a, [wSndR]
    jr z, .o
    and $BB                     ; clear ch3 left/right
    ld b, a
    ld a, [wSndH2]
    and 1                       ; A right
    jr z, .r
    set 2, b
.r:
    ld a, [wSndH2]
    and 2                       ; A left
    jr z, .l
    set 6, b
.l:
    ld a, b
.o:
    ld c, $25
    jp SndOut

; reload ch3 from the shadows (DAC off while writing wave RAM, then retrigger)
Ch3Restore:
    xor a
    ldh [rNR30], a
    ld a, [wSnd3Ctl]
    and $40                     ; played bank
    rrca
    rrca
    ld e, a
    ld d, 0
    ld hl, wWave
    add hl, de
    ld c, LOW(WAVE)
    ld b, 16
.cp:
    ld a, [hl+]
    ldh [c], a
    inc c
    dec b
    jr nz, .cp
    ld a, [wSnd3Sh]
    ldh [rNR30], a
    ld a, [wSnd3Sh + 2]
    ldh [rNR32], a
    ld a, [wSnd3Sh + 3]
    ldh [rNR33], a
    ld a, [wSnd3Sh]
    or a
    ret z
    ld a, [wSnd3Sh + 4]
    and $07
    or $80                      ; retrigger (a DMG DAC-off stops the channel)
    ldh [rNR34], a
    ret

; ---------------------------------------------------------------- DirectSound
HAL_WR_DMA1SAD::
    ld hl, wSfxSrc
    ld b, 4
.c:
    ldh a, [c]
    ld [hl+], a
    inc c
    dec b
    jr nz, .c
    ret

HAL_WR_DMA1CNT_H::
    inc c
    ldh a, [c]
    and $80
    ld [wDmaOn], a
    jr SfxUpdate

HAL_WR_TM0CNT_H::
    ldh a, [c]
    and $80
    ld [wTmOn], a
    ; fall through

SfxUpdate:
    ld a, [wDmaOn]
    ld b, a
    ld a, [wTmOn]
    and b
    jr z, SfxStop
    ld a, [wSfxOn]
    or a
    ret nz
    ; find the SFX by its ARM address
    ld hl, SfxTab
    ld a, [SfxCount]
    or a
    ret z
    ld b, a
.find:
    push hl
    ld de, wSfxSrc
    ld c, 4
.cmp:
    ld a, [de]
    cp [hl]
    jr nz, .no
    inc de
    inc hl
    dec c
    jr nz, .cmp
    ld a, [hl+]                 ; bank
    ld [wSfxBank], a
    ld a, [hl+]
    ld [wSfxPtr], a
    ld a, [hl+]
    ld [wSfxPtr + 1], a
    ld a, [hl+]
    ld [wSfxLeft], a
    ld a, [hl]
    ld [wSfxLeft + 1], a
    pop hl
    jr SfxStart
.no:
    pop hl
    ld de, 9
    add hl, de
    dec b
    jr nz, .find
    ret                         ; unknown source: silent (documented)

SfxStart:
    ld a, 1
    ld [wSfxOn], a
    ld a, [wSndH]
    bit 2, a                    ; DMA A volume: 100 % / 50 %
    ld a, $20
    jr nz, .v
    ld a, $40
.v:
    ldh [rNR32], a
    ld a, LOW(SFX_X)
    ldh [rNR33], a
    call SndNR51
    call SfxChunk
    ld a, 256 - 16              ; 4096 Hz / 16 = 256 Hz = 8192 / 32
    ldh [rTMA], a
    ldh [rTIMA], a
    ld a, $04
    ldh [rTAC], a
    ldh a, [rIE]
    or $04
    ldh [rIE], a
    ret

SfxStop:
    ld a, [wSfxOn]
    or a
    ret z
    xor a
    ld [wSfxOn], a
    ldh [rTAC], a
    ldh a, [rIE]
    and $FB
    ldh [rIE], a
    call SndNR51
    jp Ch3Restore

; copy one 16-byte chunk into wave RAM and retrigger channel 3
SfxChunk:
    ld a, [wSfxLeft]
    ld b, a
    ld a, [wSfxLeft + 1]
    or b
    jr z, SfxStop
    ld a, [wSfxBank]
    ld [$2000], a
    ld a, [wSfxPtr]
    ld l, a
    ld a, [wSfxPtr + 1]
    ld h, a
    xor a
    ldh [rNR30], a
    ld c, LOW(WAVE)
    REPT 16
    ld a, [hl+]
    ldh [c], a
    inc c
    ENDR
.loaded::                       ; DAC still off: wave RAM readable (tests)
    ld a, $80
    ldh [rNR30], a
    ld a, $80 | HIGH(SFX_X)
    ldh [rNR34], a
    ld a, l
    ld [wSfxPtr], a
    ld a, h
    ld [wSfxPtr + 1], a
    ld a, 1
    ld [$2000], a
    ld hl, wSfxLeft
    ld a, [hl]
    sub 1
    ld [hl+], a
    ld a, [hl]
    sbc a, 0
    ld [hl], a
    ret

SfxTimerISR:
    push af
    push bc
    push de
    push hl
    call SfxChunk
    pop hl
    pop de
    pop bc
    pop af
.ret::
    reti
