; runtime/gb_hal_shims.asm — GB hardware abstraction for transpiled GBA programs
; (Phase 2; docs/hal.md, docs/memory_map.md). Linked instead of the lockstep harness
; part of runtime.asm (which is assembled with -DHAL).
;
; Calling convention of the shims (from generated code): `c` = low byte of the HRAM
; slot holding the value (store) or receiving it (load, 4 bytes written); for
; dynamic-address shims HR_T1 holds the ARM address. All CPU registers may be
; clobbered (generated code keeps no state in CPU registers across instructions).
INCLUDE "hram.inc"

DEF rP1   EQU $FF00
DEF rIF   EQU $FF0F
DEF rLCDC EQU $FF40
DEF rSTAT EQU $FF41
DEF rSCY  EQU $FF42
DEF rSCX  EQU $FF43
DEF rLY   EQU $FF44
DEF rDMA  EQU $FF46
DEF rBGP  EQU $FF47
DEF rOBP0 EQU $FF48
DEF rOBP1 EQU $FF49
DEF rIE   EQU $FFFF
DEF HRAM_DMA EQU $FFE0
DEF MAX_GB_SPRITES EQU 40

SECTION "vec_vblank", ROM0[$40]
    jp VBlankISR

SECTION "entry", ROM0[$100]
    nop
    jp HalStart
    ds $150 - @, 0

SECTION "shadow_oam", WRAMX[$D000]
wShadowOAM:: ds 160
SECTION "gba_oam_mirror", WRAMX[$D100]
wGbaOAM:: ds 256              ; GBA OAM 0x07000000-0x070000FF (objects 0-31)
SECTION "hal_state", WRAMX[$D200]
wFrame:: ds 2                 ; VBlank counter (incremented by the ISR)
wVsync:: ds 2                 ; completed vsyncs (= GBA frame number, see HAL_VCOUNT)
wNeedCompose:: ds 1           ; a vsync completed: compose at the next vsync entry
wLastVc:: ds 1                ; last VCOUNT value returned
wDmaReady:: ds 1              ; shadow OAM ready: DMA at the next VBlank
wScx:: ds 1                   ; latched BG0HOFS / BG0VOFS (applied in VBlank)
wScy:: ds 1
wDispcnt:: ds 2
wKeys:: ds 2                  ; last KEYINPUT value built by the input shim
wDropped:: ds 1               ; hardware sprites dropped by the 40-sprite limit
wUsed:: ds 1
wBgLvl:: ds 16                ; BG palette bank 0: colour index -> GB colour (0-3)
wObjLvl:: ds 16               ; OBJ palette bank 0: colour index -> GB colour (1-3, 0 = transparent)
wObjI: ds 1
wShape: ds 1
wSize: ds 1
wCx: ds 2
wCy: ds 2
wW: ds 1
wH: ds 1
wTile: ds 1
wFlags: ds 1
wStride: ds 1
wR: ds 1
wC: ds 1
wSx: ds 1
wSy: ds 1
wVtmp: ds 2
wVaddr: ds 2
wVhalf: ds 1

SECTION "hal", ROM0
HalStart:
    di
    ld sp, $E000
    ldh a, [rLCDC]
    bit 7, a
    jr z, .off
.wv:
    ldh a, [rLY]
    cp 144
    jr c, .wv
    xor a
    ldh [rLCDC], a                ; LCD off only in VBlank
.off:
    ld hl, $8000
    ld bc, $2000
    call MemClear                 ; VRAM (LCD is off)
    ld hl, $D000
    ld bc, $0300
    call MemClear                 ; shadow OAM, GBA OAM mirror, HAL state
    ld hl, DmaRoutine
    ld c, LOW(HRAM_DMA)
    ld b, DmaRoutineEnd - DmaRoutine
.cp:
    ld a, [hl+]
    ldh [c], a
    inc c
    dec b
    jr nz, .cp
    ld a, %11100100
    ldh [rBGP], a
    ldh [rOBP0], a
    ld a, %00011011               ; OBP1: inverted shades (GBA OBJ palette banks != 0)
    ldh [rOBP1], a
    xor a
    ldh [rSCX], a
    ldh [rSCY], a
    ldh [rIF], a
    ld hl, HR_R0
    ld b, 64
