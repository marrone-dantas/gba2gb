"""Indirect calls (Thumb-1 `bl stub` / `stub: bx rN`, e.g. C++ virtual calls).

tools/lift/lift.py turns such a call into `call NAT_icall_rN`; the possible targets are
the lifted Thumb functions whose address is stored as data in the ELF (vtables,
function pointer tables: Image.taken). This module emits the run-time dispatch:

* NAT_icall_rN (ROM0) loads the low three bytes of rN and jumps to ICallDispatch;
* ICallDispatch maps the table bank (without touching wRomBank), indexes a bucket
  array by address bits 8-23 relative to the lowest target, scans the bucket for
  address bits 0-7 and jumps to FarCall with the target's bank and label, so the
  callee returns to the lifted caller through FarRet with the caller's bank.
* An address that is not a lifted function (ARM code, not taken, outside the image)
  is a no-op call (ICallDispatch.miss).
"""
from __future__ import annotations


def asm(prog):
    regs = sorted(getattr(prog, "icalls", set()))
    if not regs:
        return ""
    tg = sorted(t for t in prog.img.taken if t in prog.funcs and t in prog.ins)
    L = ['SECTION "icall_code", ROM0']
    for r in regs:
        L += [f"NAT_icall_r{r}::", f"    ldh a, [$FF{0x80 + 4 * r:02X}]", "    ld c, a",
              f"    ldh a, [$FF{0x81 + 4 * r:02X}]", "    ld e, a",
              f"    ldh a, [$FF{0x82 + 4 * r:02X}]", "    ld d, a", "    jp ICallDispatch"]
    if not tg:
        L += ["ICallDispatch:", "    ret"]
        return "\n".join(L) + "\n"
    base = (tg[0] >> 8) & 0xFFFF
    nb = ((tg[-1] >> 8) & 0xFFFF) - base + 1
    L += ["ICallDispatch:",
          "    ld a, e", f"    sub ${base & 0xFF:02X}", "    ld l, a",
          "    ld a, d", f"    sbc ${base >> 8:02X}", "    ld h, a",
          "    ld a, l", f"    sub ${nb & 0xFF:02X}", "    ld a, h", f"    sbc ${nb >> 8:02X}",
          "    jr nc, .miss",
          "    add hl, hl", "    ld de, ICallBuckets", "    add hl, de",
          "    ld a, BANK(ICallBuckets)", "    ld [$2000], a",
          "    ld a, [hl+]", "    ld h, [hl]", "    ld l, a",
          "    ld a, [hl+]", "    or a", "    jr z, .miss", "    ld b, a",
          ".scan:", "    ld a, [hl+]", "    cp c", "    jr z, .hit",
          "    inc hl", "    inc hl", "    inc hl", "    dec b", "    jr nz, .scan",
          ".miss:", "    ld a, [wRomBank]", "    ld [$2000], a",
          "    ret",
          ".hit:", "    ld a, [hl+]", "    ld e, a", "    ld a, [hl+]", "    ld h, [hl]", "    ld l, a",
          "    ld a, e", "    jp FarCall",
          'SECTION "icall_tab", ROMX', "ICallBuckets:"]
    buckets = {}
    for t in tg:
        buckets.setdefault(((t >> 8) & 0xFFFF) - base, []).append(t)
    L += [f"    dw .b{k}" if k in buckets else "    dw .empty" for k in range(nb)]
    L += [".empty: db 0"]
    for k, ts in sorted(buckets.items()):
        L.append(f".b{k}: db {len(ts)}")
        for t in ts:
            L.append(f"    db ${(t | 1) & 0xFF:02X}, BANK(L_{t:08X})")
            L.append(f"    dw L_{t:08X}")
    return "\n".join(L) + "\n"
