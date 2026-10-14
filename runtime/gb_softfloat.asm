INCLUDE "hram.inc"
SECTION "sf_stubs", ROM0
NAT_dsub::
    ld a, BANK(NAT_dsub_impl)
    ld hl, NAT_dsub_impl
    jp FarCall
NAT_dadd::
    ld a, BANK(NAT_dadd_impl)
    ld hl, NAT_dadd_impl
    jp FarCall
NAT_fsub::
    ld a, BANK(NAT_fsub_impl)
    ld hl, NAT_fsub_impl
    jp FarCall
NAT_fadd::
    ld a, BANK(NAT_fadd_impl)
    ld hl, NAT_fadd_impl
    jp FarCall
NAT_dmul::
    ld a, BANK(NAT_dmul_impl)
    ld hl, NAT_dmul_impl
    jp FarCall
NAT_fmul::
    ld a, BANK(NAT_fmul_impl)
    ld hl, NAT_fmul_impl
    jp FarCall
NAT_i2d::
    ld a, BANK(NAT_i2d_impl)
    ld hl, NAT_i2d_impl
    jp FarCall
NAT_i2f::
    ; Phase P1: ROM0 fast path for |i| < 2^24 (exact, no rounding needed)
    ldh a, [HR_R0 + 3]
    ld b, a                       ; sign
    bit 7, a
    jr z, .p
    ; |i| = -i
    ldh a, [HR_R0]
    cpl
    add a, 1
    ld c, a
    ldh a, [HR_R0 + 1]
    cpl
    adc a, 0
    ld d, a
    ldh a, [HR_R0 + 2]
    cpl
    adc a, 0
    ld e, a
    ldh a, [HR_R0 + 3]
    cpl
    adc a, 0
    jr nz, .far
    jr .m
.p:
    or a
    jr nz, .far
    ldh a, [HR_R0]
    ld c, a
    ldh a, [HR_R0 + 1]
    ld d, a
    ldh a, [HR_R0 + 2]
    ld e, a
.m:                               ; e:d:c = |i| < 2^24
    ld a, e
    or d
    or c
    jr z, .z
    ld h, 150                     ; exponent of e:d:c with the leading 1 at bit 23
.bs:
    ld a, e
    or a
    jr nz, .bb
    ld e, d
    ld d, c
    ld c, 0
    ld a, h
    sub 8
    ld h, a
    jr .bs
.bb:
    bit 7, e
    jr nz, .pk
    sla c
    rl d
    rl e
    dec h
    jr .bb
.pk:
    ld a, c
    ldh [HR_R0], a
    ld a, d
    ldh [HR_R0 + 1], a
    ld a, h
    rrca                          ; exponent bit 0 -> bit 7
    and $80
    ld l, a
    ld a, e
    and $7F
    or l
    ldh [HR_R0 + 2], a
    ld a, h
    srl a
    ld l, a
    ld a, b
    and $80
    or l
    ldh [HR_R0 + 3], a
    ret
.z:
    xor a
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ldh [HR_R0 + 3], a
    ret
.far:
    ld a, BANK(NAT_i2f_impl)
    ld hl, NAT_i2f_impl
    jp FarCall
NAT_f2d::
    ld a, BANK(NAT_f2d_impl)
    ld hl, NAT_f2d_impl
    jp FarCall
NAT_d2f::
    ld a, BANK(NAT_d2f_impl)
    ld hl, NAT_d2f_impl
    jp FarCall
NAT_f2iz::
    ; Phase P1: ROM0 fast path for 1 <= |x| < 256 and |x| < 1 (no bank switch);
    ; everything else goes to the banked routine (exact)
    ldh a, [HR_R0 + 3]
    add a, a
    ld b, a
    ldh a, [HR_R0 + 2]
    rlca
    and 1
    or b                          ; biased exponent
    cp 127
    jr c, .zero
    cp 135
    jr nc, .far                   ; |x| >= 256
    ld b, a
    ld a, 150 - 16
    sub b                         ; shift - 16 (0..7)
    ld b, a
    ldh a, [HR_R0 + 2]
    or $80
    inc b
    jr .t
.l:
    srl a
.t:
    dec b
    jr nz, .l
    ld b, a                       ; |result| (8 bits)
    ldh a, [HR_R0 + 3]
    bit 7, a
    jr z, .pos
    xor a
    sub b
    ldh [HR_R0], a
    ld a, $FF
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ldh [HR_R0 + 3], a
    ret
.pos:
    ld a, b
    ldh [HR_R0], a
    xor a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ldh [HR_R0 + 3], a
    ret
.zero:
    xor a
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ldh [HR_R0 + 3], a
    ret
.far:
    ld a, BANK(NAT_f2iz_impl)
    ld hl, NAT_f2iz_impl
    jp FarCall
; Phase P1: float compares entirely in ROM0 (exact, no unpacking): NaN -> 2,
; +0 == -0, otherwise IEEE order via the sign-magnitude -> unsigned key mapping.
NAT_fcmpeq::
    call FCmpFast
    or a
    jr SetR0BoolF
NAT_fcmplt::
    call FCmpFast
    cp -1
    jr SetR0BoolF
NAT_fcmpgt::
    call FCmpFast
    cp 1
SetR0BoolF:                       ; R0 = (z ? 1 : 0)
    ld a, 0
    jr nz, .s
    inc a
.s:
    ldh [HR_R0], a
    xor a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ldh [HR_R0 + 3], a
    ret

; c if the float at HRAM slot c is a NaN (exponent 255, mantissa != 0). Keeps c.
IsNanFast:
    inc c
    inc c
    ldh a, [c]                    ; byte 2
    ld b, a
    inc c
    ldh a, [c]                    ; byte 3
    dec c
    dec c
    dec c
    add a, a
    ld d, a
    ld a, b
    rlca
    and 1
    or d
    inc a
    jr nz, .no                    ; exponent != 255
    ld a, b
    and $7F
    ld d, a
    ldh a, [c]
    or d
    inc c
    ld d, a
    ldh a, [c]
    dec c
    or d
    jr z, .no                     ; infinity
    scf
    ret
.no:
    and a
    ret

; a = -1 (R0 < R1), 0 (equal), 1 (R0 > R1), 2 (unordered)
FCmpFast:
    ld c, LOW(HR_R0)
    call IsNanFast
    jr c, .un
    ld c, LOW(HR_R1)
    call IsNanFast
    jr c, .un
    ldh a, [HR_R0 + 3]            ; both zero (any sign)?
    ld b, a
    ldh a, [HR_R1 + 3]
    or b
    and $7F
    ld b, a
    ldh a, [HR_R0 + 2]
    or b
    ld b, a
    ldh a, [HR_R1 + 2]
    or b
    ld b, a
    ldh a, [HR_R0 + 1]
    or b
    ld b, a
    ldh a, [HR_R1 + 1]
    or b
    ld b, a
    ldh a, [HR_R0]
    or b
    ld b, a
    ldh a, [HR_R1]
    or b
    ret z                         ; a = 0: equal
    ; keys: negative -> ~bits, positive -> bits | $80000000; compare high to low
    ldh a, [HR_R0 + 3]
    rlca
    sbc a, a
    ld d, a                       ; d = $FF if R0 negative
    ldh a, [HR_R1 + 3]
    rlca
    sbc a, a
    ld e, a
    ld c, 3
.byte:
    ld a, c
    add a, LOW(HR_R0)
    ld l, a
    ld h, $FF
    ld a, [hl]
    xor d
    ld b, a                       ; key byte of R0 (sign bit fixed below)
    ld a, c
    add a, LOW(HR_R1)
    ld l, a
    ld a, [hl]
    xor e
    ld l, a                       ; key byte of R1
    ld a, c
    cp 3
    jr nz, .cmp
    ld a, d                       ; positive: set the key's top bit
    cpl
    and $80
    xor b
    ld b, a
    ld a, e
    cpl
    and $80
    xor l
    ld l, a
