; runtime/ports/pico8gba_dmg.asm - native DMG implementation of the small "PICO-8 on GBA"
; platform layer used by PICO-8 conversions such as JeffRuLz's Celeste Classic GBA
; (pico8.h: spr / pal / camera / update_screen). docs/homebrew_port.md.
;
; The game's own versions build a GBA OAM buffer, change palette RAM and copy the OAM
; with CpuFastSet; here they are replaced (lifter overrides, `call NAT_p8_*`) by direct
; writes to a double-buffered GB shadow OAM ($D400 / $D000, DMA page swapped by
; update_screen) and by DMG palette registers computed from a 16-colour remap table.
; Tiles are prebaked at build time (tools/ports/pico8gba.py -> p8_tiles.inc):
; 4bpp colour c -> 2bpp index P8Idx[c]; BGP/OBP0/OBP1 give every index the shade of the
; colour its representative (P8Rep) is currently remapped to.
;
; Screen: the 128x128 PICO-8 view sits at GB (16, 8); the room is GB BG map cells
; (0..15, 0..15) written by the HAL from the game's BG map (PORT_BGMAP), scrolled by the
; camera (screen shake).
INCLUDE "hram.inc"
INCLUDE "p8_tiles.inc"

DEF P8_VIEW_X EQU 16
DEF P8_VIEW_Y EQU 8

SECTION "p8_state", WRAMX[$D500]
wP8N:: ds 1          ; sprites in the back page
wP8Back:: ds 1       ; back page (high byte)
wP8CamX:: ds 2       ; camera() argument (pixels)
wP8CamY:: ds 2
wP8Bgp:: ds 1        ; palette registers latched by update_screen, applied in VBlank
wP8Obp0:: ds 1
wP8Obp1:: ds 1
wP8Flips:: ds 1      ; update_screen calls (effective frames)
wP8FlipsHi:: ds 1
wP8Tmp: ds 2
SECTION "p8_maps", WRAMX[$D600]
wP8MapBg:: ds 16     ; pal() remap tables: colour -> colour
wP8MapSpr:: ds 16
wP8MapPl:: ds 16

SECTION "p8_rom0", ROM0
; ---------------------------------------------------------------- init (LCD off)
PortInit::
    ld a, BANK(P8ObjTiles)
    ld [$2000], a
    ld hl, P8ObjTiles
    ld de, $8000
    ld bc, P8_NOBJ * 16
    call P8Copy
    ld hl, P8ObjTiles               ; BG tiles 0-127 at $9000 (128-255 share $8800)
    ld de, $9000
    ld bc, 128 * 16
    call P8Copy
    ld a, 1
    ld [$2000], a
    ld a, $D4
    ld [wP8Back], a
    xor a
    ld [wP8N], a
    ld hl, wP8CamX
    ld [hl+], a
    ld [hl+], a
    ld [hl+], a
    ld [hl], a
    ld c, 7                         ; all three layers
    call P8Reset
    jp P8Regs

P8Copy:
    ld a, [hl+]
    ld [de], a
    inc de
    dec bc
    ld a, b
    or c
    jr nz, P8Copy
    ret

; c = layer mask (bit0 BG, bit1 sprites, bit2 player): identity remap
P8Reset:
    ld hl, wP8MapBg
    ld b, 0
.l:
    ld a, b
    and 15
    bit 0, c
    jr z, .s0
    ld [hl], a
.s0:
    push hl
    ld de, 16
    add hl, de
    bit 1, c
    jr z, .s1
    ld [hl], a
.s1:
    add hl, de
    bit 2, c
    jr z, .s2
    ld [hl], a
.s2:
    pop hl
    inc hl
    inc b
    ld a, b
    cp 16
    jr nz, .l
    ret

; palette registers from the remap tables
P8Regs:
    ld a, [wP8MapBg]                ; index 0 = colour 0 (backdrop)
    call P8Shade
    ld [wP8Tmp], a
    ld hl, wP8MapBg
    call P8Three
    ld [wP8Bgp], a
    xor a
    ld [wP8Tmp], a
    ld hl, wP8MapSpr
    call P8Three
    ld [wP8Obp0], a
    ld hl, wP8MapPl
    call P8Three
    ld [wP8Obp1], a
    ret

; hl = remap table, [wP8Tmp] = shade of index 0 -> a = s0 | s1 << 2 | s2 << 4 | s3 << 6, where
; s_k is the shade of the colour that index k's representative P8Rep[k-1] maps to
P8Three:
    ld b, 0
    ld de, P8Rep + 2
    ld c, 3
.l:
    ld a, [de]
    push hl
    add a, l
    ld l, a
    jr nc, .n
    inc h
.n:
    ld a, [hl]
    pop hl
    call P8Shade
    sla b
    sla b
    or b
    ld b, a
    dec de
    dec c
    jr nz, .l
    ld a, b
    add a, a
    add a, a
    ld hl, wP8Tmp
    or [hl]
    ret

; a = PICO-8 colour -> a = DMG shade (preserves hl, de, bc)
P8Shade:
    push hl
    and 15
    ld hl, P8ShadeTab
    add a, l
    ld l, a
    jr nc, .n
    inc h
.n:
    ld a, [hl]
    pop hl
    ret

; VBlank (called by the HAL ISR in PORT_OAM mode): latched palette registers
PortVBlank::
    ld a, [wP8Bgp]
    ldh [$FF47], a
    ld a, [wP8Obp0]
    ldh [$FF48], a
    ld a, [wP8Obp1]
    ldh [$FF49], a
    ret