.z:
    ld [hl+], a
    dec b
    jr nz, .z
    ld a, $0F                     ; ARM SP = 0x03000F00 (docs/memory_map.md)
    ldh [HR_SP + 1], a
    ld a, $03
    ldh [HR_SP + 3], a
    call GbaDataInit
    ld a, 1
    ld [wNeedCompose], a          ; the first vsync shows the initial OAM
    ldh [rIE], a                  ; VBlank interrupt only
    ei
    jp KernelEntry

MemClear:
    xor a
.clr::
    ld [hl+], a
    dec bc
    ld a, b
    or c
    jr nz, MemClear
    ret

; copied to HRAM_DMA: OAM DMA from the shadow OAM page (160 M-cycles + overhead)
DmaRoutine:
    ld a, HIGH(wShadowOAM)
    ldh [rDMA], a
    ld a, 40
.w:
    dec a
    jr nz, .w
    ret
DmaRoutineEnd:

; ---------------------------------------------------------------- VBlank ISR
VBlankISR:
    push af
    ld a, [wDmaReady]
    or a
    jr z, .nodma
.dma::
    call HRAM_DMA
    xor a
    ld [wDmaReady], a
.nodma:
    ld a, [wScx]
    ldh [rSCX], a
    ld a, [wScy]
    ldh [rSCY], a
    ld a, [wFrame]
    inc a
    ld [wFrame], a
    jr nz, .s
    ld a, [wFrame + 1]
    inc a
    ld [wFrame + 1], a
.s:
    pop af
    reti

; LCDC from the last DISPCNT: LCD on, BG0 -> BG, OBJ -> OBJ (8x8), tiles $8800 mode,
; map $9800.
LcdOn:
    ld a, [wDispcnt + 1]
    ld b, $80
    bit 0, a                      ; DISPCNT bit 8: BG0
    jr z, .nobg
    set 0, b
.nobg:
    bit 4, a                      ; DISPCNT bit 12: OBJ
    jr z, .noobj
    set 1, b
.noobj:
    ld a, b
    ldh [rLCDC], a
    ret

; ---------------------------------------------------------------- I/O shims
HAL_WR_DISPCNT::
    ldh a, [c]
    ld [wDispcnt], a
    inc c
    ldh a, [c]
    ld [wDispcnt + 1], a
    jr LcdOn

HAL_WR_BG0HOFS::
    ldh a, [c]
    ld [wScx], a
    ret

HAL_WR_BG0VOFS::
    ldh a, [c]
    ld [wScy], a
    ret

; KEYINPUT (0x04000130) from JOYP. JOYP is a select matrix: P14 low selects the
; D-pad (bit0 Right, 1 Left, 2 Up, 3 Down), P15 low the buttons (bit0 A, 1 B,
; 2 Select, 3 Start); both active low, like KEYINPUT, whose low byte is
; A B Sel Start Right Left Up Down: low byte = (dpad << 4) | buttons. The shoulder
; buttons (bits 8-9) do not exist on the GB and read as released.
HAL_KEYINPUT::
    ld a, $20                     ; P14 = 0: D-pad
    ldh [rP1], a
    ldh a, [rP1]
    ldh a, [rP1]                  ; read twice (matrix settle time)
    and $0F
    swap a
    ld b, a
    ld a, $10                     ; P15 = 0: buttons
    ldh [rP1], a
    ldh a, [rP1]
    ldh a, [rP1]
    and $0F
    or b
    ld b, a
    ld a, $30                     ; deselect
    ldh [rP1], a
    ld a, b
    ld [wKeys], a
    ldh [c], a
    inc c
    ld a, $03                     ; L, R released
    ld [wKeys + 1], a
    ldh [c], a
    inc c
    xor a
    ldh [c], a
    inc c
    ldh [c], a
    ret
HAL_KEYINPUT_END::

; VCOUNT (0x04000006): GB LY mapped to the GBA line range (VCOUNT_LUT).
; A vsync completes when a read returns >= 160 after a read < 160 (the definition
; of the GBA reference, tools/hal/gba_ref.py): wVsync is incremented. The first
; VCOUNT read after that (the next vsync entry: the frame update is done) composes
; the shadow OAM, which the VBlank ISR then DMAs.
HAL_VCOUNT::
    push bc
    ldh a, [rLCDC]
    bit 7, a
    call z, LcdOn
    ld a, [wNeedCompose]
    or a
    jr z, .nocomp
    xor a
    ld [wNeedCompose], a
    call Compose
.nocomp:
    pop bc
    ldh a, [rLY]
    ld l, a
    ld h, HIGH(VCOUNT_LUT)
    ld a, [hl]
    ld b, a
    cp 160
    jr c, .store
    ld a, [wLastVc]
    cp 160
    jr nc, .store
    call VsyncDone