.cmp:
    ld a, b
    cp l
    jr c, .lt
    jr nz, .gt
    dec c
    bit 7, c
    jr z, .byte
    xor a
    ret
.lt:
    ld a, -1
    ret
.gt:
    ld a, 1
    ret
.un:
    ld a, 2
    ret
; Integer division fast paths (ROM0, no bank switch): divisor 1..65535 and, for the
; signed forms, both operands in -65535..65535 except where noted -> 32/16 restoring
; division in registers (Div16Step, unrolled). Everything else goes to the generic
; bank-1 routine. Results are identical to libgcc's (tests/test_softfloat.py).
NAT_uidiv::
NAT_uidivmod::
    ldh a, [HR_R1 + 2]
    ld b, a
    ldh a, [HR_R1 + 3]
    or b
    jr nz, .far
    ldh a, [HR_R1]
    ld c, a
    ldh a, [HR_R1 + 1]
    ld b, a
    or c
    jr z, .far
    call UDiv32by16
    jp PutQR
.far:
    ld a, BANK(NAT_uidiv_impl)
    ld hl, NAT_uidiv_impl
    jp FarCall

NAT_idiv::
NAT_idivmod::
    ; divisor: |R1| < 65536, != 0
    ldh a, [HR_R1 + 3]
    ld b, a
    ldh a, [HR_R1 + 2]
    cp b
    jp nz, .far                   ; bytes 2-3 must be 0000 or FFFF
    inc a
    jr z, .dneg
    dec a
    jp nz, .far
    ldh a, [HR_R1]
    ld c, a
    ldh a, [HR_R1 + 1]
    ld b, a
    or c
    jp z, .far
    xor a
    jr .dvd
.dneg:
    ldh a, [HR_R1]
    cpl
    add a, 1
    ld c, a
    ldh a, [HR_R1 + 1]
    cpl
    adc a, 0
    ld b, a
    or c
    jp z, .far                    ; -65536
    ld a, $80
.dvd:
    ld [sfSq], a                  ; quotient sign
    ldh a, [HR_R0 + 3]
    bit 7, a
    jr z, .pos
    ; negative dividend: negate all 32 bits (INT_MIN -> generic path)
    ld hl, HR_R0
    ld a, [hl]
    cpl
    add a, 1
    ld [hl+], a
    ld a, [hl]
    cpl
    adc a, 0
    ld [hl+], a
    ld a, [hl]
    cpl
    adc a, 0
    ld [hl+], a
    ld a, [hl]
    cpl
    adc a, 0
    ld [hl], a
    bit 7, a
    jr nz, .min
    ld a, [sfSq]
    xor $80
    ld [sfSq], a
    ld a, $80
    jr .sr
.pos:
    xor a
.sr:
    ld [sfSr], a                  ; remainder sign = dividend sign
    call UDiv32by16
    ; quotient (HR_R0) and remainder (de) with signs
    ld a, [sfSq]
    or a
    call nz, NegR0
    ld a, [sfSr]
    or a
    jr z, PutR
    ld a, e
    cpl
    add a, 1
    ldh [HR_R1], a
    ld a, d
    cpl
    adc a, 0
    ldh [HR_R1 + 1], a
    ld a, $FF
    jr nc, .rh
    ld a, e
    or d
    ld a, $FF
    jr nz, .rh
    xor a
.rh:
    ldh [HR_R1 + 2], a
    ldh [HR_R1 + 3], a
    ret
.min:
    ld hl, HR_R0                  ; restore INT_MIN (negation is its own inverse)
    xor a
    ld [hl+], a
    ld [hl+], a
    ld [hl+], a
    ld [hl], $80
.far:
    ld a, BANK(NAT_idivmod_impl)
    ld hl, NAT_idivmod_impl
    jp FarCall

; quotient already in HR_R0; de = remainder -> R1 (unsigned)
PutQR:
PutR:
    ld a, e
    ldh [HR_R1], a
    ld a, d
    ldh [HR_R1 + 1], a
    xor a
    ldh [HR_R1 + 2], a
    ldh [HR_R1 + 3], a
    ret

NegR0:
    ld hl, HR_R0
    ld a, [hl]
    cpl
    add a, 1
    ld [hl+], a
    REPT 3
    ld a, [hl]
    cpl
    adc a, 0
    ld [hl+], a
    ENDR
    ret

; HR_R0 (unsigned 32) / bc (1..65535): quotient -> HR_R0, remainder -> de.
UDiv32by16:
    ld hl, 0
    ldh a, [HR_R0 + 2]
    ld e, a
    ldh a, [HR_R0 + 3]
    ld d, a
    or e
    jr z, .lo                     ; high half 0: quotient high = 0, remainder 0
    call Div16Step
    ld a, e
    ldh [HR_R0 + 2], a
    ld a, d
    ldh [HR_R0 + 3], a
.lo:
    ldh a, [HR_R0]
    ld e, a
    ldh a, [HR_R0 + 1]
    ld d, a
    call Div16Step
    ld a, e
    ldh [HR_R0], a
    ld a, d
    ldh [HR_R0 + 1], a
    ld d, h
    ld e, l
    ret

; (hl:de) / bc with hl < bc: de = quotient (16 bits), hl = remainder.
Div16Step:
    REPT 16
    sla e
    rl d
    rl l
    rl h
    jr c, .sub\@                ; 17-bit partial remainder >= divisor
    ld a, l
    sub c
    ld a, h
    sbc b
    jr c, .nx\@
.sub\@:
    ld a, l
    sub c
    ld l, a
    ld a, h
    sbc b
    ld h, a
    inc e
.nx\@:
    ENDR
    ret
NAT_lmul::
    ld a, BANK(NAT_lmul_impl)
    ld hl, NAT_lmul_impl
    jp FarCall
; runtime/gb_softfloat.asm - Phase 5 B2: native SM83 replacements for the libgcc /
; AEABI helpers used by Thumb code (docs/softfloat.md). A BL to one of them
; (tools/lift/lift.py NATIVES) becomes `call NAT_<name>`.
;
; Calling convention = AEABI on the HRAM register file: arguments in R0-R3
; (doubles in R0:R1 / R2:R3, low word first), result in R0 (R0:R1 for doubles and
; lmul, R0 = quotient / R1 = remainder for idivmod). R4-R11, SP and LR are
; preserved; R2, R3, R12, T0-T2 and the CPSR bytes may be clobbered.
;
; IEEE 754 binary32 / binary64, round to nearest even, subnormals, signed zeros,
; infinities. NaNs: a NaN operand is returned quieted (first operand first),
; invalid operations return the default NaN of libgcc (0x7FF80000_00000000 /
; 0x7FC00000) - checked against libgcc in tests/test_softfloat.py.
;
; Internal format (struct of 12 bytes): +0 sign ($00/$80), +1 class (0 zero,
; 1 finite, 2 inf, 3 nan), +2 E (signed 16-bit LE), +4 M (64-bit LE). Finite value =
; M * 2^(E-63), M normalised (bit 63 set).

DEF OS EQU 0
DEF OC EQU 1
DEF OE EQU 2
DEF OM EQU 4
DEF C_ZERO EQU 0
DEF C_FIN  EQU 1
DEF C_INF  EQU 2
DEF C_NAN  EQU 3

SECTION "sf_state", WRAMX[$D300]
sfA: ds 16
sfB: ds 16
sfP: ds 16                  ; 128-bit product / scratch
sfStk: ds 1                 ; sticky accumulator
sfI: ds 1
sfJ: ds 1
sfN: ds 1
sfMode: ds 1                ; 0 = double, 1 = float (Pack)
sfQ: ds 4                   ; division
sfR: ds 4
sfD: ds 4
sfSq: ds 1                  ; quotient sign
sfSr: ds 1                  ; remainder sign
sfLim: ds 1                 ; lmul: highest product byte kept

