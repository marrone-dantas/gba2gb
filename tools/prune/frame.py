"""Stack-frame analysis (Phase 1.5).

* SP tracking: every SSA value of r13 gets its offset from the function's entry SP
  (push/pop/`add|sub sp, #imm`); pointer values derived from SP (`add rX, sp, #k`,
  `mov rX, sp`) get a known offset too.
* Save slots: each register stored by `push` occupies a 4-byte slot at a known offset;
  each `pop` reads slots back into registers.
* Usefulness of restored values: a value is *useful* if some instruction reads it
  (other than a plain `mov` copy into a useless value), if it flows through phi/pi into
  a useful value, or if it is the value of a register that is live at a return.
  Registers live at a return:
    - default (AAPCS as far as it matters here): r0 and the callee-saved r4-r11.
      LR is never live: returns use the SM83 call stack (item 1);
    - opt-in `entry_abi="none"` for the program entry only: r0 (item 2). The caller
      (the harness / game code calling the kernel) must then treat r1-r12 and LR as
      clobbered, exactly like caller-saved registers.
* A push slot is *skippable* (not written) when every pop that reads it yields a
  useless value and no other constant-offset SP access overlaps it. Pops of useless
  values do not load anything.

Assumption (C semantics): memory accesses through pointers derived from a local
object stay inside that object; they never touch the register-save area.
"""
from __future__ import annotations
from tools.prune import range_analysis as ra
from tools.lift.defuse import uses

ARGREGS = (0,)
CALLEE_SAVED = tuple(range(4, 12))


def sp_offsets(ssa):
    """Value -> byte offset from the entry SP (only for SP and SP-derived pointers)."""
    off = {}
    for f in ssa.funcs.values():
        off[f.params[13]] = 0
    changed = True
    while changed:
        changed = False
        for v in ssa.values:
            if v in off:
                continue
            o = None
            if v.kind == "pi" and v.env["x"] in off:
                o = off[v.env["x"]]
            elif v.kind == "phi":
                os_ = {off.get(a) for a in v.args.values()}
                if len(os_) == 1 and None not in os_:
                    o = os_.pop()
            elif v.kind == "ins":
                x = v.ins
                sp = v.env.get(13)
                if x.op == "push" and v.reg == 13 and sp in off:
                    o = off[sp] - 4 * len(x.regs)
                elif x.op in ("pop", "pop_ret") and v.reg == 13 and sp in off:
                    o = off[sp] + 4 * len(x.regs)
                elif x.op in ("add", "sub", "mov") and v.reg == x.rd:
                    a = v.env.get(int(x.a[1:])) if isinstance(x.a, str) else None
                    if x.op == "mov" and a in off:
                        o = off[a]
                    elif a in off and isinstance(x.b, int):
                        o = off[a] + (x.b if x.op == "add" else -x.b)
                    elif x.op == "add" and isinstance(x.b, str) and a is not None:
                        b = v.env.get(int(x.b[1:]))
                        if b in off and a.proven and a.proven[0] == a.proven[1]:
                            o = off[b] + a.proven[0]
            if o is not None:
                off[v] = o
                changed = True
    return off


class Frame:
    def __init__(self, ssa, entry_abi="aapcs", skip_lr=True):
        self.ssa = ssa
        self.skip_lr = skip_lr
        self.entry_abi = entry_abi
        self.off = sp_offsets(ssa)
        self.useful = self._usefulness()
        self.skip_push = {}   # push addr -> set of regs not written
        self.skip_pop = {}    # pop addr -> set of regs not loaded
        self._slots()

    def live_at_return(self, func):
        lr = () if self.skip_lr else (14,)
        if func == self.ssa.prog.entry and self.entry_abi == "none":
            return (0,) + lr
        return (0,) + CALLEE_SAVED + lr

    def _usefulness(self):
        ssa = self.ssa
        useful = set()
        copies = {}  # value -> values that are plain copies of it
        for a, env in ssa.envs.items():
            x = ssa.prog.ins[a]
            if x.op == "mov" and isinstance(x.a, str) and not x.s:
                src = env.get(int(x.a[1:]))
                d = ssa.defval.get((a, x.rd))
                if src is not None and d is not None:
                    copies.setdefault(src, []).append(d)
                continue
            if x.op in ("ret", "pop_ret"):
                continue  # handled through ret_envs
            useful.update(env.values())
        for v in ssa.values:
            useful.update(v.links or [])
        for a, renv in ssa.ret_envs.items():
            func = ssa.func_of[renv[0]] if 0 in renv else None
            for r in self.live_at_return(func):
                if r in renv:
                    useful.add(renv[r])
        # backward closure through copies, phi and pi
        srcs = {}
        for v in ssa.values:
            if v.kind == "phi":
                for a in v.args.values():
                    srcs.setdefault(v, []).append(a)
            elif v.kind == "pi":
                srcs.setdefault(v, []).append(v.env["x"])
                if isinstance(v.env["b"], ra.Value):
                    useful.add(v.env["b"])
        for s, ds in copies.items():
            for d in ds:
                srcs.setdefault(d, []).append(s)
        work = list(useful)
        while work:
            v = work.pop()
            for s in srcs.get(v, []):
                if s not in useful:
                    useful.add(s)
                    work.append(s)
        return useful

    def _slots(self):
        ssa, off = self.ssa, self.off
        writers, readers, other = {}, {}, []
        for a, env in ssa.envs.items():
            x = ssa.prog.ins[a]
            sp = env.get(13)
            if x.op == "push" and sp in off:
                base = off[sp] - 4 * len(x.regs)
                for i, r in enumerate(x.regs):
                    writers.setdefault(base + 4 * i, []).append((a, r))
            elif x.op in ("pop", "pop_ret") and sp in off:
                for i, r in enumerate(x.regs):
                    v = ssa.defval.get((a, r))
                    readers.setdefault(off[sp] + 4 * i, []).append((a, r, v))
            elif x.mem is not None:
                bv = env.get(x.mem[0])
                if bv in off and x.mem[1] is None:
                    other.append(off[bv] + x.mem[2])
            elif x.op in ("ldm", "stm"):
                bv = env.get(x.rd)
                if bv in off:
                    other.extend(off[bv] + 4 * i for i in range(len(x.regs)))
        for o, ws in writers.items():
            rs = readers.get(o, [])
            if any(o - 3 <= p < o + 4 for p in other):
                continue
            if not self.skip_lr and any(r == 14 for _, r in ws):
                continue  # LR saving explicitly kept
            if all(v is None or v not in self.useful for _, _, v in rs):
                for a, r in ws:
                    self.skip_push.setdefault(a, set()).add(r)
                for a, r, _ in rs:
                    self.skip_pop.setdefault(a, set()).add(r)