.store:
    ld a, b
    ld [wLastVc], a
    ldh [c], a
    inc c
    xor a
    ldh [c], a
    inc c
    ldh [c], a
    inc c
    ldh [c], a
    ret

VsyncDone:
    ld a, 1
    ld [wNeedCompose], a
    ld a, [wVsync]
    inc a
    ld [wVsync], a
    ret nz
    ld a, [wVsync + 1]
    inc a
    ld [wVsync + 1], a
    ret

; BIOS VBlankIntrWait (swi 5): compose, then halt until the next VBlank.
HAL_VBLANKINTRWAIT::
    ldh a, [rLCDC]
    bit 7, a
    call z, LcdOn
    call Compose
    ld a, [wFrame]
    ld b, a
.w:
    halt
    ld a, [wFrame]
    cp b
    jr z, .w
    xor a
    ld [wNeedCompose], a
    jp VsyncDone

; ---------------------------------------------------------------- spatial OAM
; Converts the GBA OAM mirror (objects 0 .. GbaObjCount-1) into the shadow OAM:
;   X_gb = floor(x*2/3)+8, Y_gb = floor(y*9/10)+16 (XLUT/YLUT, with 9-bit X and
;   8-bit Y wrap-around), each GBA object split into 8x8 hardware sprites at
;   (X_gb + 8c, Y_gb + 8r); sprites entirely off-screen are skipped; GBA OAM order
;   is the priority order, at most 40 hardware sprites are kept (wDropped counts
;   the rest). Flips mirror the sub-sprite layout and set the GB flip bits; GBA
;   palette bank != 0 selects OBP1.
SizeTab:  ; (width, height) in tiles, index = shape * 4 + size
    db 1, 1, 2, 2, 4, 4, 8, 8
    db 2, 1, 4, 1, 4, 2, 8, 4
    db 1, 2, 1, 4, 2, 4, 4, 8
    db 1, 1, 1, 1, 1, 1, 1, 1      ; shape 3 (prohibited): treated as 8x8

Compose::
    xor a
    ld [wDropped], a
    ld [wUsed], a
    ld [wObjI], a
    ld de, wShadowOAM
.obj:
    ld a, [wObjI]
    ld b, a
    ld a, [GbaObjCount]
    cp b
    jp z, .done
    ld a, b
    inc a
    ld [wObjI], a
    ld a, b
    add a, a
    add a, a
    add a, a
    ld l, a
    ld h, HIGH(wGbaOAM)
    ld a, [hl+]                   ; attr0 low: Y
    ld c, a
    ld a, [hl+]                   ; attr0 high
    ld b, a
    and $03
    cp $02
    jr z, .obj                    ; hidden
    ld a, b
    and $C0
    ld [wShape], a
    push hl
    ld h, HIGH(YLUT_LO)
    ld l, c
    ld a, [hl]
    ld [wCy], a
    inc h
    ld a, [hl]
    ld [wCy + 1], a
    pop hl
    ld a, [hl+]                   ; attr1 low: X bits 0-7
    ld c, a
    ld a, [hl+]                   ; attr1 high
    ld b, a
    and $30                       ; hflip (bit 12) / vflip (bit 13)
    add a, a                      ; -> GB bits 5 / 6
    ld [wFlags], a
    ld a, b
    and $C0
    ld [wSize], a
    push hl
    ld a, b
    and 1                         ; X bit 8
    add a, HIGH(XLUT_LO)
    ld h, a
    ld l, c
    ld a, [hl]
    ld [wCx], a
    ld a, h
    add a, 2
    ld h, a
    ld a, [hl]
    ld [wCx + 1], a
    pop hl
    ld a, [hl+]                   ; attr2 low: tile
    ld [wTile], a
    ld a, [hl]
    ld b, a
    and $03
    jr nz, .obj                   ; tile >= 256: not converted (docs/hal.md)
    ld a, b
    and $F0
    jr z, .p0
    ld a, [wFlags]
    or $10                        ; OBP1
    ld [wFlags], a
.p0:
    ld a, [wShape]
    rrca
    rrca
    rrca
    rrca
    ld b, a
    ld a, [wSize]
    rlca
    rlca
    and 3
    or b
    add a, a
    ld hl, SizeTab
    add a, l
    ld l, a
    jr nc, .nc
    inc h
