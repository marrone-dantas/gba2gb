"""Register def/use sets for IR instructions (shared by the tracer and SSA)."""
from tools.lift.lift import Ins

CALL_CLOBBER = (0, 1, 2, 3, 12, 14)  # AAPCS caller-saved registers + LR


def _r(x):
    return int(x[1:]) if isinstance(x, str) else None


def defs(x: Ins):
    """Registers written by the instruction (excluding flags)."""
    op = x.op
    if op in ("cmp", "cmn", "tst", "b", "bcc", "ret", "nop") or op.startswith("str"):
        return []
    if op == "push":
        return [13]
    if op in ("pop", "pop_ret"):
        return list(x.regs) + [13]
    if op == "ldm":
        return list(x.regs) + ([x.rd] if x.wb and x.rd not in x.regs else [])
    if op == "stm":
        return [x.rd] if x.wb else []
    if op == "bl":
        return list(CALL_CLOBBER)
    return [x.rd] if x.rd is not None else []


def uses(x: Ins):
    """Registers read by the instruction."""
    op = x.op
    u = [r for r in (_r(x.a), _r(x.b)) if r is not None]
    if x.mem:
        base, idx, _ = x.mem
        u += [base] + ([idx] if idx is not None else [])
        if op.startswith("str"):
            u.append(x.rd)
    if op == "push":
        u += list(x.regs) + [13]
    if op in ("pop", "pop_ret"):
        u.append(13)
    if op in ("ldm", "stm"):
        u.append(x.rd)
        if op == "stm":
            u += list(x.regs)
    if op in ("ret", "pop_ret"):
        u.append(0)
    if op == "bl":
        u += [0, 1, 2, 3, 13]
    return list(dict.fromkeys(u))
