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

IF DEF(PROFILE)
; Statistical profiler (tools/ports/profile.py): an LYC interrupt every 9 lines records
; the interrupted PC and the ROMX bank into a 64-entry ring at $D700 (4 bytes each:
; pc lo, pc hi, bank, 0); wProfN ($D7FF... see below) counts samples.
SECTION "prof_vec", ROM0[$48]
    jp ProfISR
SECTION "prof_ram", WRAMX[$D700]
wProfRing:: ds 252
wProfIdx:: ds 1
SECTION "prof_code", ROM0
ProfISR:
    push af
    push hl
    push de
    ld hl, sp + 6
    ld a, [hl+]
    ld e, a
    ld d, [hl]
    ld a, [wProfIdx]
    ld l, a
    ld h, HIGH(wProfRing)
    ld [hl], e
    inc l
    ld [hl], d
    inc l
    ld a, [wRomBank]
    ld [hl+], a
    ld [hl], 0
    inc l
    ld a, l
    cp 252
    jr c, .s
    xor a
.s:
    ld [wProfIdx], a
    ldh a, [$FF45]
    add a, 9
    cp 153
    jr c, .l
    sub 153
.l:
    ldh [$FF45], a
    pop de
    pop hl
    pop af
    reti
ENDC

SECTION "entry", ROM0[$100]
    nop
    jp HalStart
    ds $150 - @, 0

SECTION "shadow_oam", WRAMX[$D000]
wShadowOAM:: ds 160
SECTION "hal_state", WRAMX[$D100]
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
wRotBase:: ds 1               ; Phase 5 B3: start object for the 40-sprite rotation
wCamX:: ds 1                  ; camera in GB pixels (follow OBJ0)
wCamY:: ds 1
wLastComposeFrame:: ds 1      ; compose at most once per GB frame (KEYINPUT)
wBg1Cnt:: ds 2                ; last BG1CNT
wBg1On:: ds 1                 ; 1 when the sparse overlay is applied
wOvN:: ds 1                   ; sparse BG1 overlay count
wOvEnt: ds 80                 ; 16 x (sbb, idx lo, idx hi, tile, saved map tile)
wCurObj: ds 1
wPinned: ds 1
wObjK: ds 1
wUsedPin: ds 1
wObjSeen: ds 1
wObjMax:: ds 1
wOvSbb: ds 1                ; objects composed: max(static count, highest dynamic store + 1)
wTileNZ: ds 256               ; OBJ tile ever had a non-zero pixel
wBgLvl:: ds 16                ; BG palette bank 0: colour index -> GB colour (0-3)
wBgRaw:: ds 16                ; BG palette bank 0: raw luminance levels (0-3)
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
wDynZero: ds 4     ; Phase 5 A1: reads through unknown pointers to unmapped space
wVaddr: ds 2
wVhalf: ds 1
wAff: ds 1                    ; current object is affine (Compose)
wAffG: ds 1
wAffTile:: ds 1               ; Phase 4.1: OBJ tile of the displayed pre-rotated frame
wAffWant:: ds 1               ; frame selected by HAL_AFFINE_SEL
wAffHave:: ds 1               ; frame shown at wAffTile
wAffCur:: ds 1                ; stream mode: frame being copied
wAffLeft:: ds 1               ; stream mode: chunks left
wAffBack:: ds 1               ; stream mode: back slot tile
wAffUsed:: ds 1               ; slot tile used by the last Compose
wAffShown:: ds 1              ; slot tile in the hardware OAM (set after the DMA)
wAffSrc:: ds 2
wAffDst:: ds 2

SECTION "hal_state2", WRAMX[$D344]
wDmaPage:: ds 1                ; PORT_OAM: shadow OAM page DMA'd by the VBlank ISR
wPalDirty:: ds 1
wComposeN:: ds 2
wRejInval:: ds 1               ; Phase P1: a tile gained opaque pixels
wAnyDirty:: ds 1               ; Phase P1: some object changed since the last compose
wLastCamX: ds 1
wLastCamY: ds 1
wOamDirty:: ds 1
wBgW:: ds 16                  ; BG tiles written (bitmap, tile shadow)
wObjW:: ds 32                 ; OBJ tiles written
wRcBank: ds 1
wRcT: ds 1
wRcOff: ds 2
wRcK: ds 1

SECTION "obj_state", WRAMX[$D800]
; Phase P1: one byte per GBA object: bit 0 live (ever stored), bit 1 dirty (changed
; since the last compose). The native SM83 stack now starts at $E000 and grows down
; to at most $D900 (B4 low-water mark: $DFE8).
wObjState:: ds 128

SECTION "gba_oam_mirror", WRAMX[$D400]
wGbaOAM:: ds 1024             ; GBA OAM 0x07000000-0x070003FF (128 objects)
; native SM83 stack: $D800-$DFFF (SP starts at $E000)

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
    ld bc, $00A0
    call MemClear                 ; shadow OAM
    ld hl, $D100
    ld bc, $0200
    call MemClear                 ; HAL state
    ld hl, $D400
    ld bc, $0400
    call MemClear                 ; GBA OAM mirror (128 objects)
    ld hl, wObjState
    ld bc, 128
    call MemClear                 ; per-object state (Phase P1)
    call AffInit                  ; pre-rotated affine frames (LCD off; stub if unused)
    xor a
    ldh [$FF26], a                ; APU off, like SOUNDCNT_X at GBA reset
    ld hl, DmaRoutine
    ld c, LOW(HRAM_DMA)
    ld b, DmaRoutineEnd - DmaRoutine
.cp:
    ld a, [hl+]
    ldh [c], a
    inc c
    dec b
    jr nz, .cp
    ld hl, wBgRaw                 ; GBA palette RAM is 0 (black = level 3) at reset
    ld b, 16
    ld a, 3