.nc:
    ld a, [hl+]
    ld [wW], a
    ld a, [hl]
    ld [wH], a
    ld a, [wDispcnt]
    and $40                       ; 1D mapping?
    ld a, [wW]
    jr nz, .st
    ld a, 32
.st:
    ld [wStride], a
    xor a
    ld [wR], a
.row:
    xor a
    ld [wC], a
.col:
    ld a, [wR]
    add a, a
    add a, a
    add a, a
    ld b, a
    ld a, [wCy]
    add a, b
    ld c, a
    ld a, [wCy + 1]
    adc a, 0
    jp nz, .next                  ; Y outside 0-255
    ld a, c
    cp 9
    jp c, .next
    cp 160
    jp nc, .next
    ld [wSy], a
    ld a, [wC]
    add a, a
    add a, a
    add a, a
    ld b, a
    ld a, [wCx]
    add a, b
    ld c, a
    ld a, [wCx + 1]
    adc a, 0
    jp nz, .next
    ld a, c
    or a
    jp z, .next
    cp 168
    jp nc, .next
    ld [wSx], a
    ld a, [wUsed]
    cp MAX_GB_SPRITES
    jr c, .ok
    ld a, [wDropped]
    inc a
    ld [wDropped], a
    jp .next
.ok:
    inc a
    ld [wUsed], a
    ld a, [wFlags]
    bit 6, a
    ld a, [wR]
    jr z, .nv
    ld b, a
    ld a, [wH]
    dec a
    sub b
.nv:
    ld b, a                       ; tile row
    ld a, [wStride]
    ld c, a
    xor a
    inc b
.mul:
    dec b
    jr z, .md
    add a, c
    jr .mul
.md:
    ld b, a
    ld a, [wFlags]
    bit 5, a
    ld a, [wC]
    jr z, .nh
    ld c, a
    ld a, [wW]
    dec a
    sub c
.nh:
    add a, b
    ld b, a
    ld a, [wTile]
    add a, b
    ld c, a
    ld a, [wSy]
    ld [de], a
    inc de
    ld a, [wSx]
    ld [de], a
    inc de
    ld a, c
    ld [de], a
    inc de
    ld a, [wFlags]
    ld [de], a
    inc de
.next:
    ld a, [wC]
    inc a
    ld [wC], a
    ld b, a
    ld a, [wW]
    cp b
    jp nz, .col
    ld a, [wR]
    inc a
    ld [wR], a
    ld b, a
    ld a, [wH]
    cp b
    jp nz, .row
    jp .obj
.done:
    ld a, e
    cp 160
    jr nc, .fin
    xor a
    ld [de], a                    ; Y = 0: hidden
    inc de
    inc de
    inc de
    inc de
    jr .done
.fin:
    ld a, 1
    ld [wDmaReady], a
    ret
Compose_END::

; ---------------------------------------------------------------- VRAM / palette
WaitVram:
    ldh a, [rLCDC]
    bit 7, a
    ret z                         ; LCD off: always accessible
.w:
    ldh a, [rSTAT]
    and 2                         ; mode 2/3: VRAM busy
    jr nz, .w
    ret

AddT1_2:
    ldh a, [HR_T1]
    add a, 2
    ldh [HR_T1], a
    ldh a, [HR_T1 + 1]
    adc a, 0
    ldh [HR_T1 + 1], a
    ldh a, [HR_T1 + 2]
    adc a, 0
    ldh [HR_T1 + 2], a
    ret

HAL_VRAM_STORE32::
    push bc
    call HAL_VRAM_STORE16
    call AddT1_2
    pop bc
    inc c
    inc c
    ; fall through
; 16-bit VRAM store at ARM address T1 (0x06000000-0x06017FFF):
;   OBJ tiles (0x06010000 + 32 t, t < 256) -> $8000 + 16 t   (4bpp -> 2bpp)
;   BG tiles of the compile-time CBB (t < 128) -> $9000 + 16 t
;   BG map of the compile-time SBB (32x32 entries) -> $9800 (tile number low byte)
; Everything else is ignored. 4bpp -> 2bpp: colour index -> GB colour through the
; palette level tables (luminance, 4 levels), so palettes must be loaded first.
HAL_VRAM_STORE16::
    ldh a, [c]
    ld [wVtmp], a
    inc c
    ldh a, [c]
    ld [wVtmp + 1], a
    ldh a, [HR_T1 + 2]
    and 1
    jr z, .bg
    ldh a, [HR_T1 + 1]
    cp $20
    ret nc                        ; OBJ tile >= 256
    ld d, a
    ldh a, [HR_T1]
    ld e, a
    ld bc, $8000
    ld hl, wObjLvl
    jr .conv
