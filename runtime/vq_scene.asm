; Phase 3.5: DMG ROM that shows a VQ-compiled scene (tools/vq/scene_rom.py).
; Loads the codebook to $8000, rebuilds the BG map from the source-class map through
; LUT_Tile_Remap (RemapStart..RemapEnd, timed by the test), copies the precomputed
; tilemap into $9C00 with the same loop minus the lookup (CopyStart..CopyEnd, baseline),
; then pans the 160x144 window over the 240x160 scene with SCX/SCY in VBlank.
; Defines from the command line: MAP_W, MAP_H, CLASS16 (1 = 16-bit class ids).

DEF rLY   EQU $FF44
DEF rLCDC EQU $FF40
DEF rSCY  EQU $FF42
DEF rSCX  EQU $FF43
DEF rBGP  EQU $FF47
DEF hCnt  EQU $FF80
DEF hRows EQU $FF81
DEF hX    EQU $FF82
DEF hDir  EQU $FF83
DEF hFrm  EQU $FF84

SECTION "header", ROM0[$100]
    nop
    jp Start
    ds $150 - @, 0

SECTION "main", ROM0[$150]
Start:
    di
    ld sp, $E000
.wv:
    ldh a, [rLY]
    cp 144
    jr c, .wv
    xor a
    ldh [rLCDC], a                ; LCD off: VRAM free
    ld hl, Tiles
    ld de, $8000
    ld bc, TilesEnd - Tiles
.ct:
    ld a, [hl+]
    ld [de], a
    inc de
    dec bc
    ld a, b
    or c
    jr nz, .ct
    ld hl, $9800
    ld bc, $0800
.cl:
    xor a
    ld [hl+], a
    dec bc
    ld a, b
    or c
    jr nz, .cl
    ld hl, Classes
    ld de, $9800
    ld a, MAP_H
    ldh [hRows], a
    IF CLASS16 == 0
    ld b, HIGH(LUT_Tile_Remap)
    ENDC
RemapStart::
.row:
    ld a, MAP_W
    ldh [hCnt], a
.cell:
    IF CLASS16
    ld a, [hl+]                   ; class low byte
    ld c, a
    ld a, [hl+]                   ; class high byte
    add a, HIGH(LUT_Tile_Remap)
    ld b, a
    ld a, [bc]                    ; GB tile = LUT[class]
    ELSE
    ld a, [hl+]
    ld c, a
    ld a, [bc]
    ENDC
    ld [de], a
    inc de
    ldh a, [hCnt]
    dec a
    ldh [hCnt], a
    jr nz, .cell
    ld a, e
    add a, 32 - MAP_W
    ld e, a
    jr nc, .nc
    inc d
.nc:
    ldh a, [hRows]
    dec a
    ldh [hRows], a
    jr nz, .row
RemapEnd::
    ld hl, Tilemap
    ld de, $9C00
    ld a, MAP_H
    ldh [hRows], a
CopyStart::
.row2:
    ld a, MAP_W
    ldh [hCnt], a
.cell2:
    ld a, [hl+]
    ld [de], a
    inc de
    ldh a, [hCnt]
    dec a
    ldh [hCnt], a
    jr nz, .cell2
    ld a, e
    add a, 32 - MAP_W
    ld e, a
    jr nc, .nc2
    inc d
.nc2:
    ldh a, [hRows]
    dec a
    ldh [hRows], a
    jr nz, .row2
CopyEnd::
    ld a, %11100100
    ldh [rBGP], a
    xor a
    ldh [rSCX], a
    ldh [rSCY], a
    ldh [hX], a
    ldh [hFrm], a
    inc a
    ldh [hDir], a
    ld a, $91                     ; LCD on, BG on, tiles $8000, map $9800
    ldh [rLCDC], a
Main::
.w1:
    ldh a, [rLY]
    cp 144
    jr nz, .w1
    ldh a, [hFrm]                 ; pan one pixel every second frame
    inc a
    ldh [hFrm], a
    and 1
    jr nz, .w2
    ldh a, [hDir]
    ld b, a
    ldh a, [hX]
    add a, b
    ldh [hX], a
    cp MAX_X
    jr nz, .z
    ld a, -1
    ldh [hDir], a
.z:
    ldh a, [hX]
    or a
    jr nz, .s
    ld a, 1
    ldh [hDir], a
.s:
    ldh a, [hX]
    ldh [rSCX], a
    srl a
    srl a
    srl a
    cp MAX_Y + 1
    jr c, .y
    ld a, MAX_Y
.y:
    ldh [rSCY], a
.w2:
    ldh a, [rLY]
    cp 144
    jr z, .w2
    jr Main

SECTION "tiles", ROM0
Tiles:
    INCBIN "tiles.2bpp"
TilesEnd:
Classes:
    INCBIN "classes.bin"
Tilemap:
    INCBIN "tilemap.bin"

SECTION "lut", ROMX[$4000], BANK[1]
LUT_Tile_Remap::
    INCBIN "lut_tile_remap.bin"