.pr:
    ld [hl+], a
    dec b
    jr nz, .pr
    call BgPalUpdate
    ld a, %11100100
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
IF DEF(PORT_OAM)
    ld a, HIGH(wShadowOAM)
    ld [wDmaPage], a
ENDC
    call GbaDataInit
    call BankInit
    call TimerInit                ; GBA timers 0/1 (gb_timer_shims.asm)
    ld a, [GbaObjCount]
    ld [wObjMax], a
    ld a, 1
    ld [wNeedCompose], a          ; the first vsync shows the initial OAM
    ldh [rIE], a                  ; VBlank interrupt only
IF DEF(PROFILE)
    ld a, $40
    ldh [rSTAT], a                ; LYC interrupt source
    ld a, 3
    ldh [rIE], a
ENDC
    ei
    ld a, BANK(KernelEntry)
    ld hl, KernelEntry
    jp FarJump

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
IF !DEF(PORT_OAM)
    ld a, HIGH(wShadowOAM)
ENDC                              ; PORT_OAM: a = source page (VBlankISR)
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
IF DEF(PORT_OAM)
    ld a, [wDmaPage]              ; port-owned OAM: double-buffered shadow pages
ENDC
    call HRAM_DMA
    ld a, [wAffUsed]
    ld [wAffShown], a             ; the back slot is free only once the OAM stopped using it
    xor a
    ld [wDmaReady], a
.nodma:
IF DEF(PORT_OAM)
    push bc
    push de
    push hl
    call PortVBlank               ; port-owned palette / OAM state (runtime/ports)
    pop hl
    pop de
    pop bc
ENDC
    call TmSync                   ; extend the 4096 Hz TIMA clock
    call AffStream                ; Phase 4.1 frame streaming (stub: ret)
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
    ld b, $81                     ; BG always on: BG0 off = flat backdrop (SetBgp)
    bit 4, a                      ; DISPCNT bit 12: OBJ
    jr z, .noobj
    set 1, b
.noobj:
    ld a, b
    ldh [rLCDC], a
    jp SetBgp

; ---------------------------------------------------------------- I/O shims
HAL_WR_DISPCNT::
    ldh a, [c]
    ld [wDispcnt], a
    inc c
    ldh a, [c]
    ld [wDispcnt + 1], a
    call Bg1Refresh
    jr LcdOn

HAL_WR_BG0HOFS::
    ldh a, [c]
    ld [wScx], a
    ret

HAL_WR_BG0VOFS::
    ldh a, [c]
    ld [wScy], a
    ret

; BG1CNT (0x0400000A): track priority/SBB and refresh the sparse overlay.
HAL_WR_BG1CNT::
    ldh a, [c]
    ld [wBg1Cnt], a
    inc c
    ldh a, [c]
    ld [wBg1Cnt + 1], a
    jp Bg1Refresh

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
HAL_KEYINPUT_END::
    ; Phase 5 B3: games without VCOUNT/vsync (GbaView != 0, e.g. Snek) still
    ; need a compose each GB frame. Compose at most once per wFrame.
    ld a, [GbaView]
    or a
    ret z
    ld a, [wOamDirty]
    or a
    ret z
    ld a, [wFrame]
    ld hl, wLastComposeFrame
    cp [hl]
    ret z
    ld [hl], a
    xor a
    ld [wOamDirty], a
    ldh a, [rLCDC]
    bit 7, a
    call z, LcdOn
    jp Compose

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
IF !DEF(PORT_OAM)
    call Compose
ENDC
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
IF !DEF(PORT_OAM)
    call Compose
ENDC
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
    ld hl, wComposeN              ; statistics: composes (lag-frame counting)
    inc [hl]
    jr nz, .cn
    inc hl
    inc [hl]
.cn:
    ld a, [wRejInval]
    or a
    call nz, RejInval
    ld a, [wPalDirty]
    or a
    call nz, Reconvert
    ld a, [GbaView]
    or a
    jr z, .full
    call CamUpdate
    ; Phase P1 (camera mode): nothing changed since the last compose -> the shadow
    ; OAM already shows this logic tick; commit it without recomposing
    ld a, [wAnyDirty]
    ld hl, wDropped
    or [hl]
    ld hl, wRotBase
    or [hl]
    jr nz, .full
    ld a, [wCamX]
    ld hl, wLastCamX
    cp [hl]
    jr nz, .full
    ld a, [wCamY]
    ld hl, wLastCamY
    cp [hl]
    ret z
.full:
    ld a, [wCamX]
    ld [wLastCamX], a
    ld a, [wCamY]
    ld [wLastCamY], a
    xor a
    ld [wAnyDirty], a
    ld [wDropped], a
    ld [wUsed], a
    ld de, wShadowOAM
    ld a, [GbaView]
    or a
    jr nz, .cam
    ; legacy order: objects 0 .. n-1
    xor a
    ld [wObjI], a
.lo:
    ld a, [wObjI]
    ld b, a
    ld a, [wObjMax]
    cp b
    jp z, .done
    ld a, b
    inc a
    ld [wObjI], a
    ld h, HIGH(wObjState)         ; Phase P1: clean object with a cached rejection
    ld l, b
    ld a, [hl]
    and 6
    cp 4
    jr z, .lo
    call CObj
    jr .lo
.cam:
    ; Phase 5 B3: pinned objects first (HUD), then the rest from wRotBase,
    ; rotating when the 40-sprite limit drops objects (flicker instead of loss)
    ld a, [GbaPinLo]
    ld [wObjI], a