SECTION "sf_qsq", ROMX, BANK[1], ALIGN[8]
; quarter squares floor(n*n/4), n = 0..511: 512 low bytes then 512 high bytes
QsqLo:
FOR N, 0, 512
    db LOW((N * N) / 4)
ENDR
QsqHi:
FOR N, 0, 512
    db HIGH((N * N) / 4)
ENDR

SECTION "softfloat", ROMX, BANK[1]

; ------------------------------------------------------------------ 8x8 multiply
; de = b * c (quarter squares). Clobbers a, hl.
Mul8:
    ld a, b
    add a, c
    ld l, a
    ld a, HIGH(QsqLo)
    adc 0
    ld h, a
    ld e, [hl]
    inc h
    inc h
    ld d, [hl]
    ld a, b
    sub c
    jr nc, .p
    cpl
    inc a
.p:
    ld l, a
    ld h, HIGH(QsqLo)
    ld a, e
    sub [hl]
    ld e, a
    inc h
    inc h
    ld a, d
    sbc [hl]
    ld d, a
    ret

; ------------------------------------------------------------------ 64-bit helpers
; All take hl = address of m0 (LE 8 bytes).

; shift left by 1
Shl64:
    and a
    REPT 8
    rl [hl]
    inc hl
    ENDR
    ret

; shift right by 1, carry = bit shifted out
Shr64:
    ld de, 7
    add hl, de
    and a
    REPT 7
    rr [hl]
    dec hl
    ENDR
    rr [hl]
    ret

; z if the 8 bytes are 0. Clobbers a, b.
Zero64:
    xor a
    REPT 8
    or [hl]
    inc hl
    ENDR
    ret

; shift right by a bits, OR of the lost bits into bit 0 (sticky). Clobbers all.
ShrSticky:
    push hl
    ld [sfN], a
    xor a
    ld [sfStk], a
    ld a, [sfN]
    cp 64
    jr c, .bytes
    call Zero64             ; everything is lost
    pop hl
    ld b, a                 ; a = OR of the bytes
    xor a
    REPT 8
    ld [hl+], a
    ENDR
    ld a, b
    or a
    ret z
    ld de, -8
    add hl, de
    ld [hl], 1
    ret
.bytes:
    pop hl
.bl:
    ld a, [sfN]
    cp 8
    jr c, .bits
    sub 8
    ld [sfN], a
    ld a, [sfStk]
    or [hl]
    ld [sfStk], a
    push hl
    ld d, h
    ld e, l
    inc de
    REPT 7
    ld a, [de]
    ld [hl+], a
    inc de
    ENDR
    xor a
    ld [hl], a
    pop hl
    jr .bl
.bits:
    or a
    jr z, .done
.bt:
    push hl
    call Shr64
    pop hl
    jr nc, .nc
    ld a, 1
    ld [sfStk], a
.nc:
    ld a, [sfN]
    dec a
    ld [sfN], a
    jr nz, .bt
.done:
    ld a, [sfStk]
    or a
    ret z
    set 0, [hl]
    ret

; ------------------------------------------------------------------ struct helpers
; hl = struct. Normalise M (non-zero): shift left until bit 63 is set, E -= shift.
Normalize:
    push hl
    ld de, OM + 7
    add hl, de              ; hl = m7
.byte:
    ld a, [hl]
    or a
    jr nz, .bit
    ; shift bytes up: m7 = m6 ... m0 = 0
    push hl
    ld d, h
    ld e, l
    dec de
    REPT 7
    ld a, [de]
    ld [hl-], a
    dec de
    ENDR
    xor a
    ld [hl], a
    pop hl
    pop de                  ; struct
    push de
    ld a, -8
    call AddE
    jr .byte
.bit:
    bit 7, [hl]
    jr nz, .out
    push hl
    ld de, -7
    add hl, de
    call Shl64
    pop hl
    pop de
    push de
    ld a, -1
    call AddE
    jr .bit
.out:
    pop hl
    ret

; E(struct de) += a (signed 8-bit). Preserves hl.
AddE:
    push hl
    ld h, d
    ld l, e
    inc hl
    inc hl
    ld c, a
    rlca
    sbc a
    ld b, a                 ; sign extension of the addend
    ld a, c
    add a, [hl]
    ld [hl+], a
    ld a, b
    adc [hl]
    ld [hl], a
    pop hl
    ret

; ------------------------------------------------------------------ unpack
; hl = HRAM address of the double (8 bytes LE), de = struct
UnpackD:
    push de
    ; sign
    push hl
    ld bc, 7
    add hl, bc
    ld a, [hl]
    and $80
    ld [de], a              ; +0 sign
    ; exponent = (b7 & $7F) << 4 | b6 >> 4
    ld a, [hl-]
    and $7F
    ld b, a
    ld a, [hl]
    and $F0
    ld c, a                 ; b:c = exp << 4 (b holds bits 10..4, c bits 3..0 in high nibble)
    pop hl
    ; mantissa: m1..m7 = d0..d6 (d6 & $0F), m0 = 0
    push hl
    ld h, d
    ld l, e
    push bc
    ld bc, OM
    add hl, bc
    pop bc
    xor a
    ld [hl+], a             ; m0
    pop de                  ; de = src (HRAM)
    push de
    REPT 6
    ld a, [de]
    ld [hl+], a
    inc de
    ENDR
    ld a, [de]
    and $0F
    ld [hl], a              ; m7 (temporarily: frac bits 51..48)
    pop de
    pop de                  ; struct
    ; exponent value e = (b << 4) | (c >> 4)
    ld a, c
    swap a
    and $0F
    ld c, a
    ld a, b
    swap a
    ld h, a
    and $F0
    or c
    ld c, a                 ; low 8 bits of exp
    ld a, h
    and $0F
    ld b, a                 ; high 3 bits -> b:c = exp (11 bits)
    ; classify
    ld a, b
    cp $07
    jr nz, .notmax
    ld a, c
    cp $FF
    jr nz, .notmax
    ; inf / nan
    call FracZeroD
    ld a, C_INF
    jr z, .cls
    ld a, C_NAN
.cls:
    ld h, d
    ld l, e
    inc hl
    ld [hl], a
    ret
.notmax:
    ld a, b
    or c
    jr nz, .normal
    call FracZeroD
    jr nz, .sub
    ld h, d
    ld l, e
    inc hl
    ld [hl], C_ZERO
    ret
.sub:
    ld bc, 1                ; subnormal: exponent field 1, no hidden bit
    jr .setE
.normal:
    ; hidden bit: m7 |= $10
    ld hl, OM + 7
    add hl, de
    set 4, [hl]
.setE:
    ; E = exp - 1023 + 0 (M will be << 11 so that the hidden bit is bit 63)
    ld h, d
    ld l, e
    inc hl
    ld [hl], C_FIN
    inc hl
    ld a, c
    sub LOW(1023)
    ld [hl+], a
    ld a, b
    sbc HIGH(1023)
    ld [hl], a
    ; M <<= 3  (m1..m7 already hold the value << 8)
    ld hl, OM
    add hl, de
    push de
    push hl
    call Shl64
    pop hl
    push hl
    call Shl64
    pop hl
    push hl
    call Shl64
    pop hl
    pop hl                  ; struct
    jp Normalize

; z if the 52-bit fraction (struct de, m1..m7 before the shift) is 0
FracZeroD:
    ld hl, OM
    add hl, de
    push bc
    call Zero64
    pop bc
    ret

