"""Phase P1/P2: idiom -> HAL lifting (docs/proposal_generic_engine.md, technique 1).

A BL target whose whole body matches an idiom of the table is not lifted; the call
becomes `call NAT_<name>` (a native SM83 routine in the HAL), like the libgcc
helpers of tools/lift/lift.py NATIVES. Matching is by instruction semantics, not by
address or symbol name: each instruction is normalised (mnemonic + operands, with
the callee-saved/scratch registers that are not part of the calling convention
renamed in order of appearance), so the idiom is found in any game built by the
same compiler idiom, at any address, any number of times.

The native routine must reproduce the ARM-visible effects exactly: memory writes,
and the values left in r0-r3 (callers may only rely on what the AAPCS allows, but the
lockstep/state checks see memory only). Flags are not preserved across a BL by the
AAPCS, so they are not modelled.
"""
from __future__ import annotations
import re

ARGS = {"r0", "r1", "r2"}          # argument registers keep their names


def _norm(text, ren):
    def sub(m):
        r = m.group(0)
        if r in ARGS or r in ("sp", "lr", "pc"):
            return r
        if r not in ren:
            ren[r] = f"s{len(ren)}"
        return ren[r]
    return re.sub(r"\br\d+\b", sub, text.replace("\t", " ").strip())


# tonc / libgba style obj_set_pos(obj, x, y):
#   obj->attr0 = (obj->attr0 & ~0xFF) | (y & 0xFF); obj->attr1 = (obj->attr1 & ~0x1FF) | (x & 0x1FF)
# as emitted by arm-none-eabi-gcc -O2 -mthumb (Snek, gba.h set_obj_pos).
IDIOMS = {
    "objsetpos": [
        "push {s0, lr}", "movs s0, #0xff", "ldrh s1, [r0]", "ands r2, s0", "bics s1, s0",
        "orrs s1, r2", "strh s1, [r0]", "ldrh s1, [r0, #2]", "lsls r1, r1, #0x17",
        "lsrs s1, s1, #9", "lsrs r1, r1, #0x17", "lsls s1, s1, #9", "orrs s1, r1",
        "strh s1, [r0, #2]", "pop {s0}", "pop {r0}", "bx r0",
    ],
}


def match(md, img, addr, read):
    """Name of the idiom implemented by the function at `addr`, else None.
    `read(addr, n)` returns ROM bytes."""
    for name, pat in IDIOMS.items():
        code = read(addr & ~1, 2 * len(pat) + 4)
        ins = list(md.disasm(code, addr & ~1))[:len(pat)]
        if len(ins) < len(pat):
            continue
        ren = {}
        got = [_norm(f"{i.mnemonic} {i.op_str}", ren) for i in ins]
        if got == pat:
            return name
    return None