.pin:
    ld a, [wObjI]
    ld b, a
    ld a, [GbaPinHi]
    cp b
    jr z, .pd
    ld a, b
    inc a
    ld [wObjI], a
    ld a, 1
    ld [wPinned], a
    ld h, HIGH(wObjState)         ; Phase P1: clean object with a cached rejection
    ld l, b
    ld a, [hl]
    and 6
    cp 4
    jr z, .pin
    call CObj
    jr .pin
.pd:
    xor a
    ld [wPinned], a
    ld [wObjK], a
    ld a, [wUsed]
    ld [wUsedPin], a
    ld a, [wRotBase]
    or a
    jr nz, .rk
    ; Phase P1: no rotation in effect -> objects 0 .. n-1 in a tight scan
    ld b, 0
.f0:
    ld a, [wObjMax]
    cp b
    jr z, .rot
    ld h, HIGH(wObjState)
    ld l, b
    ld a, [hl]
    rrca
    jr nc, .f1                    ; never stored
    and 3
    cp 2
    jr z, .f1                     ; clean + cached rejection
    ld a, [GbaPinLo]
    ld c, a
    ld a, b
    cp c
    jr c, .f2
    ld a, [GbaPinHi]
    ld c, a
    ld a, b
    cp c
    jr c, .f1                     ; pinned: already drawn
.f2:
    push bc
    call CObj
    pop bc
.f1:
    inc b
    jr .f0
.rk:
    ld a, [wObjK]
    ld b, a
    ld a, [wObjMax]
    cp b
    jr z, .rot
    ld a, b
    inc a
    ld [wObjK], a
    ; i = (wRotBase + k) mod n
    ld a, [wRotBase]
    add a, b
    ld b, a
    ld a, [wObjMax]
    ld c, a
    ld a, b
    cp c
    jr c, .im
    sub c
.im:
    ld b, a
    ld a, [GbaPinLo]
    ld c, a
    ld a, b
    cp c
    jr c, .np
    ld a, [GbaPinHi]
    ld c, a
    ld a, b
    cp c
    jr c, .rk                     ; pinned: already drawn
.np:
    ld h, HIGH(wObjState)         ; skip objects that were never stored
    ld l, b
    ld a, [hl]
    bit 0, a
    jr z, .rk
    and 6
    cp 4
    jr z, .rk                     ; Phase P1: clean object with a cached rejection
    call CObj
    jr .rk
.rot:
    ld a, [wDropped]
    or a
    jr z, .nrot
    ld a, [wObjSeen]
    ld b, a                       ; advance by the objects that got a sprite
    ld a, [wRotBase]
    add a, b
    ld b, a
    ld a, [wObjMax]
    ld c, a
    ld a, b
.mod:
    cp c
    jr c, .ms
    sub c
    jr .mod
.ms:
    ld [wRotBase], a
    jr .done0
.nrot:
    xor a
    ld [wRotBase], a
.done0:
    xor a
    ld [wObjSeen], a
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
    ld hl, wObjState              ; Phase P1: everything composed is clean now
    ld a, [wObjMax]
    or a
    jr z, .cd
    ld b, a
.cl:
    res 1, [hl]
    inc l
    dec b
    jr nz, .cl
.cd:
    ld a, 1
    ld [wDmaReady], a
    ret

RejInval:
    ld a, 1
    ld [wAnyDirty], a             ; previously rejected objects may be visible now
    xor a
    ld [wRejInval], a
    ld hl, wObjState
    ld b, 128
.l:
    res 2, [hl]
    inc l
    dec b
    jr nz, .l
    ret

; Phase P1: CObj rejected the object on its attributes alone (hidden, tile >= 256,
; never-opaque tile): cache it (state bit 2) so later composes skip it in O(1)
; until the object is stored again (dirty) or a tile gains opaque pixels.
CObjRej:
    ld a, [wCurObj]
    ld l, a
    ld h, HIGH(wObjState)
    set 2, [hl]
    ret

; one GBA object (index b) -> hardware sprites at de
CObj:
    ld a, b
    ld [wCurObj], a
    ld l, a
    ld h, 0
    add hl, hl
    add hl, hl
    add hl, hl
    ld a, h
    add a, HIGH(wGbaOAM)
    ld h, a
    ld a, [hl+]                   ; attr0 low: Y
    ld c, a
    ld a, [hl+]                   ; attr0 high
    ld b, a
    and $03
    cp $02
    jp z, CObjRej                   ; hidden
    ld a, [GbaView]
    or a
    jr z, .vis
    ; camera mode: reject objects whose tile is >= 256 or never had an opaque
    ; pixel before the camera transform (Snek clears OAM to zero: most live
    ; objects are tile 0 and used to cost ~1200 T-cycles each per compose)
    push hl
    push de
    inc hl
    inc hl
    ld a, [hl+]                   ; attr2 low: tile
    ld e, a
    ld a, [hl]
    and $03
    ld a, 0                       ; (flags kept) tile >= 256: reject
    jr nz, .rej
    ld d, a
    ld hl, wTileNZ
    add hl, de
    ld a, [hl]
.rej:
    pop de
    pop hl
    or a
    jp z, CObjRej
.vis:
    ld a, b
    and $01
    ld [wAff], a                  ; affine object (double-size is rejected at bake time)
    ld a, b
    and $C0
    ld [wShape], a
    ld a, [GbaView]
    or a
    jr z, .ylut
    call CamY                     ; Phase 5 B3: camera mode (1:1 pixels)
    jr .ydone
.ylut:
    push hl
    ld h, HIGH(YLUT_LO)
    ld l, c
    ld a, [hl]
    ld [wCy], a
    inc h
    ld a, [hl]
    ld [wCy + 1], a
    pop hl
.ydone:
    ld a, [hl+]                   ; attr1 low: X bits 0-7
    ld c, a
    ld a, [hl+]                   ; attr1 high
    ld b, a
    ld a, [wAff]
    or a
    jr z, .naff
    ld a, b
    rrca
    and $1F
    ld [wAffG], a                 ; affine group (one group supported, docs/affine.md)
    xor a                         ; no flips: the baked frame is already transformed
    jr .fl
