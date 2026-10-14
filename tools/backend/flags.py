"""Backward liveness of the NZCV flags over the CFG (per function).

Used by the narrowed backend to skip computing flags nobody reads. Calls (BL)
kill all flags (AAPCS does not preserve them); returns have no live flags."""
from tools.lift.lift import Ins

COND_READS = {"eq": "Z", "ne": "Z", "cs": "C", "cc": "C", "mi": "N", "pl": "N", "vs": "V", "vc": "V",
              "hi": "CZ", "ls": "CZ", "ge": "NV", "lt": "NV", "gt": "NVZ", "le": "NVZ"}


def reads(x: Ins):
    if x.op == "bcc":
        return set(COND_READS[x.cond])
    if x.op in ("adc", "sbc"):
        return {"C"}
    return set()


def kills(x: Ins):
    """Flags that are definitely overwritten by x."""
    if x.op == "bl":
        return set("NZCV")
    if not x.s:
        return set()
    if x.op in ("add", "sub", "adc", "sbc", "cmp", "cmn"):
        return set("NZCV")
    if x.op in ("lsl", "lsr", "asr", "ror"):
        if isinstance(x.b, int) and not (x.op == "lsl" and x.b == 0):
            return set("NZC")
        return set("NZ")  # register amount 0 leaves C unchanged
    return set("NZ")


def live_out(ssa):
    """Address -> set of flags live right after the instruction."""
    out = {}
    for f in ssa.funcs.values():
        g = f.g
        live_in = {n: set() for n in g}
        changed = True
        while changed:
            changed = False
            for n in reversed(list(g)):
                ins = g.nodes[n]["ins"]
                live = set()
                if ins[-1].op not in ("ret", "pop_ret"):
                    for s in g.successors(n):
                        live |= live_in[s]
                for x in reversed(ins):
                    out[x.addr] = set(live)
                    live = (live - kills(x)) | reads(x)
                if live != live_in[n]:
                    live_in[n] = live
                    changed = True
    return out