; hl = HRAM address of the float, de = struct
UnpackF:
    push hl
    inc hl
    inc hl
    inc hl
    ld a, [hl]
    and $80
    ld [de], a
    ld a, [hl-]
    add a, a                ; exp bits 7..1 (drops sign)
    ld b, a
    ld a, [hl]
    rlca
    and 1
    or b
    ld c, a                 ; c = exponent field
    pop hl
    ; M: m5 = b0, m6 = b1, m7 = b2 & $7F, m0..m4 = 0
    push de
    push hl
    ld hl, OM
    add hl, de
    xor a
    REPT 5
    ld [hl+], a
    ENDR
    pop de                  ; src
    ld a, [de]
    ld [hl+], a
    inc de
    ld a, [de]
    ld [hl+], a
    inc de
    ld a, [de]
    and $7F
    ld [hl], a
    pop de                  ; struct
    ld a, c
    cp $FF
    jr nz, .notmax
    call FracZeroD
    ld a, C_INF
    jr z, .cls
    ld a, C_NAN
.cls:
    ld h, d
    ld l, e
    inc hl
    ld [hl], a
    ret
.notmax:
    or a
    jr nz, .normal
    call FracZeroD
    jr nz, .sub
    ld h, d
    ld l, e
    inc hl
    ld [hl], C_ZERO
    ret
.sub:
    ld c, 1
    jr .setE
.normal:
    ld hl, OM + 7
    add hl, de
    set 7, [hl]
.setE:
    ld h, d
    ld l, e
    inc hl
    ld [hl], C_FIN
    inc hl
    ld a, c
    sub 127
    ld [hl+], a
    ld a, 0
    sbc 0
    ld [hl], a
    ld h, d
    ld l, e
    jp Normalize

; ------------------------------------------------------------------ pack
; Pack sfA (class C_FIN, normalised) to R0:R1 (sfMode 0, double) or R0 (sfMode 1, float)
PackA:
    ; emin: double -1022, float -126; if E < emin: denormalise
    ld a, [sfMode]
    or a
    ld bc, -1022
    jr z, .em
    ld bc, -126
.em:
    ; d = emin - E (16-bit)
    ld hl, sfA + OE
    ld a, c
    sub [hl]
    ld e, a
    inc hl
    ld a, b
    sbc [hl]
    ld d, a                 ; de = emin - E
    bit 7, d
    jr nz, .round           ; E > emin
    ld a, d
    or e
    jr z, .round            ; E == emin
    ; denormalise by de bits (cap at 70)
    ld a, d
    or a
    jr nz, .big
    ld a, e
    cp 70
    jr c, .shr
.big:
    ld a, 70
.shr:
    ld hl, sfA + OM
    call ShrSticky
    ld hl, sfA + OE
    ld a, [sfMode]
    or a
    ld bc, -1022
    jr z, .se
    ld bc, -126
.se:
    ld a, c
    ld [hl+], a
    ld [hl], b
.round:
    ld a, [sfMode]
    or a
    jp nz, .roundF
    ; double: lsb = bit 11 (m1.3), round = bit 10 (m1.2), sticky = m1&3 | m0
    ld a, [sfA + OM + 1]
    bit 2, a
    jr z, .encD             ; round bit 0 -> truncate
    and $0B                 ; lsb | sticky bits of m1
    ld b, a
    ld a, [sfA + OM]
    or b
    and a
    jr z, .encD             ; tie with even lsb -> truncate
    ld hl, sfA + OM + 1
    ld a, [hl]
    add a, 8
    ld [hl+], a
    REPT 6
    ld a, [hl]
    adc 0
    ld [hl+], a
    ENDR
    jr nc, .encD
    ; mantissa overflow: M = 2^63, E++
    ld [hl], $80
    ld de, sfA
    ld a, 1
    call AddE
.encD:
    ; overflow? E > 1023 -> inf
    ld hl, sfA + OE
    ld a, [hl+]
    sub LOW(1024)
    ld a, [hl]
    sbc HIGH(1024)
    bit 7, a
    jr z, .infD
    ; exponent field f = (m7.7) ? E + 1023 : 0
    ld bc, 0
    ld a, [sfA + OM + 7]
    bit 7, a
    jr z, .fD
    ld hl, sfA + OE
    ld a, [hl+]
    add a, LOW(1023)
    ld c, a
    ld a, [hl]
    adc HIGH(1023)
    ld b, a
.fD:
    ; N = M >> 11: shift M right 3 bits, bytes m1..m7 -> d0..d6
    push bc
    ld hl, sfA + OM
    call Shr64
    ld hl, sfA + OM
    call Shr64
    ld hl, sfA + OM
    call Shr64
    pop bc
    ld hl, sfA + OM + 1
    ld de, HR_R0
    REPT 6
    ld a, [hl+]
    ld [de], a
    inc de
    ENDR
    ; d6 = (n6 & $0F) | (f & $0F) << 4 ; d7 = sign | f >> 4
    ld a, [hl]
    and $0F
    ld h, a
    ld a, c
    swap a
    and $F0
    or h
    ld [de], a
    inc de
    ld a, c
    swap a
    and $0F
    ld h, a
    ld a, b
    swap a
    and $70
    or h
    ld h, a
    ld a, [sfA + OS]
    or h
    ld [de], a
    ret
.infD:
    ld a, [sfA + OS]
    ld b, a
    jp RetInfD

.roundF:
    ; float: lsb = m5.0, round = m4.7, sticky = m4&$7F | m3 | m2 | m1 | m0
    ld a, [sfA + OM + 4]
    bit 7, a
    jr z, .encF
    and $7F
    ld b, a
    ld hl, sfA + OM
    REPT 4
    ld a, [hl+]
    or b
    ld b, a
    ENDR
    ld a, [sfA + OM + 5]
    and 1
    or b
    jr z, .encF
    ld hl, sfA + OM + 5
    ld a, [hl]
    add a, 1
    ld [hl+], a
    ld a, [hl]
    adc 0
    ld [hl+], a
    ld a, [hl]
    adc 0
    ld [hl], a
    jr nc, .encF
    ld [hl], $80
    ld de, sfA
    ld a, 1
    call AddE
.encF:
    ld hl, sfA + OE
    ld a, [hl+]
    sub 128
    ld a, [hl]
    sbc 0
    bit 7, a
    jr z, .infF
    ld c, 0
    ld a, [sfA + OM + 7]
    bit 7, a
    jr z, .fF
    ld a, [sfA + OE]
    add a, 127
    ld c, a
.fF:
    ld a, [sfA + OM + 5]
    ldh [HR_R0], a
    ld a, [sfA + OM + 6]
    ldh [HR_R0 + 1], a
    ld a, c
    rrca
    and $80
    ld b, a
    ld a, [sfA + OM + 7]
    and $7F
    or b
    ldh [HR_R0 + 2], a
    ld a, c
    srl a
    ld b, a
    ld a, [sfA + OS]
    or b
    ldh [HR_R0 + 3], a
    ret
.infF:
    ld a, [sfA + OS]
    ld b, a
    jp RetInfF

; ------------------------------------------------------------------ returns
; b = sign
RetInfD:
    xor a
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ldh [HR_R0 + 3], a
    ldh [HR_R1], a
    ldh [HR_R1 + 1], a
    ld a, $F0
    ldh [HR_R1 + 2], a
    ld a, $7F
    or b
    ldh [HR_R1 + 3], a
    ret
RetZeroD:
    xor a
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ldh [HR_R0 + 3], a
    ldh [HR_R1], a
    ldh [HR_R1 + 1], a
    ldh [HR_R1 + 2], a
    ld a, b
    ldh [HR_R1 + 3], a
    ret