.naff:
    ld a, b
    and $30                       ; hflip (bit 12) / vflip (bit 13)
    add a, a                      ; -> GB bits 5 / 6
.fl:
    ld [wFlags], a
    ld a, b
    and $C0
    ld [wSize], a
    ld a, [GbaView]
    or a
    jr z, .xlut
    call CamX
    jr .xdone
.xlut:
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
.xdone:
    ld a, [hl+]                   ; attr2 low: tile
    ld [wTile], a
    ld a, [GbaView]
    or a
    jr z, .tnz
    push de
    push hl
    ld a, [wTile]
    ld l, a
    ld h, 0
    ld de, wTileNZ
    add hl, de
    ld a, [hl]
    pop hl
    pop de
    or a
    jp z, CObjRej                   ; tile never had an opaque pixel: nothing to draw
.tnz:
    ld a, [hl]
    ld b, a
    and $03
    jp nz, CObjRej                  ; tile >= 256: not converted (docs/hal.md)
    ld a, b
    and $F0
    jr z, .p0
    ld a, [wFlags]
    or $10                        ; OBP1
    ld [wFlags], a
.p0:
    ld a, [wAff]
    or a
    jr z, .p1
    ld a, [wAffTile]
    ld [wTile], a
    ld [wAffUsed], a
.p1:
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
    ld a, [wAff]
    or a
    ld a, [wW]
    jr nz, .st                    ; baked frames are stored 1D
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
    ld a, [wPinned]
    or a
    jr nz, .cnt
    ld a, [wC]
    ld b, a
    ld a, [wR]
    or b
    jr nz, .cnt
    ld a, [wObjSeen]
    inc a
    ld [wObjSeen], a
.cnt:
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
    ret

Compose_END::


; ---------------------------------------------------------------- Phase 5 B3 camera
; Camera mode (GbaView = 1): GBA pixels map 1:1, the 160x144 window follows object
; GbaFollow, clamped to the 240x160 GBA screen; objects GbaPinLo..GbaPinHi-1 (HUD)
; are drawn at their GBA screen position.
CamUpdate:
    ld a, [GbaFollow]
    ld l, a
    ld h, 0
    add hl, hl
    add hl, hl
    add hl, hl
    ld a, h
    add a, HIGH(wGbaOAM)
    ld h, a
    ld a, [hl+]                   ; Y
    ld c, a
    inc hl
    ld a, [hl+]                   ; X low
    ld e, a
    ld a, [hl]
    and 1
    ld d, a                       ; d:e = X (9 bits)
    ; camX = clamp(X + 4 - 80, 0, 80)
    ld a, d
    or a
    jr z, .xl
    ld a, e
    cp 128
    jr nc, .x0                    ; X >= 384: negative
    ld a, 80
    jr .xs
.xl:
    ld a, e
    cp 76
    jr c, .x0
    sub 76
    cp 80
    jr c, .xs
    ld a, 80
    jr .xs
.x0:
    xor a
.xs:
    ld [wCamX], a
    ld [wScx], a
    ; camY = clamp(Y + 4 - 72, 0, 16)
    ld a, c
    cp 224
    jr nc, .y0
    cp 68
    jr c, .y0
    sub 68
    cp 16
    jr c, .ys
    ld a, 16
    jr .ys
.y0:
    xor a
.ys:
    ld [wCamY], a
    ld [wScy], a
    ret

; c = attr0 low (Y) -> wCy = GB sprite Y (signed 16-bit). Preserves bc, de, hl.
CamY:
    push de
    push hl
    ld l, c
    ld h, 0
    ld a, c
    cp 224
    jr c, .p
    ld h, $FF
.p:
    ld a, [wPinned]
    or a
    jr nz, .np
    ld a, [wCamY]
    cpl
    ld e, a
    ld d, $FF
    inc de
    add hl, de
.np:
    ld de, 16
    add hl, de
    ld a, l
    ld [wCy], a
    ld a, h
    ld [wCy + 1], a
    pop hl
    pop de
    ret

; b = attr1 high, c = attr1 low -> wCx = GB sprite X (signed 16-bit). Preserves bc, de, hl.
CamX:
    push de
    push hl
    ld l, c
    ld h, 0
    bit 0, b
    jr z, .p
    inc h                         ; 256..511
    ld a, c
    cp 128
    jr c, .p
    ld h, $FF                     ; >= 384: x - 512
.p:
    ld a, [wPinned]
    or a
    jr nz, .np
    ld a, [wCamX]
    cpl
    ld e, a
    ld d, $FF
    inc de
    add hl, de
.np:
    ld de, 8
    add hl, de
    ld a, l
    ld [wCx], a
    ld a, h
    ld [wCx + 1], a
    pop hl
    pop de
    ret

; ---------------------------------------------------------------- Phase 5 B3 BG1 overlay
; GBA BG1 is emulated as a sparse overlay on the GB BG map: non-zero map entries
; written to screen blocks other than BG0's are recorded (16 max); when BG1 is
; enabled and in front of BG0 (lower priority value) the entries of its screen
; block replace the BG0 tiles (the replaced tiles are saved and restored).
; Transparent BG1 pixels show the backdrop instead of BG0 (documented limit).
OvRecord:                         ; b = VRAM offset bits 8-15, wVtmp = entry
    ld a, [wVtmp]
    or a
    ret z
    ld a, b
    srl a
    srl a
    srl a
    cp 32
    ret nc
    ld [wOvSbb], a
    ld a, b
    and 7
    ld d, a
    ldh a, [HR_T1]
    srl d
    rra
    ld e, a                       ; d:e = map index 0-1023
    ld a, [wOvN]
    ld b, a
    ld hl, wOvEnt
    or a
    jr z, .append
