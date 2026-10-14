; runtime/gb_bank.asm — Phase 5 B3: far calls across MBC5 ROMX banks.
; Writing $2000 sets the low ROM bank (MBC5); ROM0 stays mapped. wRomBank shadows
; the latch. Soft-float lives in BANK[1]; the transpiled kernel occupies BANK[2],
; BANK[3], ... Calls nest through the native stack (no static return slot), so
; recursion across banks is safe.
INCLUDE "hram.inc"

; Fixed in WRAMX: $C000-$CFFF (WRAM0) is the emulated ARM memory window
; (hram.inc), and a floating WRAM0 section there is overwritten by program data.
SECTION "bank_state", WRAMX[$D3F0]
wRomBank:: ds 1

SECTION "bank_code", ROM0
BankInit::
    ld a, BANK(KernelEntry)       ; bank of the kernel entry (placed by rgblink)
    ld [wRomBank], a
    ld [$2000], a
    ret

; call FarCall with a = bank, hl = address: calls hl in bank a, then restores the
; caller's bank. Clobbers af, de (generated code keeps no state in registers).
FarCall::
    ld e, a
    ld a, [wRomBank]
    push af                       ; caller bank
    ld a, e
    ld [wRomBank], a
    ld [$2000], a
    ld de, FarRet
    push de
    jp hl
FarRet:
    pop af
    ld [wRomBank], a
    ld [$2000], a
    ret

; jp FarJump with a = bank, hl = address (no return)
FarJump::
    ld [wRomBank], a
    ld [$2000], a
    jp hl

; jp RetBank with a = bank: re-map bank a, then return (used by `ret` in the
; continuation bank of a function split across banks, tools/backend/codegen.py)
RetBank::
    ld [wRomBank], a
    ld [$2000], a
    ret