RetNanD:                    ; default NaN 0x7FF80000_00000000, sign in b
    xor a
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ldh [HR_R0 + 3], a
    ldh [HR_R1], a
    ldh [HR_R1 + 1], a
    ld a, $F8
    ldh [HR_R1 + 2], a
    ld a, $7F
    or b
    ldh [HR_R1 + 3], a
    ret
RetInfF:
    xor a
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ld a, $80
    ldh [HR_R0 + 2], a
    ld a, $7F
    or b
    ldh [HR_R0 + 3], a
    ret
RetZeroF:
    xor a
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ld a, b
    ldh [HR_R0 + 3], a
    ret
RetNanF:
    xor a
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ld a, $C0
    ldh [HR_R0 + 2], a
    ld a, $7F
    or b
    ldh [HR_R0 + 3], a
    ret

; copy the 8 bytes at HRAM c (low byte address) to R0:R1, quieting a NaN if a != 0
RetCopyD:
    ld de, HR_R0
    ld h, $FF
    ld l, c
    REPT 8
    ld a, [hl+]
    ld [de], a
    inc de
    ENDR
    ret
RetCopyF:
    ld de, HR_R0
    ld h, $FF
    ld l, c
    REPT 4
    ld a, [hl+]
    ld [de], a
    inc de
    ENDR
    ret

; ------------------------------------------------------------------ add / sub core
; sfA, sfB finite non-zero. Result packed according to sfMode.
AddCore:
    ; make |A| >= |B|: compare E then M
    ld hl, sfA + OE + 1
    ld de, sfB + OE + 1
    ld a, [de]
    ld b, a
    ld a, [hl]
    ; signed compare of E hi bytes
    xor $80
    ld c, a
    ld a, b
    xor $80
    cp c                    ; (B.hi) - (A.hi)
    jr c, .ordered          ; A.hi > B.hi
    jr nz, .swap
    dec hl
    dec de
    ld a, [de]
    cp [hl]
    jr c, .ordered
    jr nz, .swap
    ; equal exponents: compare mantissas from m7 down
    ld hl, sfA + OM + 7
    ld de, sfB + OM + 7
    ld b, 8
.cm:
    ld a, [de]
    cp [hl]
    jr c, .ordered
    jr nz, .swap
    dec hl
    dec de
    dec b
    jr nz, .cm
    jr .ordered
.swap:
    ld hl, sfA
    ld de, sfB
    ld b, 12
.sw:
    ld a, [de]
    ld c, [hl]
    ld [hl+], a
    ld a, c
    ld [de], a
    inc de
    dec b
    jr nz, .sw
.ordered:
    ; d = EA - EB (>= 0)
    ld a, [sfA + OE]
    ld hl, sfB + OE
    sub [hl]
    ld c, a
    ld a, [sfA + OE + 1]
    inc hl
    sbc [hl]
    or a
    jr z, .dsmall
    ld c, 70
.dsmall:
    ld a, c
    cp 70
    jr c, .dok
    ld a, 70
.dok:
    ld hl, sfB + OM
    call ShrSticky
    ; if B was shifted out completely (only a sticky bit remains), the
    ; IEEE result is A: subtracting sticky and renormalising would give A/2
    ld hl, sfB + OM
    ld a, [hl+]
    and $FE
    REPT 7
    or [hl]
    inc hl
    ENDR
    jp z, PackA
    ld a, [sfA + OS]
    ld hl, sfB + OS
    cp [hl]
    jr nz, .sub
    ; magnitude add
    ld hl, sfA + OM
    ld de, sfB + OM
    and a
    REPT 8
    ld a, [de]
    adc [hl]
    ld [hl+], a
    inc de
    ENDR
    jp nc, PackA
    ; carry: shift right 1 with sticky, set bit 63, E++
    ld hl, sfA + OM
    call Shr64
    jr nc, .ns
    ld hl, sfA + OM
    set 0, [hl]
.ns:
    ld hl, sfA + OM + 7
    set 7, [hl]
    ld de, sfA
    ld a, 1
    call AddE
    jp PackA
.sub:
    ld hl, sfA + OM
    ld de, sfB + OM
    and a
    REPT 8
    ld a, [de]
    ld b, a
    ld a, [hl]
    sbc b
    ld [hl+], a
    inc de
    ENDR
    ld hl, sfA + OM
    call Zero64
    jr z, .zero
    ld hl, sfA
    call Normalize
    jp PackA
.zero:
    ld b, 0                 ; x - x = +0 (round to nearest)
    ld a, [sfMode]
    or a
    jp z, RetZeroD
    jp RetZeroF

; ------------------------------------------------------------------ multiply core
; P = A.M * B.M (128-bit), skipping zero bytes
MulCore:
    ld hl, sfP
    xor a
    REPT 16
    ld [hl+], a
    ENDR
    ld [sfI], a
.oi:
    ld a, [sfI]
    ld hl, sfA + OM
    add a, l
    ld l, a
    ld a, [hl]
    or a
    jr z, .ni
    ld b, a
    xor a
    ld [sfJ], a
.oj:
    ld a, [sfJ]
    ld hl, sfB + OM
    add a, l
    ld l, a
    ld a, [hl]
    or a
    jr z, .nj
    ld c, a
    push bc
    call Mul8               ; de = b * c
    pop bc
    ; P[i + j] += de, propagate carry
    ld a, [sfI]
    ld hl, sfJ
    add a, [hl]
    ld hl, sfP
    add a, l
    ld l, a
    ld a, [hl]
    add a, e
    ld [hl+], a
    ld a, [hl]
    adc d
    ld [hl+], a
    jr nc, .nj
.cy:
    ld a, [hl]
    adc 0
    ld [hl+], a
    jr c, .cy
.nj:
    ld a, [sfJ]
    inc a
    ld [sfJ], a
    cp 8
    jr nz, .oj
.ni:
    ld a, [sfI]
    inc a
    ld [sfI], a
    cp 8
    jr nz, .oi
    ret

; A = A * B (finite non-zero), then PackA
MulFin:
    call MulCore
    ; E = EA + EB + 1
    ld hl, sfA + OE
    ld a, [sfB + OE]
    add a, [hl]
    ld c, a
    inc hl
    ld a, [sfB + OE + 1]
    adc [hl]
    ld b, a
    inc bc
    ld a, b
    ld [hl-], a
    ld [hl], c
    ld a, [sfA + OS]
    ld hl, sfB + OS
    xor [hl]
    ld [sfA + OS], a
    ; if P bit 127 clear: P <<= 1, E--
    ld a, [sfP + 15]
    bit 7, a
    jr nz, .top
    ld hl, sfP
    call Shl64
    ld hl, sfP + 8
    rl [hl]                 ; continue the 128-bit shift (carry from the low half)
    REPT 7
    inc hl
    rl [hl]
    ENDR
    ld de, sfA
    ld a, -1
    call AddE
.top:
    ; M = P[8..15], sticky = OR(P[0..7])
    ld hl, sfP
    call Zero64
    ld b, a
    ld hl, sfP + 8
    ld de, sfA + OM
    REPT 8
    ld a, [hl+]
    ld [de], a
    inc de
    ENDR
    ld a, b
    or a
    jp z, PackA
    ld hl, sfA + OM
    set 0, [hl]
    jp PackA

; ------------------------------------------------------------------ entry points
; NaN handling for binary ops: a = class A, uses sfA/sfB classes.
; Returns nc if no NaN; else result already written, c set.
NanBinD:
    ld a, [sfA + OC]
    cp C_NAN
    jr z, QuietAD
    ld a, [sfB + OC]
    cp C_NAN
    jr z, QuietBD
    and a
    ret
QuietAD:
    ld c, LOW(HR_R0)
    jr QuietD
QuietBD:
    ld c, LOW(HR_R2)
QuietD:
    call RetCopyD
    ld hl, HR_R1 + 2
    set 3, [hl]             ; quiet bit 51
    scf
    ret