.find:
    ld a, [wOvSbb]
    cp [hl]
    jr nz, .next
    inc hl
    ld a, [hl+]
    cp e
    jr nz, .n2
    ld a, [hl+]
    cp d
    jr nz, .n3
    ld a, [wVtmp]
    ld [hl], a
    ret
.n2:
    inc hl
.n3:
    inc hl
    inc hl
    jr .cont
.next:
    inc hl
    inc hl
    inc hl
    inc hl
    inc hl
.cont:
    dec b
    jr nz, .find
.append:
    ld a, [wOvN]
    cp 16
    ret nc
    ld c, a
    inc a
    ld [wOvN], a
    ld a, c
    ld b, a
    add a, a
    add a, a
    add a, b                      ; 5 * n
    ld hl, wOvEnt
    add a, l
    ld l, a
    jr nc, .nc
    inc h
.nc:
    ld a, [wOvSbb]
    ld [hl+], a
    ld a, e
    ld [hl+], a
    ld a, d
    ld [hl+], a
    ld a, [wVtmp]
    ld [hl+], a
    xor a
    ld [hl], a
    ret

Bg1Refresh::
    ld b, 0                       ; wanted overlay = 0 (none) or SBB + 1
    ld a, [wDispcnt + 1]
    bit 1, a                      ; BG1 enabled
    jr z, .w
    ld a, [wBg1Cnt]
    and 3
    ld c, a
    ld a, [GbaBg0Prio]
    cp c
    jr z, .w                      ; same priority: BG0 (lower index) in front
    jr c, .w
    ld a, [wBg1Cnt + 1]
    and $1F
    inc a
    ld b, a
.w:
    ld a, [wBg1On]
    cp b
    ret z
    push bc
    or a
    jr z, .apply
    ld c, a
    ld e, 0                       ; restore
    call OvWalk
.apply:
    pop bc
    ld a, b
    ld [wBg1On], a
    or a
    ret z
    ld c, b
    ld e, 1
    ; fall through
; entries with SBB + 1 == c: e = 1 apply (save BG0 tile, write overlay), 0 restore
OvWalk:
    ld a, [wOvN]
    or a
    ret z
    ld b, a
    ld hl, wOvEnt
.lp:
    ld a, [hl+]
    inc a
    cp c
    jr nz, .sk
    push bc
    push de
    ld a, [hl+]
    ld e, a
    ld a, [hl+]
    ld d, a
    push hl
    ld hl, $9800
    add hl, de
    ld d, h
    ld e, l
    pop hl
    pop bc
    push bc
    ld a, c
    or a
    jr z, .rs
    call WaitVram
    ld a, [de]
    inc hl
    ld [hl-], a
    ld a, [hl]
    ld b, a
    call WaitVram
    ld a, b
    ld [de], a
    jr .dn
.rs:
    inc hl
    ld a, [hl-]
    ld b, a
    call WaitVram
    ld a, b
    ld [de], a
.dn:
    inc hl
    inc hl
    pop de
    pop bc
    jr .nx
.sk:
    inc hl
    inc hl
    inc hl
    inc hl
.nx:
    dec b
    jr nz, .lp
    ret


; ---------------------------------------------------------------- Phase 5 B3 tile shadow
; The HAL converts 4bpp tiles to 2bpp through the palette level tables when they are
; stored, so palettes had to be loaded first. Programs without EWRAM (GbaShadow = 1)
; keep the raw 4bpp data in MBC5 SRAM (bank 14: BG tiles 0-127, bank 15: OBJ tiles
; 0-255) and every tile written is reconverted after a palette change (Snek loads
; its palettes last).
; a = SRAM bank, de = offset in the tile area, wVtmp = halfword. Preserves de.
ShadowPut:
    ld b, a
    ld a, [GbaShadow]
    or a
    ret z
    ld a, b
    ld [$4000], a
    ld a, d
    or $A0
    ld h, a
    ld l, e
    ld a, [wVtmp]
    ld [hl+], a
    ld a, [wVtmp + 1]
    ld [hl], a
    ; written-tile bitmap: t = de >> 5; BG -> wBgW, OBJ -> wObjW
    ld a, e
    swap a
    rrca
    and 7
    ld c, a
    ld a, d
    add a, a
    add a, a
    add a, a
    or c                          ; t (0-255)
    ld c, a
    ld hl, wObjW
    ld a, b
    cp 15
    jr z, .o
    ld hl, wBgW
.o:
    ld a, c
    srl a
    srl a
    srl a
    add a, l
    ld l, a
    jr nc, .n
    inc h
.n:
    ld a, c
    and 7
    ld b, a
    ld a, 1
    inc b
.sh:
    dec b
    jr z, .set
    add a, a
    jr .sh
.set:
    or [hl]
    ld [hl], a
    ret

Reconvert:
    xor a
    ld [wPalDirty], a
    ld a, [GbaShadow]
    or a
    ret z
    ld a, 14
    ld [wRcBank], a
    ld hl, wBgW
    ld b, 16
    call .kind
    ld a, 15
    ld [wRcBank], a
    ld hl, wObjW
    ld b, 32
.kind:                            ; hl = bitmap, b = bytes
    xor a
    ld [wRcT], a
.byte:
    ld a, [hl+]
    push hl
    push bc
    ld c, 8
.bit:
    rra
    push af
    push bc
    call c, .tile
    pop bc
    pop af
    push hl
    ld hl, wRcT
    inc [hl]
    pop hl
    dec c
    jr nz, .bit
    pop bc
    pop hl
    dec b
    jr nz, .byte
    ret