.bg:
    ldh a, [HR_T1 + 1]
    ld b, a
    ld a, [GbaBgCbbHi]
    ld c, a
    ld a, b
    sub c
    jr c, .map
    cp $10
    jr nc, .map                   ; BG tile >= 128
    ld d, a
    ldh a, [HR_T1]
    ld e, a
    ld bc, $9000
    ld hl, wBgLvl
    jr .conv
.map:
    ld a, [GbaBgSbbHi]
    ld c, a
    ld a, b
    sub c
    ret c
    cp 8
    ret nc
    ld d, a
    ldh a, [HR_T1]
    ld e, a
    srl d
    rr e                          ; map entry index 0-1023
    ld hl, $9800
    add hl, de
    call WaitVram
    ld a, [wVtmp]
.wrmap::                          ; VRAM write sites are exported for the access checker
    ld [hl], a
    ret
.conv:                            ; de = offset in the tile area, bc = GB base, hl = levels
    push hl
    ld a, e
    and 2
    ld [wVhalf], a
    ld h, d
    ld l, e
    srl h
    rr l
    res 0, l
    add hl, bc                    ; GB address = base + ((offset >> 1) & ~1)
    ld a, l
    ld [wVaddr], a
    ld a, h
    ld [wVaddr + 1], a
    pop hl
    ld bc, 0
    ld a, [wVtmp]
    call .nib2
    ld a, [wVtmp + 1]
    call .nib2
    ld a, [wVhalf]
    or a
    jr nz, .h1
    swap c
    swap b
    ld d, $0F                     ; first 4 pixels -> bits 7-4, keep bits 3-0
    jr .wr
.h1:
    ld d, $F0
.wr:
    ld a, [wVaddr]
    ld l, a
    ld a, [wVaddr + 1]
    ld h, a
    call WaitVram
    ld a, [hl]
    and d
    or c
.wrlo::
    ld [hl+], a
    call WaitVram
    ld a, [hl]
    and d
    or b
.wrhi::
    ld [hl], a
    ret
.nib2:
    ld d, a
    and $0F
    call .pix
    ld a, d
    swap a
    and $0F
.pix:                             ; colour index a -> shift its 2 bits into c (lo) / b (hi)
    push hl
    add a, l
    ld l, a
    jr nc, .pn
    inc h
.pn:
    ld a, [hl]
    pop hl
    rra
    rl c
    rra
    rl b
    ret

HAL_PAL_STORE32::
    push bc
    call HAL_PAL_STORE16
    call AddT1_2
    pop bc
    inc c
    inc c
; 16-bit palette store: colour index = (address & $3FF) / 2. BG bank 0 (index 0-15)
; and OBJ bank 0 (256-271) update the level tables: level = 3 - ((R + 2G + B) / 4 >> 3)
; (0 = white). Other banks are ignored (OBJ banks != 0 use the inverted OBP1).
HAL_PAL_STORE16::
    ldh a, [HR_T1 + 1]
    and 3
    ld d, a
    ldh a, [HR_T1]
    ld e, a
    srl d
    rr e
    ldh a, [c]
    ld l, a
    inc c
    ldh a, [c]
    ld h, a
    ld a, l
    and 31
    ld b, a                       ; R
    ld a, h
    rra
    rra
    and 31
    add a, b
    ld b, a                       ; R + B
    ld a, h
    and 3
    add a, a
    add a, a
    add a, a
    ld c, a
    ld a, l
    swap a
    rra
    and 7
    or c                          ; G
    add a, a
    add a, b                      ; R + 2G + B (0-124)
    srl a
    srl a
    srl a
    srl a
    srl a                         ; 0-3
    cpl
    and 3
    ld b, a
    ld a, d
    or a
    jr nz, .obj
    ld a, e
    cp 16
    ret nc
    ld hl, wBgLvl
    jr .st
.obj:
    dec a
    ret nz
    ld a, e
    cp 16
    ret nc
    or a
    jr nz, .nz
    ld b, 0
    jr .o
.nz:
    ld a, b
    or a
    jr nz, .o
    ld b, 1                       ; opaque colours never map to transparent 0
.o:
    ld hl, wObjLvl
.st:
    ld a, l
    add a, e
    ld l, a
    jr nc, .s2
    inc h
.s2:
    ld [hl], b
    ret

INCLUDE "hal_luts.inc"
