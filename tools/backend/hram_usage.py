"""Static count of HRAM register-file bytes referenced by generated code."""
import re

REG_LO, REG_HI = 0xFF80, 0xFFC0


def hram_reg_bytes(asm):
    """Static count of register-area bytes ($FF80-$FFBF) the generated code reads or
    writes: explicit `ldh [$FFxx]` operands plus `[hl]` walks after `ld hl, $FFxx`
    (followed through inc l / dec l)."""
    used, cur = set(), None
    for line in asm.splitlines():
        t = line.split(";")[0].strip()
        if not t:
            if line.strip().endswith(":"):
                cur = None
            continue
        m = re.match(r"ld hl, \$(FF[0-9A-F]{2})$", t)
        if m:
            cur = int(m.group(1), 16)
            continue
        if t in ("inc l",) and cur is not None:
            cur += 1
        elif t == "dec l" and cur is not None:
            cur -= 1
        elif t.startswith(("ld h,", "ld l,", "ld hl,", "call", "jp", "ret")) or "hl+" in t:
            cur = None
        if "[hl]" in t and cur is not None:
            used.add(cur)
        for m in re.finditer(r"\[\$(FF[0-9A-F]{2})\]", t):
            used.add(int(m.group(1), 16))
    used |= {0xFF80 + i for i in range(16)} | {0xFFB4 + i for i in range(4)}  # args + SP
    return len({a for a in used if REG_LO <= a < REG_HI})