.tile:                            ; tile wRcT of bank wRcBank: 16 halfwords
    ld a, [wRcT]
    ld l, a
    ld h, 0
    add hl, hl
    add hl, hl
    add hl, hl
    add hl, hl
    add hl, hl                    ; t * 32
    ld a, l
    ld [wRcOff], a
    ld a, h
    ld [wRcOff + 1], a
    ld a, 16
    ld [wRcK], a
.hw:
    ld a, [wRcBank]
    ld [$4000], a
    ld a, [wRcOff + 1]
    ld d, a
    or $A0
    ld h, a
    ld a, [wRcOff]
    ld e, a
    ld l, a
    ld a, [hl+]
    ld [wVtmp], a
    ld a, [hl]
    ld [wVtmp + 1], a
    ld a, [wRcBank]
    cp 15
    jr z, .ob
    ld bc, $9000
    ld hl, wBgLvl
    jr .cv
.ob:
    ld bc, $8000
    ld hl, wObjLvl
.cv:
    call HAL_VRAM_STORE16.conv
    ld hl, wRcOff
    ld a, [hl]
    add a, 2
    ld [hl+], a
    jr nc, .nc
    inc [hl]
.nc:
    ld hl, wRcK
    dec [hl]
    jr nz, .hw
    ret

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
IF DEF(VRAM_SHADOW)
    ldh a, [HR_T1 + 2]
    or a
    jr nz, .nosh
    ldh a, [HR_T1 + 1]
    cp $80
    jr nc, .nosh
    call HAL_VSH_ADDR             ; keep the readable copy (SRAM banks 8-11)
    ld a, [wVtmp]
    ld [hl+], a
    ld a, [wVtmp + 1]
    ld [hl], a
.nosh:
ENDC
IF DEF(PORT_BGMAP)
    ; port mode: tiles are prebaked, only the displayed screen block reaches the GB map
    ldh a, [HR_T1 + 2]
    and 1
    ret nz                        ; OBJ tiles: prebaked
    ldh a, [HR_T1 + 1]
    ld b, a
    ld a, [GbaBgSbbHi]
    ld c, a
    ld a, b
    sub c
    ret c
    cp 8
    ret nc
    jp .map
ENDC
    ldh a, [HR_T1 + 2]
    and 1
    jr z, .bg
    ldh a, [HR_T1 + 1]
    cp $20
    ret nc                        ; OBJ tile >= 256
    ld d, a
    ldh a, [HR_T1]
    ld e, a
    ld a, [wVtmp]                 ; Phase 5 B3: remember tiles with opaque pixels
    ld b, a
    ld a, [wVtmp + 1]
    or b
    jr z, .z
    push de
    ld a, e
    swap a
    rrca
    and 7
    ld l, a
    ld a, d
    add a, a
    add a, a
    add a, a
    or l
    ld l, a
    ld h, 0
    ld bc, wTileNZ
    add hl, bc
    ld a, [hl]
    or a
    jr nz, .nzk
    ld [hl], 1
    ld a, 1
    ld [wRejInval], a             ; Phase P1: cached object rejections are stale
.nzk:
    pop de
.z:
    ld a, 15                      ; tile shadow: SRAM bank 15
    call ShadowPut
    ld bc, $8000
    ld hl, wObjLvl
    jr .conv
.bg:
    ldh a, [HR_T1 + 1]
    ld b, a
    ld a, [GbaBgSbbHi]            ; Phase 5 B3: the BG0 screen block wins when it
    ld c, a                       ; overlaps the character block (Snek: SBB 1 in CBB 0)
    ld a, b
    sub c
    jr c, .tile
    cp 8
    jr c, .map
.tile:
    ld a, [GbaBgCbbHi]
    ld c, a
    ld a, b
    sub c
    jp c, OvRecord
    cp $10
    jp nc, OvRecord               ; BG tile >= 128: another screen block (BG1 overlay)
    ld d, a
    ldh a, [HR_T1]
    ld e, a
    ld a, 14                      ; tile shadow: SRAM bank 14
    call ShadowPut
    ld bc, $9000
    ld hl, wBgLvl
    jr .conv
.map:
    ld a, [GbaBgSbbHi]
    ld c, a
    ld a, b
    sub c
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
    ld a, 1
    ld [wPalDirty], a             ; Phase 5 B3: reconvert shadowed tiles at the next Compose
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
    ld b, a
    ld a, [GbaView]
    or a
    ld a, b
    jr nz, .gamma
    srl a
    srl a
    srl a
    srl a
    srl a                         ; 0-3
    cpl
    and 3
    ld b, a
    jr .lvl
.gamma:                           ; Phase 5 B3 (view mode): perceptual thresholds so
    ld b, 3                       ; dark palettes keep 4 distinct DMG shades
    cp 12
    jr c, .lvl
    dec b
    cp 36
    jr c, .lvl
    dec b
    cp 72
    jr c, .lvl
    dec b
.lvl:
    ld a, d
    or a
    jr nz, .obj
    ld a, e
    cp 16
    ret nc
    ld hl, wBgRaw
    ld a, l
    add a, e
    ld l, a
    jr nc, .r2
    inc h
.r2:
    ld [hl], b
    jp BgPalUpdate
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
    jr nz, .bd
    ld b, 1                       ; opaque colours never map to transparent 0
.bd:
    ld a, [wBgRaw]                ; same level as the backdrop: shift by one shade
    cp b                          ; so sprites stay visible (3 -> 2, 1 -> 2, 2 -> 3)
    jr nz, .o
    ld b, 2
    cp 2
    jr nz, .o
    ld b, 3
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