NanBinF:
    ld a, [sfA + OC]
    cp C_NAN
    jr z, QuietAF
    ld a, [sfB + OC]
    cp C_NAN
    jr z, QuietBF
    and a
    ret
QuietAF:
    ld c, LOW(HR_R0)
    jr QuietF
QuietBF:
    ld c, LOW(HR_R1)
QuietF:
    call RetCopyF
    ld hl, HR_R0 + 2
    set 6, [hl]             ; quiet bit 22
    scf
    ret

NAT_dsub_impl::
    ld hl, HR_R3 + 3
    ld a, [hl]
    xor $80
    ld [hl], a
NAT_dadd_impl::
    xor a
    ld [sfMode], a
    ld hl, HR_R0
    ld de, sfA
    call UnpackD
    ld hl, HR_R2
    ld de, sfB
    call UnpackD
    call InfNan
    jp z, RetNanD
    call NanBinD
    ret c
    call AddSpecial
    ret c
    jp AddCore

NAT_fsub_impl::
    ld hl, HR_R1 + 3
    ld a, [hl]
    xor $80
    ld [hl], a
NAT_fadd_impl::
    ld a, 1
    ld [sfMode], a
    ld hl, HR_R0
    ld de, sfA
    call UnpackF
    ld hl, HR_R1
    ld de, sfB
    call UnpackF
    call InfNan
    jp z, RetNanF
    call NanBinF
    ret c
    call AddSpecial
    ret c
    jp AddCore

; infinities / zeros of an addition (no NaN). c set if the result is written.
AddSpecial:
    ld a, [sfA + OC]
    cp C_INF
    jr nz, .ainf
    ld a, [sfB + OC]
    cp C_INF
    jr nz, .retA
    ld a, [sfA + OS]
    ld hl, sfB + OS
    cp [hl]
    jr z, .retA
    ld a, [sfA + OS]
    ld b, a                 ; inf - inf: default NaN with A's sign (libgcc)
    call RetNanM
    scf
    ret
.ainf:
    ld a, [sfB + OC]
    cp C_INF
    jr z, .retB
    ld a, [sfB + OC]
    cp C_ZERO
    jr nz, .bnz
    ld a, [sfA + OC]
    cp C_ZERO
    jr nz, .retA
    ; 0 + 0: sign = sA & sB
    ld a, [sfA + OS]
    ld hl, sfB + OS
    and [hl]
    ld b, a
    call RetZeroM
    scf
    ret
.bnz:
    ld a, [sfA + OC]
    cp C_ZERO
    jr z, .retB
    and a
    ret
.retA:
    ld c, 0
    jr .ret
.retB:
    ld c, 1
.ret:
    ; return the raw operand (exact)
    ld a, [sfMode]
    or a
    jr nz, .f
    ld a, c
    or a
    ld c, LOW(HR_R0)
    jr z, .d
    ld c, LOW(HR_R2)
.d:
    call RetCopyD
    scf
    ret
.f:
    ld a, c
    or a
    ld c, LOW(HR_R0)
    jr z, .fc
    ld c, LOW(HR_R1)
.fc:
    call RetCopyF
    scf
    ret