; ---------------------------------------------------------------- camera(s16 x, s16 y)
NAT_p8_camera::
    ldh a, [HR_R0]
    ld [wP8CamX], a
    ldh a, [HR_R0 + 1]
    ld [wP8CamX + 1], a
    ldh a, [HR_R1]
    ld [wP8CamY], a
    ldh a, [HR_R1 + 1]
    ld [wP8CamY + 1], a
    ret

; ---------------------------------------------------------------- pal(u8 c0, u8 c1, u8 p)
; p: bit0 BG, bit1 sprites, bit2 player (text / overlay layers are not separate on the
; DMG). pal(0, 0, p) resets the selected layers (p = 0: all).
NAT_p8_pal::
    ldh a, [HR_R2]
    ld c, a
    ldh a, [HR_R0]
    ld b, a
    ldh a, [HR_R1]
    or b
    jr nz, .set
    ld a, c
    or a
    jr nz, .r
    ld c, 7
.r:
    jp P8Reset
.set:
    ld a, b
    and 15
    ld hl, wP8MapBg
    add a, l
    ld l, a                         ; tables are page-aligned + 16, no carry
    ldh a, [HR_R1]
    and 15
    ld b, a
    bit 0, c
    jr z, .s0
    ld [hl], b
.s0:
    ld de, 16
    add hl, de
    bit 1, c
    jr z, .s1
    ld [hl], b
.s1:
    add hl, de
    bit 2, c
    ret z
    ld [hl], b
    ret

; ---------------------------------------------------------------- spr(n, x, y, layer, palette, flip_x, flip_y)
; R0 = n, R1 = x, R2 = y (s16), R3 = layer (unused: every object is above the room);
; ARM stack [sp] palette, [sp+4] flip_x, [sp+8] flip_y. Objects whose top-left corner
; is more than 4 pixels outside the 128x128 view are not shown (the GBA hides them
; behind its border layer; the DMG has no clipping).
NAT_p8_spr::
    ld a, [wP8N]
    cp 40
    ret nc
    ; Y = y - camY + 24, visible if 20..148
    ld hl, wP8CamY
    ldh a, [HR_R2]
    sub [hl]
    ld e, a
    inc hl
    ldh a, [HR_R2 + 1]
    sbc [hl]
    ld d, a
    ld a, e
    add a, P8_VIEW_Y + 16
    ld e, a
    jr nc, .y1
    inc d
.y1:
    ld a, d
    or a
    ret nz
    ld a, e
    cp P8_VIEW_Y + 16 - 4
    ret c
    cp P8_VIEW_Y + 16 + 125
    ret nc
    ; X = x - camX + 24
    ld hl, wP8CamX
    ldh a, [HR_R1]
    sub [hl]
    ld c, a
    inc hl
    ldh a, [HR_R1 + 1]
    sbc [hl]
    ld b, a
    ld a, c
    add a, P8_VIEW_X + 8
    ld c, a
    jr nc, .x1
    inc b
.x1:
    ld a, b
    or a
    ret nz
    ld a, c
    cp P8_VIEW_X + 8 - 4
    ret c
    cp P8_VIEW_X + 8 + 125
    ret nc
    ; slot hl = back page + 4 * n
    ld a, [wP8N]
    inc a
    ld [wP8N], a
    dec a
    add a, a
    add a, a
    ld l, a
    ld a, [wP8Back]
    ld h, a
    ld a, e
    ld [hl+], a
    ld a, c
    ld [hl+], a
    ; tile: n < 256 -> n, n >= 256 (font) -> n - 256 + P8_FONT_BASE
    ldh a, [HR_R0 + 1]
    or a
    ldh a, [HR_R0]
    jr z, .t
    add a, P8_FONT_BASE
.t:
    ld [hl+], a
    ; attributes from the ARM stack arguments
    push hl
    ldh a, [HR_SP + 1]
    and $0F
    or $C0
    ld h, a
    ldh a, [HR_SP]
    ld l, a
    ld a, [hl]                      ; palette flags
    and 6
    cp 4
    ld b, 0
    jr nz, .p
    ld b, $10                       ; PAL_PLAYER only -> OBP1
.p:
    ld de, 4
    add hl, de
    ld a, [hl]
    or a
    jr z, .fx
    set 5, b
.fx:
    add hl, de
    ld a, [hl]
    or a
    jr z, .fy
    set 6, b
.fy:
    pop hl
    ld [hl], b
    ret

; ---------------------------------------------------------------- update_screen()
; Hide the unused slots of the back page, hand it to the VBlank DMA, swap pages,
; latch scroll (camera shake) and palette registers.
NAT_p8_update_screen::
    ld a, [wP8Back]
    ld h, a
    ld a, [wP8N]
    ld b, a
    add a, a
    add a, a
    ld l, a
    ld a, 40
    sub b
    jr z, .full
    ld b, a
    xor a
.h:
    ld [hl+], a
    inc l
    inc l
    inc l
    dec b
    jr nz, .h
.full:
    xor a
    ld [wP8N], a
    ld a, [wP8Back]
    ld [wDmaPage], a
    xor $D0 ^ $D4
    ld [wP8Back], a
    ld a, 1
    ld [wDmaReady], a
    ld a, [wP8CamX]
    sub P8_VIEW_X
    ld [wScx], a
    ld a, [wP8CamY]
    sub P8_VIEW_Y
    ld [wScy], a
    ld hl, wP8Flips
    inc [hl]
    jr nz, .c
    inc hl
    inc [hl]
.c:
    jp P8Regs

; CpuFastSet(src, dst, mode): the only uses copy graphics to VRAM / OAM, which are
; prebaked (PortInit) or handled by update_screen.
NAT_p8_cpufastset::
    ret