; Backdrop (GBA BG palette entry 0 = transparent BG pixels and the screen when
; BG0 is off). GB BG colour 0 is used for GBA colour index 0 (cleared VRAM, empty
; map tiles); BGP maps it to the backdrop level L0. Opaque colours of level L are
; stored as perm(L), perm = swap(0, L0), so BGP = perm shows them as L. With BG0
; off the BG stays enabled and BGP maps every colour to L0 (uniform backdrop).
BgPalUpdate:
    ld a, [wBgRaw]
    ld d, a                       ; L0
    ld hl, wBgLvl + 1
    ld bc, wBgRaw + 1
    ld e, 15
.l:
    ld a, [bc]
    inc bc
    or a
    jr nz, .n0
    ld a, d
    jr .st
.n0:
    cp d
    jr nz, .st
    xor a
.st:
    ld [hl+], a
    dec e
    jr nz, .l
SetBgp:
    ld a, [wBgRaw]
    ld hl, BgpPerm
    ld b, a
    ld a, [wDispcnt + 1]
    bit 0, a
    jr nz, .on
    ld hl, BgpFlat
.on:
    ld a, l
    add a, b
    ld l, a
    jr nc, .h
    inc h
.h:
    ld a, [hl]
    ldh [rBGP], a
    ret
BgpPerm: db $E4, $E1, $C6, $27   ; BGP for L0 = 0..3 (swap shades 0 and L0)
BgpFlat: db $00, $55, $AA, $FF   ; BG0 off: everything = L0

INCLUDE "hal_luts.inc"
INCLUDE "gb_audio_shims.asm"
INCLUDE "gb_timer_shims.asm"

; ---------------------------------------------------------------------------
; Phase 5 A1: run-time address-space dispatch for pointers whose provenance is
; unknown at compile time (docs/hal.md, "Pointer provenance").
SECTION "hal_dyn", ROM0
; T1 = ARM address -> hl = GB address of its bytes for a load:
;   $08/$09xxxxxx -> ARM image in ROM0 ($2000 | addr & $1FFF)
;   $02/$03xxxxxx -> ARM RAM window ($C000 | addr & $0FFF)
;   anything else -> wDynZero (reads as 0)
HAL_DYN_ADDR::
    ldh a, [HR_T1 + 3]
    cp $08
    jr z, .rom
    cp $09
    jr z, .rom
    cp $03
    jr z, .ram
    cp $02
    jr z, .ew
    cp $07
    jr z, .oam
IF DEF(VRAM_SHADOW)
    cp $06
    jp z, HAL_VSH_ADDR
ENDC
    ld hl, wDynZero
    xor a
    ld [hl+], a
    ld [hl+], a
    ld [hl+], a
    ld [hl-], a
    dec hl
    dec hl
    ret
.ew:
    call HAL_EW_SETBANK
    ldh a, [HR_T1 + 1]
    and $1F
    or $A0
    jr .lo
.oam:                             ; Phase 5 B3: GBA OAM -> mirror $D400 | (addr & $3FF)
    ldh a, [HR_T1 + 1]
    and $03
    or HIGH(wGbaOAM)
    jr .lo
.rom:
IF DEF(ROM_SRAM)
    jr .ew                        ; ARM image copied to SRAM banks 0.. at boot
ELSE
    ldh a, [HR_T1 + 1]
    and $1F
    or $20
    jr .lo
ENDC
.ram:
    ldh a, [HR_T1 + 1]
    and $0F
    or $C0
.lo:
    ld h, a
    ldh a, [HR_T1]
    ld l, a
    ret

IF DEF(VRAM_SHADOW)
; GBA VRAM address T1 (offset < $8000) -> SRAM bank 8 + (offset >> 13), hl = $A000 | (offset & $1FFF)
HAL_VSH_ADDR::
    ldh a, [HR_T1 + 1]
    swap a
    rrca
    and 3
    or 8
    ld [$4000], a
    ldh a, [HR_T1 + 1]
    and $1F
    or $A0
    ld h, a
    ldh a, [HR_T1]
    ld l, a
    ret
ENDC

; Phase P1: a = GBA object index -> mark live (MarkLive) or live + dirty (MarkObj),
; extend wObjMax, request a compose. Preserves bc, de, hl.
MarkLive::
    push hl
    ld l, a
    ld h, HIGH(wObjState)
    set 0, [hl]
    jr MarkObj.max
MarkObj::
    push hl
    ld l, a
    ld h, HIGH(wObjState)
    ld a, [hl]
    or 3
    ld [hl], a
    ld a, 1
    ld [wAnyDirty], a
    ld a, l
.max:
    ld a, l
    inc a
    ld h, a
    ld a, [wObjMax]
    cp h
    jr nc, .m
    ld a, h
    ld [wObjMax], a
.m:
    ld a, 1
    ld [wOamDirty], a
    pop hl
    ret



; Phase P1 idiom -> HAL (tools/lift/idioms.py "objsetpos"): obj_set_pos(r0 = obj,
; r1 = x, r2 = y): attr0 = (attr0 & ~$FF) | (y & $FF), attr1 = (attr1 & ~$1FF) | (x & $1FF).
; Leaves r1 = x & $1FF, r2 = y & $FF, r3 = new attr1, like the Thumb body.
NAT_objsetpos::
    ldh a, [HR_R0 + 3]
    cp $07
    jr nz, .slow
    ldh a, [HR_R0]
    bit 0, a
    jr nz, .slow                  ; unaligned: exact generic path
    ld l, a
    ldh a, [HR_R0 + 1]
    and 3
    or HIGH(wGbaOAM)
    ld h, a
    ld c, 0                       ; c != 0: a byte changed
    ldh a, [HR_R2]
    cp [hl]
    jr z, .s0
    ld [hl], a                    ; attr0 low = y
    inc c
.s0:
    inc hl
    inc hl
    ldh a, [HR_R1]
    cp [hl]
    jr z, .s1
    ld [hl], a                    ; attr1 low = x
    inc c
