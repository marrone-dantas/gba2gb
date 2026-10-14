"""Phase 5 A1: pointer provenance (address space of every SSA value), including
values that travel through stack slots (spills, push/pop).

Lattice: a set of tags. Regions from tools/hal/intercept.REGIONS ("ram", "rom",
"io", "pal", "vram", "oam"), "stack" (derived from SP), "int" (proven not to be a
pointer: range below 0x02000000) and "?" (unknown origin: loaded from non-stack
memory, entry parameters, untracked operations).

Stack slots are keyed by (function, SP offset relative to the function entry) and
hold the join of everything stored to them (`str rX, [sp, #d]`, `push`). A function
whose stack address escapes (an SP-derived value used as a store base other than
SP, or passed to a call) gets "?" added to every slot load."""
from __future__ import annotations
from tools.hal.intercept import interval, region_of

UNKNOWN = frozenset({"?"})
INT = frozenset({"int"})
STACK = frozenset({"stack"})


class Provenance:
    def __init__(self, ssa, ind):
        self.ssa, self.ind = ssa, ind
        self.p = {}
        self.slots = {}
        self.spoff_memo = {}
        self.tainted = set()
        self._solve()

    # ------------------------------------------------------------ SP offsets
    def spoff(self, v):
        if v is None:
            return None
        if v in self.spoff_memo:
            return self.spoff_memo[v]
        self.spoff_memo[v] = None
        r = None
        if v.kind == "param" and v.reg == 13:
            r = 0
        elif v.kind == "pi":
            r = self.spoff(v.env["x"])
        elif v.kind == "ins" and v.reg == 13:
            x, base = v.ins, self.spoff(v.env.get(13))
            if base is not None:
                if x.op == "push":
                    r = base - 4 * len(x.regs)
                elif x.op in ("pop", "pop_ret"):
                    r = base + 4 * len(x.regs)
                elif x.op in ("sub", "add") and isinstance(x.b, int) and x.a == "r13":
                    r = base + (x.b if x.op == "add" else -x.b)
        elif v.kind == "phi":
            offs = {self.spoff(a) for a in v.args.values()}
            r = offs.pop() if len(offs) == 1 else None
        self.spoff_memo[v] = r
        return r

    # ------------------------------------------------------------ lattice
    def of(self, v):
        if v is None:
            return UNKNOWN
        return self.p.get(v, frozenset())

    def _base(self, v):
        iv = interval(v, self.ind)
        if iv is not None:
            reg = region_of(iv[0], iv[1])
            if reg:
                return frozenset({reg})
            if iv[1] < 0x02000000:
                return INT
        return None

    def _operand(self, v, x):
        if isinstance(x, int):
            return INT
        return self.of(v.env.get(int(x[1:])))

    def transfer(self, v):
        b = self._base(v)
        if b is not None:
            return b
        f = self.ssa.func_of.get(v)
        if v.links is not None:
            out = frozenset()
            for a in v.links:
                out |= self.of(a)
            return out or UNKNOWN
        if v.kind == "param":
            return STACK if v.reg == 13 else UNKNOWN
        if v.kind == "pi":
            return self.of(v.env["x"])
        if v.kind == "phi":
            out = frozenset()
            for a in v.args.values():
                out |= self.of(a)
            return out
        x = v.ins
        if v.reg == 13:
            return STACK
        if x.op in ("pop", "pop_ret"):
            off = self.spoff(v.env.get(13))
            if off is None or v.reg not in x.regs:
                return UNKNOWN
            return self._slot(f, off + 4 * sorted(x.regs).index(v.reg))
        if x.op in ("ldm", "stm") and v.reg == x.rd:
            return self.of(v.env.get(x.rd))
        if v.reg != x.rd:
            return UNKNOWN
        if x.mem is not None and x.op.startswith("ldr"):
            base, idx, disp = x.mem
            if base == 13 and idx is None and x.op == "ldr":
                off = self.spoff(v.env.get(13))
                return UNKNOWN if off is None else self._slot(f, off + disp)
            return UNKNOWN
        if x.op == "mov":
            return self._operand(v, x.a)
        if x.op in ("add", "sub"):
            s = self._operand(v, x.a) | self._operand(v, x.b)
            s -= INT
            return s or INT
        ops = [self._operand(v, o) for o in (x.a, x.b) if o is not None]
        if ops and all(o <= INT for o in ops):
            return INT
        return UNKNOWN

    def _slot(self, f, off):
        if (f, off) not in self.slots:
            return UNKNOWN          # never written in this function
        s = self.slots[(f, off)]
        return s | UNKNOWN if f in self.tainted else s

    def _stores(self):
        ch = False
        for a, x in self.ssa.prog.ins.items():
            env = self.ssa.envs.get(a)
            if env is None:
                continue
            f = self._func_at(a)
            if x.op == "push":
                off = self.spoff(env.get(13))
                if off is None:
                    continue
                off -= 4 * len(x.regs)
                for i, r in enumerate(sorted(x.regs)):
                    ch |= self._add_slot(f, off + 4 * i, self.of(env.get(r)) if r != 14 else INT)
            elif x.mem is not None and x.op.startswith("str"):
                base, idx, disp = x.mem
                if base == 13 and idx is None:
                    off = self.spoff(env.get(13))
                    if off is not None:
                        val = self.of(env.get(x.rd)) if x.op == "str" else INT
                        ch |= self._add_slot(f, off + disp, val)
                elif self.of(env.get(base)) & STACK and f not in self.tainted:
                    self.tainted.add(f)
                    ch = True
            elif x.op == "bl":
                if any(self.of(env.get(r)) & STACK for r in range(4)) and f not in self.tainted:
                    self.tainted.add(f)
                    ch = True
        return ch

    def _func_at(self, a):
        if not hasattr(self, "_fa"):
            self._fa = {}
            for fa, fn in self.ssa.funcs.items():
                for ad in fn.envs:
                    self._fa[ad] = fa
        return self._fa.get(a)

    def _add_slot(self, f, off, val):
        old = self.slots.get((f, off), frozenset())
        new = old | val
        if new != old or (f, off) not in self.slots:
            self.slots[(f, off)] = new
            return new != old
        return False

    def _solve(self):
        for _ in range(100):
            ch = self._stores()
            for v in self.ssa.values:
                new = self.of(v) | self.transfer(v)
                if new != self.of(v):
                    self.p[v] = new
                    ch = True
            if not ch:
                return
        raise RuntimeError("provenance did not converge")

    def region(self, env, base, idx=None):
        """Address space of base (+ idx) -> 'ram' | 'rom' | 'vram' | 'pal' | None (unknown)."""
        s = self.of(env.get(base))
        if idx is not None:
            s = s | self.of(env.get(idx))
        s = s - INT
        s = frozenset("ram" if t == "stack" else t for t in s)
        if len(s) == 1 and "?" not in s:
            return next(iter(s))
        return None
