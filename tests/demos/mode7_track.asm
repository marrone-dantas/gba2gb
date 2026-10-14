; mode7_track (original, Phase 4.2): pseudo-3D race track on the DMG using per-line
; (SCY, SCX) tables (runtime/hblank_mode7.asm). One table per (camera yaw, forward
; phase): 32 yaws x 8 phases, 290 bytes each, in MBC5 banks 1+ (tools/mode7).
; D-pad left/right steers (wAngle 0-31, 16 = straight ahead); the track scrolls
; towards the camera one phase per frame.
INCLUDE "hblank_mode7.asm"
INCLUDE "m7_track_data.inc"       ; NTILES, NTABLES, Tiles, Map, AddrTab, table banks

DEF rP1 EQU $FF00

SECTION "header", ROM0[$100]
    nop
    jp Start
    ds $150 - @, 0

SECTION "track_vars", WRAM0
wAngle:: ds 1
wPhase:: ds 1
wHold:: ds 1                      ; 1 = do not advance the phase (tests)

SECTION "track_main", ROM0
Start:
    di
    ld sp, $E000
.wv:
    ldh a, [rLY]
    cp 144
    jr c, .wv
    xor a
    ldh [rLCDC], a
    ld hl, Tiles
    ld de, $8000
    ld bc, NTILES * 16
.ct:
    ld a, [hl+]
    ld [de], a
    inc de
    dec bc
    ld a, b
    or c
    jr nz, .ct
    ld hl, Map
    ld de, $9800
    ld bc, 1024
.cm:
    ld a, [hl+]
    ld [de], a
    inc de
    dec bc
    ld a, b
    or c
    jr nz, .cm
    ld a, %11100100
    ldh [rBGP], a
    ld a, 16
    ld [wAngle], a
    xor a
    ld [wPhase], a
    ld [wHold], a
    ld [wM7Frame], a
    call Select
    call M7Init
    ld a, $91                     ; LCD on, BG on, tiles $8000, map $9800
    ldh [rLCDC], a
    ei
Idle::
    halt                          ; the pinned-HL ISR needs an idle main thread
    nop
    jr Idle

M7FrameWork::
    ld a, $20                     ; select the D-pad
    ldh [rP1], a
    ldh a, [rP1]
    ldh a, [rP1]
    cpl
    and $0F
    ld b, a
    ld a, $30
    ldh [rP1], a
    ld a, [wM7Frame]
    and 3
    jr nz, .nosteer
    ld a, [wAngle]
    bit 1, b                      ; left
    jr z, .nl
    or a
    jr z, .nl
    dec a
.nl:
    bit 0, b                      ; right
    jr z, .nr
    cp 31
    jr z, .nr
    inc a
.nr:
    ld [wAngle], a
.nosteer:
    ld a, [wHold]
    or a
    jr nz, Select
    ld a, [wPhase]
    inc a
    and 7
    ld [wPhase], a
Select:                           ; table t = angle * 8 + phase -> bank / pointer
    ld a, [wAngle]
    add a, a
    add a, a
    add a, a
    ld l, a
    ld a, [wPhase]
    or l
    ld l, a
    ld h, 0                       ; hl = t
    ld d, h
    ld e, l
    add hl, hl
    add hl, de                    ; hl = 3 t
    ld de, AddrTab
    add hl, de
    ld a, [hl+]
    ld [wM7NextBank], a
    ld a, [hl+]
    ld [wM7NextPtr], a
    ld a, [hl]
    ld [wM7NextPtr + 1], a
    ret