.s1:
    inc hl
    ldh a, [HR_R1 + 1]
    and 1
    ld b, a
    ld a, [hl]
    and $FE
    or b
    cp [hl]
    jr z, .s2
    ld [hl], a                    ; attr1 high
    inc c
.s2:
    ldh [HR_R3 + 1], a
    ldh a, [HR_R1]
    ldh [HR_R3], a
    ; object index = (addr & $3FF) >> 3
    ldh a, [HR_R0 + 1]
    and 3
    ld h, a
    ldh a, [HR_R0]
    srl h
    rra
    srl h
    rra
    srl h
    rra
    inc c
    dec c
    jr z, .unch
    ; position bytes only: an object rejected on its attributes (hidden, tile; see
    ; CObjRej) stays rejected, so it needs no recompose either
    ld l, a
    ld h, HIGH(wObjState)
    bit 2, [hl]
    jr z, .chg
.unch:
    call MarkLive                 ; no recompose needed for this object
    jr .regs
.chg:
    call MarkObj
    jr .regs
.slow:
    ; attr0 through the generic dispatch
    ld c, LOW(HR_R0)
    call .t1
    call HAL_DYN_ADDR
    inc hl
    ld a, [hl]
    ldh [HR_T2 + 1], a
    ldh a, [HR_R2]
    ldh [HR_T2], a
    ld c, LOW(HR_T2)
    ld e, 2
    call HAL_DYN_STORE
    ; attr1 at r0 + 2
    ld c, LOW(HR_R0)
    call .t1
    ldh a, [HR_T1]
    add a, 2
    ldh [HR_T1], a
    ldh a, [HR_T1 + 1]
    adc a, 0
    ldh [HR_T1 + 1], a
    ldh a, [HR_T1 + 2]
    adc a, 0
    ldh [HR_T1 + 2], a
    ldh a, [HR_T1 + 3]
    adc a, 0
    ldh [HR_T1 + 3], a
    call HAL_DYN_ADDR
    push hl
    inc hl
    ld a, [hl]
    and $FE
    ld b, a
    ldh a, [HR_R1 + 1]
    and 1
    or b
    ldh [HR_T2 + 1], a
    ldh [HR_R3 + 1], a
    ldh a, [HR_R1]
    ldh [HR_T2], a
    ldh [HR_R3], a
    pop hl
    ld c, LOW(HR_T2)
    ld e, 2
    call HAL_DYN_STORE
.regs:
    xor a
    ldh [HR_R3 + 2], a
    ldh [HR_R3 + 3], a
    ldh [HR_R2 + 1], a
    ldh [HR_R2 + 2], a
    ldh [HR_R2 + 3], a
    ldh [HR_R1 + 2], a
    ldh [HR_R1 + 3], a
    ldh a, [HR_R1 + 1]
    and 1
    ldh [HR_R1 + 1], a
    ret
.t1:                              ; T1 = 4 bytes of HRAM slot c
    ldh a, [c]
    ldh [HR_T1], a
    inc c
    ldh a, [c]
    ldh [HR_T1 + 1], a
    inc c
    ldh a, [c]
    ldh [HR_T1 + 2], a
    inc c
    ldh a, [c]
    ldh [HR_T1 + 3], a
    ret

; Phase 5 A2: select the MBC5 SRAM bank of the EWRAM address T1:
; bank = (addr >> 13) & 15 (bits 13-15 from T1+1, bit 16 from T1+2). Clobbers a, b.
HAL_EW_SETBANK::
    ldh a, [HR_T1 + 2]
    and 1
    add a, a
    add a, a
    add a, a
    ld b, a
    ldh a, [HR_T1 + 1]
    swap a
    rrca
    and 7
    or b
    ld [$4000], a
    ret

; Store e bytes (1/2/4) of the HRAM slot c to ARM address T1:
;   IWRAM / EWRAM (SRAM) -> window, palette / VRAM (16/32-bit) -> HAL shims,
;   anything else ignored.
HAL_DYN_STORE::
    ldh a, [HR_T1 + 3]
    cp $02
    jr z, .ew
    cp $03
    jr z, .ram
    cp $05
    jr z, .pal
    cp $06
    jr z, .vram
    cp $07
    jr z, .oam
    ret
.oam:
    ldh a, [HR_T1 + 1]            ; object = (addr & $3FF) >> 3
    and 3
    ld h, a
    ldh a, [HR_T1]
    srl h
    rra
    srl h
    rra
    srl h
    rra
    push af                       ; object index
    ldh a, [HR_T1 + 1]
    and $03
    or HIGH(wGbaOAM)
    ld h, a
    ldh a, [HR_T1]
    ld l, a
    ld d, 0                       ; d != 0: a byte changed (Phase P1 dirty tracking)
.oc:
    ldh a, [c]
    cp [hl]
    jr z, .os
    ld [hl], a
    inc d
.os:
    inc hl
    inc c
    dec e
    jr nz, .oc
    inc d
    dec d
    jr nz, .och
    pop af
    jp MarkLive
.och:
    pop af
    jp MarkObj
.ew:
    call HAL_EW_SETBANK
    ldh a, [HR_T1 + 1]
    and $1F
    or $A0
    jr .hl
.ram:
    ldh a, [HR_T1 + 1]
    and $0F
    or $C0
.hl:
    ld h, a
    ldh a, [HR_T1]
    ld l, a
.cp:
    ldh a, [c]
    ld [hl+], a
    inc c
    dec e
    jr nz, .cp
    ret
.pal:
    ld a, e
    cp 2
    jp z, HAL_PAL_STORE16
    cp 4
    jp z, HAL_PAL_STORE32
    ret
.vram:
    ld a, e
    cp 2
    jp z, HAL_VRAM_STORE16
    cp 4
    jp z, HAL_VRAM_STORE32
    ret
