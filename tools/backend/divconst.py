"""Division / modulo by a constant through ROM tables (step 7, docs/softfloat.md,
"Division by constant").

The lifter (tools/lift/lift.py, `_const_div`) rewrites `bl __aeabi_{u,}idiv{,mod}`
whose divisor r1 is a block-local constant d (2..960, not a power of two) into
`call NAT_divc_<kind>_<d>`. Each divisor gets one ROMX bank with
  * Q[i] = i // d for i < 16 d (one byte) and M[q] = q * d for q < 16,
and long division in base 16: per dividend nibble n, i = 16 r + n, q = Q[i],
r = i - M[q] (8 nibbles, leading zero bytes skipped), instead of a 32-step shift /
subtract loop. Signed kinds divide |x| and fix the signs (C truncation).
Results as the AEABI helpers: r0 = quotient, r1 = remainder."""
from __future__ import annotations

KINDS = {"uidiv": False, "uidivmod": False, "idiv": True, "idivmod": True}


def eligible(d):
    return isinstance(d, int) and 2 <= d <= 960 and d & (d - 1)


def _db(bs):
    return ["    db " + ", ".join(f"${b:02X}" for b in bs[i:i + 32]) for i in range(0, len(bs), 32)]


def asm(divs):
    """divs: set of (kind, d). Returns RGBDS source."""
    if not divs:
        return ""
    L, stubs = [], []
    byd = {}
    for k, d in sorted(divs):
        byd.setdefault(d, set()).add(k)
    for d, kinds in sorted(byd.items()):
        q = bytes(i // d for i in range(16 * d))
        m = b"".join((j * d).to_bytes(2, "little") for j in range(16))
        L += [f'SECTION "divc_{d}", ROMX', f"DivcQ_{d}:"] + _db(q) + [f"DivcM_{d}:"] + _db(m)
        L += [f"DivcNib_{d}:                ; a = nibble, de = r -> a = q nibble, de = r'",
              "    ld h, d", "    ld l, e", "    add hl, hl", "    add hl, hl", "    add hl, hl", "    add hl, hl",
              "    or l", "    ld l, a", "    ld b, h", "    ld c, l", f"    ld de, DivcQ_{d}", "    add hl, de",
              "    ld a, [hl]", "    push af", "    add a, a", "    ld e, a", "    ld d, 0", f"    ld hl, DivcM_{d}",
              "    add hl, de", "    ld a, [hl+]", "    ld e, a", "    ld d, [hl]", "    ld a, c", "    sub e",
              "    ld e, a", "    ld a, b", "    sbc d", "    ld d, a", "    pop af", "    ret"]
        for k in sorted(kinds):
            sg = KINDS[k]
            n = f"{k}_{d}"
            L += [f"DivcCore_{n}:"]
            if sg:
                L += ["    ldh a, [HR_R0 + 3]", "    rlca", "    push af              ; carry = negative",
                      "    jr nc, .pos", "    ld c, LOW(HR_R0)", "    call DivcNeg32", ".pos:"]
            L += ["    ld de, 0"]
            for b in (3, 2, 1, 0):
                L += [f"    ld a, d", "    or e", f"    jr nz, .b{b}", f"    ldh a, [HR_R0 + {b}]", "    or a",
                      f"    jr z, .z{b}", f".b{b}:", f"    ldh a, [HR_R0 + {b}]", "    push af", "    swap a",
                      "    and $0F", f"    call DivcNib_{d}", "    swap a", f"    ldh [HR_R0 + {b}], a", "    pop af",
                      "    and $0F", f"    call DivcNib_{d}", "    ld b, a", f"    ldh a, [HR_R0 + {b}]", "    or b",
                      f"    ldh [HR_R0 + {b}], a", f".z{b}:"]
            L += ["    ld a, e", "    ldh [HR_R1], a", "    ld a, d", "    ldh [HR_R1 + 1], a", "    xor a",
                  "    ldh [HR_R1 + 2], a", "    ldh [HR_R1 + 3], a"]
            if sg:
                L += ["    pop af", "    ret nc", "    ld c, LOW(HR_R0)", "    call DivcNeg32", "    ld c, LOW(HR_R1)",
                      "    jp DivcNeg32"]
            else:
                L += ["    ret"]
            stubs += [f"NAT_divc_{n}::", f"    ld a, BANK(DivcCore_{n})", f"    ld hl, DivcCore_{n}", "    jp FarCall"]
    L += ['SECTION "divc_stubs", ROM0'] + stubs + [ "DivcNeg32:                  ; negate the 4 HRAM bytes at c",
          "    ld b, 4", "    scf", ".l:", "    ldh a, [c]", "    cpl", "    adc a, 0", "    ldh [c], a", "    inc c",
          "    dec b", "    jr nz, .l", "    ret"]
    return "\n".join(L) + "\n"
