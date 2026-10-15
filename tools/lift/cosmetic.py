"""Cosmetic-loop detection and removal (docs/homebrew_port.md, "Cosmetic loops").

A loop is *cosmetic* (background particles, snow, sparkles) when, statically:
  * it walks one global array with a pointer stride (`adds rP, #elem`, base literal
    in the loop preheader) and stores only through that pointer or to the stack;
  * every call goes to a drawing native (the port's sprite overrides) or to a small
    "random" helper (arithmetic callees only, <= 2 global stores - an RNG state);
  * it reads no I/O register (input) and calls nothing else (no collision, no game
    logic), and no register it defines is read after the loop exits.
`find(elf, draw_calls)` lists them; `remove(elf, out, loops)` writes a patched ELF
copy whose loop header branches straight to the loop exit (the body is no longer
reachable, so it is not lifted). A cap K > 0 instead keeps the first K elements
(tools/lift/array_cap.py). Thumb only.
"""
from __future__ import annotations
import re
import shutil
import capstone as cs
from tools.audio.strip import demangle_base
from elftools.elf.elffile import ELFFile

DEBUG = False
BR = {"b", "beq", "bne", "bcs", "bcc", "bmi", "bpl", "bvs", "bvc", "bhi", "bls", "bge", "blt", "bgt",
      "ble", "bhs", "blo"}
STORE = re.compile(r"str[bh]?$|stm")


def _load(elf):
    with open(elf, "rb") as fh:
        e = ELFFile(fh)
        st = e.get_section_by_name(".symtab")
        text = e.get_section_by_name(".text")
        syms = list(st.iter_symbols())
        funcs = {s.name: (s["st_value"] & ~1, s["st_size"]) for s in syms
                 if s["st_info"]["type"] == "STT_FUNC" and s["st_value"] & 1 and s["st_size"]}
        allf = {s["st_value"] & ~1: s.name for s in syms if s["st_info"]["type"] == "STT_FUNC"}
        objs = [(s["st_value"], s["st_size"], s.name) for s in syms
                if s["st_info"]["type"] == "STT_OBJECT" and s["st_size"]]
        return funcs, allf, objs, text["sh_addr"], text["sh_offset"], bytes(text.data())


def _imm(t):
    return int(t, 0)


class Func:
    def __init__(self, name, lo, size, text, taddr):
        self.name, self.lo, self.size = name, lo, size
        code = text[lo - taddr:lo - taddr + size]
        md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB)
        self.lit = {}
        ins = list(md.disasm(code, lo))
        for x in ins:
            m = re.match(r"(r\d+), \[pc, #(0x[0-9a-f]+|\d+)\]", x.op_str)
            if x.mnemonic == "ldr" and m:
                t = ((x.address + 4) & ~3) + _imm(m.group(2))
                if lo <= t <= lo + size - 4:
                    self.lit[x.address] = int.from_bytes(code[t - lo:t - lo + 4], "little")
        pool = set()
        for a in self.lit:
            m = re.search(r"#(0x[0-9a-f]+|\d+)\]", next(i for i in ins if i.address == a).op_str)
            t = ((a + 4) & ~3) + _imm(m.group(1))
            pool.update(range(t, t + 4))
        self.ins = [x for x in ins if x.address not in pool]
        self.at = {x.address: k for k, x in enumerate(self.ins)}

    def succ(self, k):
        x = self.ins[k]
        nxt = [k + 1] if k + 1 < len(self.ins) else []
        if x.mnemonic in BR and x.op_str.startswith("#"):
            t = self.at.get(_imm(x.op_str[1:]))
            tl = [t] if t is not None else []
            return tl if x.mnemonic == "b" else tl + nxt
        if x.mnemonic in ("pop", "bx") and ("pc" in x.op_str or x.mnemonic == "bx"):
            return []
        return nxt

    def loops(self):
        """(header index, latch index) of the back edges."""
        for k, x in enumerate(self.ins):
            if x.mnemonic in BR and x.mnemonic != "b" and x.op_str.startswith("#"):
                t = self.at.get(_imm(x.op_str[1:]))
                if t is not None and t <= k:
                    yield t, k

    def body(self, h, latch):
        pred = {}
        for k in range(len(self.ins)):
            for s in self.succ(k):
                pred.setdefault(s, []).append(k)
        body, work = {h, latch}, [latch]
        while work:
            n = work.pop()
            if n == h:
                continue
            for p in pred.get(n, []):
                if p not in body:
                    body.add(p)
                    work.append(p)
        return body


ARITH = re.compile(r"_*aeabi_\w+|_*(?:u?div|u?mod)[sd]i3\w*|\w*_from_thumb")


