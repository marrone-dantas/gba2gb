; scanline_parallax (original, Phase 4.2): one BG layer, per-line SCX parallax with the
; HBlank stack-blasting ISR (runtime/hblank_mode7.asm) reading a WRAM table that the
; main thread rebuilds every frame (double buffered). Bands: lines 0-BAND1-1 scroll at
; cam/4, BAND1-BAND2-1 at cam/2, the rest at cam. The scene is a VQ-compiled CC0 scene
; (tools/mode7/scanline_parallax.py).
INCLUDE "hblank_mode7.asm"
INCLUDE "px_data.inc"             ; MAP_W, MAP_H, NTILES, SCY0, BAND1, BAND2, MAX_CAM, Tiles, Tilemap

SECTION "header", ROM0[$100]
    nop
    jp Start
    ds $150 - @, 0

SECTION "px_tables", WRAM0, ALIGN[8]
wTabA:: ds 290
    ds 256 - 290 % 256
wTabB:: ds 290
SECTION "px_vars", WRAM0
wCam:: ds 1
wDir:: ds 1
wBack:: ds 1                      ; 0: build into A, 1: into B
wHold:: ds 1
wSeen:: ds 1

SECTION "px_main", ROM0
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
    ld hl, Tilemap
    ld de, $9800
    ld c, MAP_H
.row:
    ld b, MAP_W
.cell:
    ld a, [hl+]
    ld [de], a
    inc de
    dec b
    jr nz, .cell
    ld a, e
    add a, 32 - MAP_W
    ld e, a
    jr nc, .nc
    inc d
.nc:
    dec c
    jr nz, .row
    ld a, %11100100
    ldh [rBGP], a
    xor a
    ld [wCam], a
    ld [wBack], a
    ld [wHold], a
    ld [wM7NextBank], a           ; 0 = table in WRAM
    ld [wM7Frame], a
    inc a
    ld [wDir], a
    call Build                    ; table A
    call Publish
    call M7Init
    ld a, $91
    ldh [rLCDC], a
    ei
Main::
    ld a, [wM7Frame]
    ld [wSeen], a
    ld a, [wHold]
    or a
    jr nz, .nomove
    ld a, [wDir]                  ; ping-pong camera 0..MAX_CAM
    ld b, a
    ld a, [wCam]
    add a, b
    ld [wCam], a
    cp MAX_CAM
    jr c, .lo
    ld a, -1
    ld [wDir], a
.lo:
    ld a, [wCam]
    or a
    jr nz, .nomove
    ld a, 1
    ld [wDir], a
.nomove:
    call Build
    call Publish
.wait:
    halt
    nop
    ld a, [wSeen]
    ld b, a
    ld a, [wM7Frame]
    cp b
    jr z, .wait
    jr Main

; build the back table for wCam: word i = SCY0 | SCX(i) << 8
Build:
    ld a, [wBack]
    or a
    ld hl, wTabA
    jr z, .a
    ld hl, wTabB
.a:
    ld a, [wCam]
    srl a
    srl a
    ld d, a                       ; far: cam / 4
    ld e, BAND1
    call Fill
    ld a, [wCam]
    srl a
    ld d, a                       ; middle: cam / 2
    ld e, BAND2 - BAND1
    call Fill
    ld a, [wCam]
    ld d, a                       ; near: cam
    ld e, 145 - BAND2
Fill:                             ; e words of (SCY0, d)
    ld a, SCY0
    ld [hl+], a
    ld a, d
    ld [hl+], a
    dec e
    jr nz, Fill
    ret

Publish:                          ; the next VBlank uses the table just built
    ld a, [wBack]
    or a
    ld a, LOW(wTabA)
    ld b, HIGH(wTabA)
    jr z, .a
    ld a, LOW(wTabB)
    ld b, HIGH(wTabB)
.a:
    di
    ld [wM7NextPtr], a
    ld a, b
    ld [wM7NextPtr + 1], a
    ei
    ld a, [wBack]
    xor 1
    ld [wBack], a
    ret

M7FrameWork::
    ret