; z if A is an infinity and B a NaN (libgcc's add returns the default NaN)
InfNan:
    ld a, [sfB + OC]
    cp C_NAN
    ret nz
    ld a, [sfA + OC]
    cp C_INF
    ret nz
    ld a, [sfA + OS]
    ld b, a                 ; default NaN inherits the infinity's sign
    xor a                   ; z so the caller jumps to RetNan*
    ret

RetNanM:
    ld a, [sfMode]
    or a
    jp z, RetNanD
    jp RetNanF
RetZeroM:
    ld a, [sfMode]
    or a
    jp z, RetZeroD
    jp RetZeroF
RetInfM:
    ld a, [sfMode]
    or a
    jp z, RetInfD
    jp RetInfF

NAT_dmul_impl::
    xor a
    ld [sfMode], a
    ld hl, HR_R0
    ld de, sfA
    call UnpackD
    ld hl, HR_R2
    ld de, sfB
    call UnpackD
    call NanBinD
    ret c
    jr MulSpecial
NAT_fmul_impl::
    ld a, 1
    ld [sfMode], a
    ld hl, HR_R0
    ld de, sfA
    call UnpackF
    ld hl, HR_R1
    ld de, sfB
    call UnpackF
    call NanBinF
    ret c
MulSpecial:
    ld a, [sfA + OS]
    ld hl, sfB + OS
    xor [hl]
    ld b, a                 ; result sign
    ld a, [sfA + OC]
    ld c, a
    ld a, [sfB + OC]
    cp C_INF
    jr z, .inf
    ld a, c
    cp C_INF
    jr z, .inf2
    cp C_ZERO
    jp z, RetZeroM
    ld a, [sfB + OC]
    cp C_ZERO
    jp z, RetZeroM
    jp MulFin
.inf:                       ; B inf: A zero -> B quieted (libgcc)
    ld a, c
    cp C_ZERO
    jp nz, RetInfM
    ld a, [sfMode]
    or a
    jp z, QuietBD
    jp QuietBF
.inf2:                      ; A inf: B zero -> A quieted
    ld a, [sfB + OC]
    cp C_ZERO
    jp nz, RetInfM
    ld a, [sfMode]
    or a
    jp z, QuietAD
    jp QuietAF

; int -> sfA (sign, |x| << 32, E = 31), z if x == 0
IntToA:
    ld hl, sfA + OM
    xor a
    REPT 4
    ld [hl+], a
    ENDR
    ldh a, [HR_R0 + 3]
    and $80
    ld [sfA + OS], a
    jr z, .pos
    ; negate R0 into M[4..7]
    ld c, LOW(HR_R0)
    scf
    ld b, 4
.n:
    ldh a, [c]
    cpl
    adc 0
    ld [hl+], a
    inc c
    dec b
    jr nz, .n
    jr .e
.pos:
    ld c, LOW(HR_R0)
    ld b, 4
.p:
    ldh a, [c]
    ld [hl+], a
    inc c
    dec b
    jr nz, .p
.e:
    ld a, 31
    ld [sfA + OE], a
    xor a
    ld [sfA + OE + 1], a
    ld a, C_FIN
    ld [sfA + OC], a
    ld hl, sfA + OM
    call Zero64
    ret z
    ld hl, sfA
    call Normalize
    or 1                    ; nz
    ret

NAT_i2d_impl::
    xor a
    ld [sfMode], a
    call IntToA
    jp nz, PackA
    ld b, 0
    jp RetZeroD
NAT_i2f_impl::
    ld a, 1
    ld [sfMode], a
    call IntToA
    jp nz, PackA
    ld b, 0
    jp RetZeroF

NAT_f2d_impl::
    xor a
    ld [sfMode], a
    ld hl, HR_R0
    ld de, sfA
    call UnpackF
    ld a, [sfA + OS]
    ld b, a
    ld a, [sfA + OC]
    cp C_ZERO
    jp z, RetZeroD
    cp C_INF
    jp z, RetInfD
    cp C_NAN
    jp nz, PackA
    ; NaN: frac << 29, quiet bit 51 set, sign kept
    ; sfA.M holds the frac (bits 62..40 when unnormalised: Unpack normalised it...)
    ldh a, [HR_R0]
    ld e, a
    ldh a, [HR_R0 + 1]
    ld d, a
    ldh a, [HR_R0 + 2]
    and $7F
    ld c, a                 ; c:d:e = 23-bit frac
    ; double frac bits 51..29 = frac: hi word bits 19..0 = frac >> 3, lo word bits 31..29 = frac & 7
    xor a
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ld a, e
    rrca
    rrca
    rrca
    and $E0
    ldh [HR_R0 + 3], a
    ; hi word = frac >> 3 (20 bits)
    ld h, c
    ld l, d
    ld a, e
    REPT 3
    srl h
    rr l
    rra
    ENDR
    ldh [HR_R1], a
    ld a, l
    ldh [HR_R1 + 1], a
    ld a, h
    or $F8                  ; exponent low nibble + quiet bit 51 (bit 19)
    ldh [HR_R1 + 2], a
    ld a, b
    or $7F
    ldh [HR_R1 + 3], a
    ret

NAT_d2f_impl::
    ld a, 1
    ld [sfMode], a
    ld hl, HR_R0
    ld de, sfA
    call UnpackD
    ld a, [sfA + OS]
    ld b, a
    ld a, [sfA + OC]
    cp C_ZERO
    jp z, RetZeroF
    cp C_INF
    jp z, RetInfF
    cp C_NAN
    jp nz, PackA
    ld b, 0
    jp RetNanF              ; libgcc returns the (positive) default NaN

NAT_f2iz_impl::
    ; fast path (Phase 5 B3, Snek: 130 conversions per movement tick): biased
    ; exponent e < 127 (|x| < 1, zeros, denormals) -> 0; 127 <= e <= 150
    ; (1 <= |x| < 2^24) -> 24-bit mantissa >> (150 - e), negated for x < 0.
    ; Everything else (large values, inf, NaN) takes the exact path below.
    ldh a, [HR_R0 + 3]
    add a, a                ; exponent bits 7-1 (bit 0 clear)
    ld b, a
    ldh a, [HR_R0 + 2]
    rlca
    and 1                   ; exponent bit 0
    or b
    cp 127
    jp c, .zero
    cp 151
    jr nc, .slow
    ld b, a
    ld a, 150
    sub b
    ld b, a                 ; shift count 0..23
    ldh a, [HR_R0 + 2]
    or $80                  ; implicit 1
    ld e, a
    ldh a, [HR_R0 + 1]
    ld d, a
    ldh a, [HR_R0]
    ld c, a                 ; e:d:c = mantissa
.fby:
    ld a, b
    cp 8
    jr c, .fbi
    sub 8
    ld b, a
    ld c, d
    ld d, e
    ld e, 0
    jr .fby
.fbi:
    inc b
.fbl:
    dec b
    jr z, .fdn
    srl e
    rr d
    rr c
    jr .fbl
.fdn:
    ldh a, [HR_R0 + 3]
    bit 7, a
    jr nz, .fng
    ld a, c
    ldh [HR_R0], a
    ld a, d
    ldh [HR_R0 + 1], a
    ld a, e
    ldh [HR_R0 + 2], a
    xor a
    ldh [HR_R0 + 3], a
    ret
.fng:
    xor a
    sub c
    ldh [HR_R0], a
    ld a, 0
    sbc d
    ldh [HR_R0 + 1], a
    ld a, 0
    sbc e
    ldh [HR_R0 + 2], a
    ld a, 0
    sbc 0
    ldh [HR_R0 + 3], a
    ret
.slow:
    ld hl, HR_R0
    ld de, sfA
    call UnpackF
    ld a, [sfA + OC]
    cp C_FIN
    jr z, .fin
    cp C_INF
    jr z, .ovf
.zero:
    xor a
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ldh [HR_R0 + 3], a
    ret
.fin:
    ld a, [sfA + OE + 1]
    bit 7, a
    jr nz, .zero            ; |x| < 1
    or a
    jr nz, .ovf
    ld a, [sfA + OE]
    cp 31
    jr c, .ok
    jr nz, .ovf
    ; E == 31: only -2^31 fits
    ld a, [sfA + OS]
    or a
    jr z, .ovf
    ld a, [sfA + OM + 7]
    cp $80
    jr nz, .ovf
    ld hl, sfA + OM
    ld b, 7
    xor a
.c31:
    or [hl]
    inc hl
    dec b
    jr nz, .c31
    or a
    jr nz, .ovf
    xor a
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ld a, $80
    ldh [HR_R0 + 3], a
    ret
.ovf:
    ld a, [sfA + OS]
    or a
    ld a, $FF
    ld b, $7F
    jr z, .sat
    xor a
    ld b, $80
.sat:
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ld a, b
    ldh [HR_R0 + 3], a
    ret
.ok:
    ; int = M >> (63 - E): shift M right by (31 - E) then take m4..m7
    ld b, a
    ld a, 31
    sub b
    ld hl, sfA + OM
    call ShrSticky          ; (sticky bit lands in m0, not in m4..m7)
    ld a, [sfA + OS]
    or a
    ld hl, sfA + OM + 4
    ld c, LOW(HR_R0)
    ld b, 4
    jr nz, .neg
.cp:
    ld a, [hl+]
    ldh [c], a
    inc c
    dec b
    jr nz, .cp
    ret
.neg:
    scf
.ng:
    ld a, [hl+]
    cpl
    adc 0
    ldh [c], a
    inc c
    dec b
    jr nz, .ng
    ret

; ------------------------------------------------------------------ float compares
; key of a float in R0 / R1: returns -1 (a < b), 0 (eq), 1 (a > b), 2 (unordered) in a
FCmp:
    ld hl, HR_R0
    call IsNanF
    jr c, .un
    ld hl, HR_R1
    call IsNanF
    jr c, .un
    ; both zero (ignoring sign)?
    ldh a, [HR_R0 + 3]
    and $7F
    ld b, a
    ldh a, [HR_R0 + 2]
    or b
    ld b, a
    ldh a, [HR_R0 + 1]
    or b
    ld b, a
    ldh a, [HR_R0]
    or b
    ld b, a
    ldh a, [HR_R1 + 3]
    and $7F
    or b
    ld b, a
    ldh a, [HR_R1 + 2]
    or b
    ld b, a
    ldh a, [HR_R1 + 1]
    or b
    ld b, a
    ldh a, [HR_R1]
    or b
    jr z, .eq
    ; signs
    ldh a, [HR_R0 + 3]
    ld b, a
    ldh a, [HR_R1 + 3]
    xor b
    bit 7, a
    jr z, .same
    bit 7, b
    jr nz, .lt              ; a negative, b positive
    jr .gt
.same:
    ; unsigned compare of the 32-bit patterns (a - b); c = OR of the differences
    ld hl, HR_R1
    ldh a, [HR_R0]
    sub [hl]
    ld c, a
    inc hl
    ldh a, [HR_R0 + 1]
    sbc [hl]
    ld d, a
    inc hl
    ldh a, [HR_R0 + 2]
    sbc [hl]
    ld e, a
    inc hl
    ldh a, [HR_R0 + 3]
    sbc [hl]
    jr c, .below
    or c
    or d
    or e
    jr z, .eq
    ; a > b as patterns: for negatives reverse
    bit 7, b
    jr nz, .lt
    jr .gt
.below:
    bit 7, b
    jr nz, .gt
.lt:
    ld a, -1
    ret
.gt:
    ld a, 1
    ret
.eq:
    xor a
    ret
.un:
    ld a, 2
    ret

; c if the float at hl is a NaN
IsNanF:
    inc hl
    inc hl
    ld a, [hl+]
    ld b, a
    ld a, [hl]
    and $7F
    cp $7F
    jr nz, .no
    bit 7, b
    jr z, .no
    ld a, b
    and $7F
    dec hl
    dec hl
    or [hl]
    dec hl
    or [hl]
    jr z, .no
    scf
    ret
.no:
    and a
    ret

SetR0Bool:                  ; R0 = (z ? 1 : 0)
    ld a, 0
    jr nz, .s
    inc a
.s:
    ldh [HR_R0], a
    xor a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ldh [HR_R0 + 3], a
    ret

NAT_fcmpeq_impl::
    call FCmp
    or a
    jr SetR0Bool
NAT_fcmplt_impl::
    call FCmp
    cp -1
    jr SetR0Bool
NAT_fcmpgt_impl::
    call FCmp
    cp 1
    jr SetR0Bool

; ------------------------------------------------------------------ integer division
; R0 / R1 unsigned (uidiv / uidivmod): same core with both signs positive;
; divisor 0 -> quotient $FFFFFFFF (0 for 0 / 0), like libgcc.
NAT_uidiv_impl::
NAT_uidivmod_impl::
    ld hl, HR_R1
    ld a, [hl+]
    or [hl]
    inc hl
    or [hl]
    inc hl
    or [hl]
    jr nz, .nz
    ld hl, HR_R0
    ld a, [hl+]
    or [hl]
    inc hl
    or [hl]
    inc hl
    or [hl]
    ret z
    ld a, $FF
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ldh [HR_R0 + 3], a
    ret
.nz:
    xor a
    ld [sfSr], a
    ld [sfSq], a
    ld de, sfD
    ld hl, HR_R1
    REPT 4
    ld a, [hl+]
    ld [de], a
    inc de
    ENDR
    ld de, sfQ
    ld hl, HR_R0
    REPT 4
    ld a, [hl+]
    ld [de], a
    inc de
    ENDR
    jp NAT_idivmod_impl.core

; R0 / R1 signed: quotient -> R0, remainder -> R1 (idivmod); idiv = quotient only.
NAT_idiv_impl::
NAT_idivmod_impl::
    ; divisor 0: libgcc returns INT_MAX / INT_MIN / 0 by the dividend's sign
    ldh a, [HR_R1]
    ld b, a
    ldh a, [HR_R1 + 1]
    or b
    ld b, a
    ldh a, [HR_R1 + 2]
    or b
    ld b, a
    ldh a, [HR_R1 + 3]
    or b
    jp z, .div0
    ; signs
    ldh a, [HR_R0 + 3]
    and $80
    ld [sfSr], a
    ld b, a
    ldh a, [HR_R1 + 3]
    and $80
    xor b
    ld [sfSq], a
    ; D = |R1|, Q = |R0|
    ld c, LOW(HR_R1)
    ld hl, sfD
    call AbsTo
    ld c, LOW(HR_R0)
    ld hl, sfQ
    call AbsTo
.core:
    ; R = 0; skip leading zero bits of Q: n = significant bits
    xor a
    ld hl, sfR
    ld [hl+], a
    ld [hl+], a
    ld [hl+], a
    ld [hl], a
    ld b, 32
.lz:
    ld a, [sfQ + 3]
    bit 7, a
    jr nz, .go
    ld hl, sfQ
    and a
    rl [hl]
    inc hl
    rl [hl]
    inc hl
    rl [hl]
    inc hl
    rl [hl]
    dec b
    jr nz, .lz
    jr .done                ; Q = 0
.go:
    ld a, b
    ld [sfN], a
.loop:
    ; (R:Q) <<= 1
    ld hl, sfQ
    and a
    REPT 8
    rl [hl]
    inc hl
    ENDR
    ; if R >= D: R -= D, Q |= 1
    ld hl, sfR
    ld de, sfD
    ld a, [de]
    ld c, a
    ld a, [hl+]
    sub c
    inc de
    ld a, [de]
    ld c, a
    ld a, [hl+]
    sbc c
    inc de
    ld a, [de]
    ld c, a
    ld a, [hl+]
    sbc c
    inc de
    ld a, [de]
    ld c, a
    ld a, [hl]
    sbc c
    jr c, .next
    ld hl, sfR
    ld de, sfD
    and a
    REPT 4
    ld a, [de]
    ld c, a
    ld a, [hl]
    sbc c
    ld [hl+], a
    inc de
    ENDR
    ld hl, sfQ
    set 0, [hl]
.next:
    ld a, [sfN]
    dec a
    ld [sfN], a
    jr nz, .loop
.done:
    ld a, [sfSq]
    ld hl, sfQ
    ld c, LOW(HR_R0)
    call SignTo
    ld a, [sfSr]
    ld hl, sfR
    ld c, LOW(HR_R1)
    jp SignTo
.div0:
    ldh a, [HR_R0 + 3]
    bit 7, a
    jr nz, .neg
    ld b, a
    ldh a, [HR_R0 + 2]
    or b
    ld b, a
    ldh a, [HR_R0 + 1]
    or b
    ld b, a
    ldh a, [HR_R0]
    or b
    ret z                   ; 0 / 0 -> 0
    ld a, $FF
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ld a, $7F
    ldh [HR_R0 + 3], a
    ret
.neg:
    xor a
    ldh [HR_R0], a
    ldh [HR_R0 + 1], a
    ldh [HR_R0 + 2], a
    ld a, $80
    ldh [HR_R0 + 3], a
    ret

; [hl] = |HRAM c| (32-bit)
AbsTo:
    ld a, c
    add a, 3
    ld e, c
    ld c, a
    ldh a, [c]
    ld c, e
    bit 7, a
    jr nz, .neg
    REPT 4
    ldh a, [c]
    ld [hl+], a
    inc c
    ENDR
    ret
.neg:
    scf
    REPT 4
    ldh a, [c]
    cpl
    adc 0
    ld [hl+], a
    inc c
    ENDR
    ret

; HRAM c = (a & $80) ? -[hl] : [hl]
SignTo:
    bit 7, a
    jr nz, .neg
    REPT 4
    ld a, [hl+]
    ldh [c], a
    inc c
    ENDR
    ret
.neg:
    scf
    REPT 4
    ld a, [hl+]
    cpl
    adc 0
    ldh [c], a
    inc c
    ENDR
    ret

; ------------------------------------------------------------------ 64-bit multiply
; R0:R1 = low 64 bits of (R0:R1 * R2:R3)
NAT_lmul_impl::
    ld hl, sfP
    xor a
    REPT 8
    ld [hl+], a
    ENDR
    ld [sfI], a
.oi:
    ld a, [sfI]
    add a, LOW(HR_R0)
    ld c, a
    ldh a, [c]
    or a
    jr z, .ni
    ld b, a
    xor a
    ld [sfJ], a
.oj:
    ld a, [sfI]
    ld hl, sfJ
    add a, [hl]
    cp 8
    jr nc, .ni              ; byte i + j beyond the low 64 bits
    ld a, [sfJ]
    add a, LOW(HR_R2)
    ld c, a
    ldh a, [c]
    or a
    jr z, .nj
    ld c, a
    push bc
    call Mul8
    pop bc
    ld a, [sfI]
    ld hl, sfJ
    add a, [hl]
    ld [sfN], a
    cp 7
    jr nz, .two
    ld hl, sfP + 7          ; only the low product byte lands below bit 64
    ld a, [hl]
    add a, e
    ld [hl], a
    jr .nj
.two:
    ld hl, sfP
    add a, l
    ld l, a
    ld a, [hl]
    add a, e
    ld [hl+], a
    ld a, [hl]
    adc d
    ld [hl+], a
    jr nc, .nj
    ld a, [sfN]
    add a, 2
.cy:
    cp 8
    jr nc, .nj
    ld e, a
    ld a, [hl]
    add a, 1
    ld [hl+], a
    jr nc, .nj
    ld a, e
    inc a
    jr .cy
.nj:
    ld a, [sfJ]
    inc a
    ld [sfJ], a
    cp 8
    jr nz, .oj
.ni:
    ld a, [sfI]
    inc a
    ld [sfI], a
    cp 8
    jr nz, .oi
    ld hl, sfP
    ld c, LOW(HR_R0)
    REPT 8
    ld a, [hl+]
    ldh [c], a
    inc c
    ENDR
    ret