def _rng_like(fn, F, by_addr, allf, depth=0):
    """Arithmetic helpers, or a helper (tree) with at most one global store and only
    such callees (an RNG: `rndi` -> `rand` -> 64-bit state update, <= 2 stores)."""
    if depth > 4:
        return False
    stores = sum(1 for x in fn.ins if STORE.match(x.mnemonic) and "sp" not in x.op_str)
    for x in fn.ins:
        if x.mnemonic in ("bl", "blx") and x.op_str.startswith("#"):
            a = _imm(x.op_str[1:])
            if ARITH.fullmatch(allf.get(a, "")):
                continue
            t = by_addr.get(a)
            if t is None or not _rng_like(t, F, by_addr, allf, depth + 1):
                return False
    return stores <= 2


def find(elf, draw_calls):
    funcs, allf, objs, taddr, toff, text = _load(elf)
    F = {n: Func(n, lo, sz, text, taddr) for n, (lo, sz) in funcs.items()}
    by_addr = {f.lo: f for f in F.values()}
    out = []

    def obj_of(v):
        for a, s, n in objs:
            if a <= v < a + s:
                return n, a, s
        return None

    for fn in F.values():
        for h, latch in fn.loops():
            body = fn.body(h, latch)
            why = None
            regs_def = set()
            ptr = arr = None
            cands = []
            for k in sorted(body):
                x = fn.ins[k]
                m = re.fullmatch(r"(r\d+), #(0x[0-9a-f]+|\d+)", x.op_str)
                if x.mnemonic == "adds" and m and _imm(m.group(2)) > 1:
                    cands.append((m.group(1), _imm(m.group(2))))
            # the array: a stride register loaded with an array literal before the loop
            for c in cands:
                for k in range(h - 1, max(-1, h - 12), -1):
                    x = fn.ins[k]
                    if x.mnemonic == "ldr" and x.op_str.startswith(c[0] + ",") and x.address in fn.lit:
                        o = obj_of(fn.lit[x.address])
                        if o and o[1] == fn.lit[x.address] and o[2] % c[1] == 0:
                            ptr, arr = c, o
                        break
                if ptr:
                    break
            if not arr or arr[2] % ptr[1]:
                continue
            draws = 0
            for k in sorted(body):
                x = fn.ins[k]
                ops = x.op_str
                if x.address in fn.lit and 0x04000000 <= fn.lit[x.address] < 0x04000400:
                    why = "reads I/O"
                elif STORE.match(x.mnemonic):
                    base = re.search(r"\[(r\d+|sp)", ops)
                    if not base or base.group(1) not in (ptr[0], "sp"):
                        why = f"store {x.mnemonic} {ops}"
                elif x.mnemonic in ("bl", "blx"):
                    a = _imm(ops[1:])
                    t = by_addr.get(a)
                    if ARITH.fullmatch(allf.get(a, "")):
                        pass
                    elif t is None:
                        why = "unknown call"
                    elif t.name in draw_calls or demangle_base(t.name) in draw_calls:
                        draws += 1
                    elif not _rng_like(t, F, by_addr, allf):
                        why = f"calls {t.name}"
                d = re.match(r"(r\d+)", ops)
                if d and not STORE.match(x.mnemonic) and x.mnemonic not in ("cmp", "tst", "cmn") + tuple(BR):
                    regs_def.add(d.group(1))
                if why:
                    break
            if DEBUG:
                print(fn.name, hex(fn.ins[h].address), why, draws, arr)
            if why or not draws:
                continue
            # registers defined in the loop must be dead at the exit
            ex = latch + 1
            for x in fn.ins[ex:]:
                if x.mnemonic in ("pop", "bx"):
                    break
                ops = [o.strip("[]! {}") for o in x.op_str.split(",")]
                reads = ops if STORE.match(x.mnemonic) or x.mnemonic in ("cmp", "tst") else ops[1:]
                if any(r in regs_def for r in reads):
                    why = f"{x.op_str} reads a loop register after exit"
                    break
                if ops and ops[0] in regs_def:
                    regs_def.discard(ops[0])
                if x.mnemonic in BR or x.mnemonic in ("bl", "blx"):
                    break
            if why:
                continue
            out.append({"func": fn.name, "header": fn.ins[h].address, "exit": fn.ins[ex].address,
                        "array": arr[0], "elem": ptr[1], "count": arr[2] // ptr[1]})
    return out


def remove(elf, out, loops):
    funcs, allf, objs, taddr, toff, text = _load(elf)
    t = bytearray(text)
    for lp in loops:
        off = lp["exit"] - (lp["header"] + 4)
        assert -2048 <= off // 2 < 1024
        t[lp["header"] - taddr:lp["header"] - taddr + 2] = (0xE000 | ((off >> 1) & 0x7FF)).to_bytes(2, "little")
    shutil.copyfile(elf, out)
    with open(out, "r+b") as fh:
        fh.seek(toff)
        fh.write(t)
