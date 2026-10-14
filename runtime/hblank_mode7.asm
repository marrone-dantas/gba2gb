; runtime/hblank_mode7.asm — per-line (SCY, SCX) raster tables driven by the LCD STAT
; mode-0 (HBlank) interrupt (Phase 4.2, docs/mode7.md).
;
; A table is 145 little-endian words in ROMX or WRAM: word i = SCY | SCX << 8 for
; screen line i (word 144 is padding). The VBlank ISR maps the bank of the next table
; (wM7NextBank, 0 = table in WRAM), applies line 0 and points the HBlank ISR at word 1;
; the HBlank ISR of line L writes the values for line L+1.
;
; Two HBlank ISRs (choose with -DM7_PINNED):
;  * default, stack blasting: save SP, SP = table pointer, POP hl, write SCY/SCX,
;    store the advanced SP back into the code (self-modifying ISR in WRAM), restore SP.
;    Needs no cooperation from the main thread.
;  * M7_PINNED: the table pointer lives in HL for the whole frame (the main thread
;    only runs `halt` while the screen is drawn and does its work in VBlank through
;    the M7FrameWork callback); 2 loads + 2 writes + reti.
;
; The including file provides: M7FrameWork (called in VBlank, may clobber all; sets
; wM7NextBank / wM7NextPtr for the next frame).

DEF rIF   EQU $FF0F
DEF rLCDC EQU $FF40
DEF rSTAT EQU $FF41
DEF rSCY  EQU $FF42
DEF rSCX  EQU $FF43
DEF rLY   EQU $FF44
DEF rBGP  EQU $FF47
DEF rIE   EQU $FFFF
DEF rROMB EQU $2000

SECTION "m7_vblank_vec", ROM0[$40]
    jp M7VBlank
SECTION "m7_stat_vec", ROM0[$48]
IF DEF(M7_PINNED)
M7Hbl::
    ld a, [hl+]                   ; 2
    ldh [rSCY], a                 ; 3
    ld a, [hl+]                   ; 2
    ldh [rSCX], a                 ; 3
M7HblRet::
    reti                          ; 4   -> 14 M + 5 M dispatch
ELSE
    jp M7HblRam                   ; 4
ENDC

SECTION "m7_state", WRAM0
wM7NextBank:: ds 1
wM7NextPtr:: ds 2
wM7Frame:: ds 1

IF !DEF(M7_PINNED)
SECTION "m7_isr_rom", ROM0
M7IsrRom:
LOAD "m7_isr_ram", WRAM0
M7HblRam::
    push af                       ; 4
    push hl                       ; 4
    ld [M7Rest + 1], sp           ; 5
M7Ptr::
    ld sp, $0000                  ; 3 (operand = table pointer, advanced below)
    pop hl                        ; 3  l = SCY, h = SCX
    ld a, l                       ; 1
    ldh [rSCY], a                 ; 3
    ld a, h                       ; 1
    ldh [rSCX], a                 ; 3
    ld [M7Ptr + 1], sp            ; 5
M7Rest::
    ld sp, $0000                  ; 3
    pop hl                        ; 3
    pop af                        ; 3
M7HblRet::
    reti                          ; 4  -> 45 M + 4 M vector jp + 5 M dispatch
ENDL
M7IsrRomEnd:
ENDC

SECTION "m7_code", ROM0
; Install: copy the ISR to WRAM, enable STAT mode-0 + VBlank interrupts.
M7Init::
IF !DEF(M7_PINNED)
    ld hl, M7IsrRom
    ld de, M7HblRam
    ld b, M7IsrRomEnd - M7IsrRom
.cp:
    ld a, [hl+]
    ld [de], a
    inc de
    dec b
    jr nz, .cp
ENDC
    ld a, $08                     ; STAT: mode-0 interrupt
    ldh [rSTAT], a
    xor a
    ldh [rIF], a
    ld a, $03                     ; VBlank + STAT
    ldh [rIE], a
    ret

; VBlank: run the frame work, map the next table, apply line 0, arm line 1.
M7VBlank:
IF !DEF(M7_PINNED)
    push af
    push bc
    push de
    push hl
ENDC
    call M7FrameWork
    ld a, [wM7NextBank]
    or a
    jr z, .ram
    ld [rROMB], a
.ram:
    ld a, [wM7NextPtr]
    ld l, a
    ld a, [wM7NextPtr + 1]
    ld h, a
    ld a, [hl+]
    ldh [rSCY], a
    ld a, [hl+]
    ldh [rSCX], a
IF DEF(M7_PINNED)
    ; HL now points at word 1 and stays pinned for the HBlank ISR
ELSE
    ld a, l
    ld [M7Ptr + 1], a
    ld a, h
    ld [M7Ptr + 2], a
ENDC
    ld a, [wM7Frame]
    inc a
    ld [wM7Frame], a
IF !DEF(M7_PINNED)
    pop hl
    pop de
    pop bc
    pop af
ENDC
    reti
