; runtime/gb_snapshot.asm - boot from a RAM snapshot (SNAPSHOT define, tools/hal/snapshot.py).
; The build reserves the snapshot space; tools/hal/snapshot.py runs the ROM once in
; PyBoy up to the first VBlankIntrWait (the end of the program's init), and patches
; the machine state into it: CPU registers, ROM/SRAM bank, I/O registers, OAM, HRAM
; and, page by page (256 bytes, zero pages only flagged), VRAM, WRAM and SRAM banks
; 0-15. SnapRestore (first thing at boot) reinstates it and resumes in
; HAL_VBLANKINTRWAIT, so the init code never runs on the GB. Magic != $A5 (an
; unpatched build): normal boot.
DEF SNAP_PAGES EQU 32 + 32 + 16 * 32
DEF SNAP_NIO EQU 16

SECTION "snap_hdr", ROM0
SnapMagic:: db 0
SnapSP:: dw 0                    ; resume SP (AF, BC, DE, HL sit just below, in WRAM)
SnapRomBank:: db 0
SnapRamBank:: db 0
SnapLcdc:: db 0
SnapIE:: db 0
SnapIo:: ds 2 * SNAP_NIO         ; (register low byte, value), $00 terminated
SnapOam:: ds 160
SnapHram:: ds 127                ; $FF80-$FFFE
SnapFlags:: ds SNAP_PAGES        ; 1 = page stored in the data stream, 0 = zero page
SnapBanks:: db BANK(SnapData0), BANK(SnapData1), BANK(SnapData2), BANK(SnapData3), BANK(SnapData4)
    db BANK(SnapData5), BANK(SnapData6), BANK(SnapData7), BANK(SnapData8)
; regions in stream order: (destination page, SRAM bank or $FF, pages)
SnapRegions:
    db $80, $FF, 32
    db $C0, $FF, 32
FOR SB, 16
    db $A0, SB, 32
ENDR
    db 0

FOR SK, 9
SECTION "snap_data_{d:SK}", ROMX
SnapData{d:SK}:: ds $4000
ENDR

; HRAM scratch while restoring (the stack is at $FFF0; HRAM itself is restored last)
DEF hRegLo EQU $FFF2
DEF hRegHi EQU $FFF3
DEF hSnapK EQU $FFF4
DEF hPages EQU $FFF5
DEF hFlagLo EQU $FFF6
DEF hFlagHi EQU $FFF7
DEF hDest EQU $FFF8

SECTION "snap_code", ROM0
SnapRestore::
    ld a, [SnapMagic]
    cp $A5
    ret nz
    ldh a, [rLCDC]
    bit 7, a
    jr z, .off
.wv:
    ldh a, [rLY]
    cp 144
    jr c, .wv
    xor a
    ldh [rLCDC], a
.off:
    ld sp, $FFF0
    ld a, $0A
    ld [$0000], a                 ; SRAM enable
    xor a
    ldh [hSnapK], a
    ld a, [SnapBanks]
    ld [$2000], a
    ld a, LOW(SnapRegions)
    ldh [hRegLo], a
    ld a, HIGH(SnapRegions)
    ldh [hRegHi], a
    ld a, LOW(SnapFlags)
    ldh [hFlagLo], a
    ld a, HIGH(SnapFlags)
    ldh [hFlagHi], a
    ld de, $4000                  ; data stream (ROMX)
.region:
    ldh a, [hRegLo]
    ld l, a
    ldh a, [hRegHi]
    ld h, a
    ld a, [hl+]
    or a
    jp z, .tail
    ldh [hDest], a
    ld a, [hl+]
    cp $FF
    jr z, .nb
    ld [$4000], a                 ; SRAM bank
.nb:
    ld a, [hl+]
    ldh [hPages], a
    ld a, l
    ldh [hRegLo], a
    ld a, h
    ldh [hRegHi], a
.page:
    ldh a, [hFlagLo]
    ld l, a
    ldh a, [hFlagHi]
    ld h, a
    ld a, [hl+]
    ld b, a
    ld a, l
    ldh [hFlagLo], a
    ld a, h
    ldh [hFlagHi], a
    ldh a, [hDest]
    ld h, a
    inc a
    ldh [hDest], a
    ld l, 0
    ld a, b
    or a
    jp z, .zero
.copy:
REPT 16
    ld a, [de]
    ld [hl+], a
    inc e
ENDR
    jr nz, .copy
    inc d
    ld a, d
    cp $80
    jp nz, .next
    ldh a, [hSnapK]
    inc a
    ldh [hSnapK], a
    ld c, a
    ld b, 0
    ld hl, SnapBanks
    add hl, bc
    ld a, [hl]
    ld [$2000], a
    ld d, $40
    jp .next
.zero:
    xor a
    ld c, 16
.z:
REPT 16
    ld [hl+], a
ENDR
    dec c
    jr nz, .z
.next:
    ldh a, [hPages]
    dec a
    ldh [hPages], a
    jp nz, .page
    jp .region
.tail:
    ld hl, SnapOam
    ld de, $FE00
    ld b, 160
.oam:
    ld a, [hl+]
    ld [de], a
    inc e
    dec b
    jr nz, .oam
    ld hl, SnapIo
.io:
    ld a, [hl+]
    or a
    jr z, .iodone
    ld c, a
    ld a, [hl+]
    ldh [c], a
    jr .io
.iodone:
    ld a, [SnapRamBank]
    ld [$4000], a
    ld a, [SnapRomBank]
    ld [$2000], a
    xor a
    ldh [rIF], a
    ld a, [SnapIE]
    ldh [rIE], a
    ld a, [SnapSP]
    sub 8
    ld e, a
    ld a, [SnapSP + 1]
    sbc 0
    ld d, a                       ; de = SP - 8 (AF, BC, DE, HL stored there)
    ld hl, SnapHram
    ld c, $80
.hr:
    ld a, [hl+]
    ldh [c], a
    inc c
    ld a, c
    cp $FF
    jr nz, .hr
    ld h, d
    ld l, e
    ld sp, hl
    ld a, [SnapLcdc]
    ldh [rLCDC], a
    pop af
    pop bc
    pop de
    pop hl
    ei
    jp HAL_VBLANKINTRWAIT
