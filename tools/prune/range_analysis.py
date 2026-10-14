"""Static range analysis (Phase 1, part A2).

1. Converts the lifted IR of every function into SSA (Cytron et al.: phi placement
   on dominance frontiers, renaming over the dominator tree; NetworkX provides
   dominators/frontiers).
2. Propagates intervals over the SSA graph with a worklist. Each value carries TWO
   intervals that are sound independently and are cross-reduced:
     u = [ulo, uhi] as unsigned 32-bit,  s = [slo, shi] as signed 32-bit.
   Transfer functions cover constants, ADD/SUB/MUL (when they cannot wrap), AND/BIC
   masks, ORR/EOR (bit-length bound), LSL/LSR/ASR by constants and registers, MVN/NEG
   and the narrow loads (LDRB/LDRH/LDRSB/LDRSH). Zero/sign-extension pairs
   (`lsls #24; lsrs/asrs #24`) fall out of the LSR/ASR rules. Loops terminate through
   widening on values that keep changing (jump to the 32-bit bounds). Branch
   conditions refine ranges through pi-nodes (e-SSA): on an edge P->B where B has P
   as its only predecessor and P ends with `cmp rX, <op>; b<cc>`, a pi value for rX
   with the condition's constraint is inserted at the start of B.
3. Merges a dynamic profile (docs/profile_format.md): every value gets
   `proven_range` (static, SOUND) and `observed_range` (dynamic, a HINT) separately.

CLI: python -m tools.prune.range_analysis [KERNEL.elf ...] [--profiles build/profiles]
     prints the per-kernel width table and writes build/ranges/<kernel>.json.
"""
from __future__ import annotations
import argparse
import glob
import json
import os
from dataclasses import dataclass, field
import networkx as nx
from tools.lift.lift import Program, Ins, lift_file
from tools.lift.defuse import defs, uses

M32 = 0xFFFFFFFF
SMIN, SMAX = -(1 << 31), (1 << 31) - 1
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------- intervals
# A range is a tuple (ulo, uhi, slo, shi); None means bottom (no value yet).
TOP = (0, M32, SMIN, SMAX)


def norm(r):
    """Cross-reduce the unsigned and signed views (both stay sound)."""
    if r is None:
        return None
    ulo, uhi, slo, shi = r
    if ulo > uhi or slo > shi:
        return r
    # signed range entirely non-negative -> same unsigned range
    if slo >= 0:
        ulo, uhi = max(ulo, slo), min(uhi, shi)
    elif shi < 0:  # entirely negative -> unsigned [slo+2^32, shi+2^32]
        ulo, uhi = max(ulo, slo + (1 << 32)), min(uhi, shi + (1 << 32))
    if uhi <= SMAX:
        slo, shi = max(slo, ulo), min(shi, uhi)
    elif ulo > SMAX:
        slo, shi = max(slo, ulo - (1 << 32)), min(shi, uhi - (1 << 32))
    return (ulo, uhi, slo, shi)


def const(v):
    v &= M32
    s = v - (1 << 32) if v > SMAX else v
    return (v, v, s, s)


def urange(lo, hi):
    return norm((lo, hi, SMIN, SMAX)) if 0 <= lo <= hi <= M32 else TOP


def srange(lo, hi):
    return norm((0, M32, lo, hi)) if SMIN <= lo <= hi <= SMAX else TOP


def meet(a, b):
    """Intersection of two sound ranges (both describe the same value).
    Returns None (bottom) when empty, i.e. the program point is unreachable."""
    if a is None or b is None:
        return None
    r = norm((max(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), min(a[3], b[3])))
    return r if r[0] <= r[1] and r[2] <= r[3] else None


def join(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), max(a[3], b[3]))


def widen(old, new):
    if old is None:
        return new
    return norm((0 if new[0] < old[0] else old[0], M32 if new[1] > old[1] else old[1],
                 SMIN if new[2] < old[2] else old[2], SMAX if new[3] > old[3] else old[3]))


def bitlen_mask(x):
    return (1 << x.bit_length()) - 1


def t_add(a, b):
    u = urange(a[0] + b[0], a[1] + b[1]) if a[1] + b[1] <= M32 else TOP
    s = srange(a[2] + b[2], a[3] + b[3]) if SMIN <= a[2] + b[2] and a[3] + b[3] <= SMAX else TOP
    return meet(u, s)


def t_sub(a, b):
    u = urange(a[0] - b[1], a[1] - b[0]) if a[0] - b[1] >= 0 else TOP
    s = srange(a[2] - b[3], a[3] - b[2]) if SMIN <= a[2] - b[3] and a[3] - b[2] <= SMAX else TOP
    return meet(u, s)


def t_mul(a, b):
    u = urange(a[0] * b[0], a[1] * b[1]) if a[1] * b[1] <= M32 else TOP
    ps = [x * y for x in (a[2], a[3]) for y in (b[2], b[3])]
    s = srange(min(ps), max(ps)) if SMIN <= min(ps) and max(ps) <= SMAX else TOP
    return meet(u, s)


def t_and(a, b):
    return urange(0, min(a[1], b[1]))


def t_orr(a, b):
    return urange(max(a[0], b[0]), bitlen_mask(max(a[1], b[1])))


def t_eor(a, b):
    return urange(0, bitlen_mask(max(a[1], b[1])))


def t_lsl(a, b):
    if b[0] != b[1]:
        return TOP
    k = b[0] & 0xFF
    if k >= 32:
        return const(0)
    u = urange(a[0] << k, a[1] << k) if a[1] << k <= M32 else TOP
    s = srange(a[2] << k, a[3] << k) if SMIN <= a[2] << k and a[3] << k <= SMAX else TOP
    return meet(u, s)


def t_lsr(a, b):
    klo, khi = (b[0], b[1]) if b[1] <= 255 else (0, 255)
    return urange(a[0] >> min(khi, 32), a[1] >> min(klo, 32))


def t_asr(a, b):
    klo, khi = (b[0], b[1]) if b[1] <= 255 else (0, 255)
    klo, khi = min(klo, 31), min(khi, 31)
    lo = min(a[2] >> klo, a[2] >> khi)
    hi = max(a[3] >> klo, a[3] >> khi)
    return srange(lo, hi)


def t_mvn(a):
    return urange(M32 - a[1], M32 - a[0])


LOADS = {"ldrb": urange(0, 0xFF), "ldrh": urange(0, 0xFFFF),
         "ldrsb": srange(-128, 127), "ldrsh": srange(-32768, 32767)}
BINOPS = {"add": t_add, "sub": t_sub, "mul": t_mul, "and": t_and, "orr": t_orr,
          "eor": t_eor, "lsl": t_lsl, "lsr": t_lsr, "asr": t_asr,
          "bic": lambda a, b: urange(0, a[1])}


def width_class(r):
    """Narrowest container: u8, i8, u16, i16 or i32."""
    if r is None:
        return None
    ulo, uhi, slo, shi = r
    if uhi <= 0xFF:
        return "u8"
    if -128 <= slo and shi <= 127:
        return "i8"
    if uhi <= 0xFFFF:
        return "u16"
    if -32768 <= slo and shi <= 32767:
        return "i16"
    return "i32"


def bucket(cls):
    return {"u8": "8", "i8": "8", "u16": "16", "i16": "16", "i32": "32"}.get(cls)


NEG = {"eq": "ne", "ne": "eq", "cs": "cc", "cc": "cs", "hi": "ls", "ls": "hi",
       "ge": "lt", "lt": "ge", "gt": "le", "le": "gt", "mi": "pl", "pl": "mi",
       "vs": "vc", "vc": "vs"}


def constraint(cond, b):
    """Range of x given that `cmp x, y` followed by b<cond> holds, y in range b."""
    if b is None:
        return None
    ulo, uhi, slo, shi = b
    c = {"eq": (ulo, uhi, slo, shi), "cs": (ulo, M32, SMIN, SMAX), "hi": (ulo + 1, M32, SMIN, SMAX),
         "cc": (0, uhi - 1, SMIN, SMAX), "ls": (0, uhi, SMIN, SMAX),
         "ge": (0, M32, slo, SMAX), "gt": (0, M32, slo + 1, SMAX),
         "lt": (0, M32, SMIN, shi - 1), "le": (0, M32, SMIN, shi)}.get(cond)
    if c is None:
        return TOP
    if c[0] > c[1] or c[2] > c[3]:
        return None  # e.g. x <u 0: edge never taken
    return norm(c)


# ---------------------------------------------------------------- SSA
@dataclass(eq=False)
class Value:
    id: int
    reg: int
    kind: str              # 'param' | 'phi' | 'ins' | 'pi'
    block: int
    ins: Ins | None = None
    env: dict = field(default_factory=dict)    # reg -> Value used by `ins`
    args: dict = field(default_factory=dict)   # phi: pred block -> Value
    cond: str | None = None                    # pi: condition, env['b'] = other operand
    links: list | None = None                  # interprocedural sources (see _link_calls)
    proven: tuple | None = None
    observed: tuple | None = None

    @property
    def key(self):
        return f"{self.ins.addr:#010x}:r{self.reg}" if self.ins else None

    def __repr__(self):
        where = f"@{self.ins.addr:#x}" if self.ins else f"{self.kind}@{self.block:#x}"
        return f"v{self.id}(r{self.reg} {where})"


class SSAFunction:
    def __init__(self, prog: Program, entry: int, counter):
        self.prog, self.entry = prog, entry
        nodes = nx.descendants(prog.cfg, entry) | {entry}
        self.g = prog.cfg.subgraph(nodes).copy()
        self.values: list[Value] = []
        self.envs: dict[int, dict] = {}     # instruction address -> reg -> Value used
        self.ret_vals: list[Value] = []     # r0 value at every return
        self.calls: list[Ins] = []          # BL instructions in this function
        self._next = counter
        self._build()

    def _new(self, **kw):
        v = Value(id=next(self._next), **kw)
        self.values.append(v)
        return v

    def _build(self):
        g, entry = self.g, self.entry
        idom = nx.immediate_dominators(g, entry)
        df = nx.dominance_frontiers(g, entry)
        tree = {n: [] for n in g}
        for n, d in idom.items():
            if n != d:
                tree[d].append(n)
        blk = lambda n: g.nodes[n]["ins"]
        defsites = {}
        for n in g:
            for x in blk(n):
                for r in defs(x):
                    defsites.setdefault(r, set()).add(n)
        phis = {n: {} for n in g}
        for r, sites in defsites.items():
            work, placed = list(sites), set()
            while work:
                n = work.pop()
                for y in df[n]:
                    if y not in placed:
                        placed.add(y)
                        phis[y][r] = self._new(reg=r, kind="phi", block=y)
                        if y not in sites:
                            work.append(y)
        refine = self._refinements()
        stacks = {r: [self._new(reg=r, kind="param", block=entry)] for r in range(15)}
        self.params = {r: s[0] for r, s in stacks.items()}

        def rename(n):
            pushed = []
            for r, v in phis[n].items():
                stacks[r].append(v)
                pushed.append(r)
            preds = list(g.predecessors(n))
            if len(preds) == 1:
                for r, cond, cmp_x in refine.get((preds[0], n), []):
                    v = self._pi(r, cond, cmp_x, n, stacks)
                    if v is not None:
                        stacks[r].append(v)
                        pushed.append(r)
            for x in blk(n):
                env = {r: stacks[r][-1] for r in uses(x) if r in stacks}
                self.envs[x.addr] = env
                if x.op in ("ret", "pop_ret") and 0 in env:
                    self.ret_vals.append(env[0])
                if x.op == "bl":
                    self.calls.append(x)
                for r in defs(x):
                    if r == 15:
                        continue
                    v = self._new(reg=r, kind="ins", block=n, ins=x, env=env)
                    stacks[r].append(v)
                    pushed.append(r)
            for s in g.successors(n):
                edge_pi = {}
                if g.in_degree(s) > 1:  # refine the phi argument on this edge
                    for r, cond, cmp_x in refine.get((n, s), []):
                        if r in phis[s]:
                            edge_pi[r] = self._pi(r, cond, cmp_x, n, stacks)
                for r, v in phis[s].items():
                    v.args[n] = edge_pi.get(r) or stacks[r][-1]
            for c in tree[n]:
                rename(c)
            for r in pushed:
                stacks[r].pop()

        rename(entry)

    def _pi(self, r, cond, cmp_x, block, stacks):
        """pi value: stacks[r] restricted by `cmp r, y` + condition."""
        src = stacks[r][-1]
        b = cmp_x.b
        b = stacks[int(b[1:])][-1] if isinstance(b, str) else b
        return self._new(reg=r, kind="pi", block=block, cond=cond, env={"x": src, "b": b})

    def _refinements(self):
        """(pred, succ) -> [(reg, cond, cmp_ins)] for edges guarded by `cmp rX, y; b<cc>`.
        Only when the cmp operand is not redefined between the cmp and the branch."""
        g, out = self.g, {}
        for p in g:
            ins = g.nodes[p]["ins"]
            br = ins[-1]
            if br.op != "bcc":
                continue
            cmp_x = None
            for x in reversed(ins[:-1]):
                if x.s:
                    cmp_x = x if x.op == "cmp" else None
                    break
            if cmp_x is None or not isinstance(cmp_x.a, str):
                continue
            ra = int(cmp_x.a[1:])
            after = ins[ins.index(cmp_x) + 1:-1]
            if any(ra in defs(x) or (isinstance(cmp_x.b, str) and int(cmp_x.b[1:]) in defs(x)) for x in after):
                continue
            fall = br.addr + br.size
            for succ in g.successors(p):
                if succ == br.target and succ == fall:
                    continue
                cond = br.cond if succ == br.target else NEG[br.cond]
                out.setdefault((p, succ), []).append((ra, cond, cmp_x))
        return out


class SSAProgram:
    def __init__(self, prog: Program):
        import itertools
        self.prog = prog
        cnt = itertools.count()
        self.funcs = {f: SSAFunction(prog, f, cnt) for f in sorted(prog.funcs)}
        self.values = [v for f in self.funcs.values() for v in f.values]
        self.envs = {a: e for f in self.funcs.values() for a, e in f.envs.items()}
        self.defval = {(v.ins.addr, v.reg): v for v in self.values if v.kind == "ins"}
        self._link_calls()

    def _link_calls(self):
        """Interprocedural links for direct BL calls (B0): callee parameters r0-r3
        are the join of the arguments at every call site, and the r0 produced by a
        BL is the join of the callee's returned r0. The program entry keeps TOP
        parameters (called from outside)."""
        sites = {}
        for f in self.funcs.values():
            for x in f.calls:
                sites.setdefault(x.target, []).append(self.envs[x.addr])
                ret = self.defval.get((x.addr, 0))
                if ret is not None and x.target in self.funcs:
                    ret.links = list(self.funcs[x.target].ret_vals)
        for fa, f in self.funcs.items():
            if fa == self.prog.entry or fa not in sites:
                continue
            for r in range(4):
                f.params[r].links = [env[r] for env in sites[fa] if r in env]

    def by_key(self):
        return {v.key: v for v in self.values if v.key}


# ---------------------------------------------------------------- analysis
def operand(v: Value, x):
    if isinstance(x, int):
        return const(x)
    dv = v.env.get(int(x[1:]))
    return dv.proven if dv is not None else TOP


def transfer(v: Value):
    if v.links is not None:
        r = None
        for a in v.links:
            r = join(r, a.proven)
        return r if v.links else TOP
    if v.kind == "param":
        return TOP
    if v.kind == "pi":
        x = v.env["x"].proven
        b = v.env["b"]
        b = const(b) if isinstance(b, int) else (TOP if b is None else b.proven)
        if x is None or b is None:
            return None
        if v.cond == "ne" and b[0] == b[1]:  # x != k: shave a matching endpoint
            k = b[0]
            ulo, uhi = x[0] + (x[0] == k), x[1] - (x[1] == k)
            ks = b[2]
            slo, shi = x[2] + (x[2] == ks), x[3] - (x[3] == ks)
            return meet(x, norm((ulo, uhi, slo, shi))) if ulo <= uhi and slo <= shi else None
        return meet(x, constraint(v.cond, b))
    if v.kind == "phi":
        iv = induction(v)
        if iv is not None:
            return iv
        r = None
        for a in v.args.values():
            r = join(r, a.proven)
        return r
    x = v.ins
    op = x.op
    if op in LOADS and v.reg == x.rd:
        return LOADS[op]
    if v.reg != x.rd or op in ("bl", "ldr", "pop", "pop_ret", "ldm", "adc", "sbc", "ror"):
        return TOP
    if op == "mov":
        return operand(v, x.a)
    if op == "mvn":
        a = operand(v, x.a)
        return None if a is None else t_mvn(a)
    if op in BINOPS:
        a, b = operand(v, x.a), operand(v, x.b)
        if a is None or b is None:
            return None
        return BINOPS[op](a, b)
    return TOP


COND_EVAL = {
    "eq": lambda x, k, xs, ks: x == k, "ne": lambda x, k, xs, ks: x != k,
    "cs": lambda x, k, xs, ks: x >= k, "cc": lambda x, k, xs, ks: x < k,
    "hi": lambda x, k, xs, ks: x > k, "ls": lambda x, k, xs, ks: x <= k,
    "ge": lambda x, k, xs, ks: xs >= ks, "lt": lambda x, k, xs, ks: xs < ks,
    "gt": lambda x, k, xs, ks: xs > ks, "le": lambda x, k, xs, ks: xs <= ks,
}
IV_LIMIT = 4096


def _s(v):
    return v - (1 << 32) if v > SMAX else v


def induction(v: Value):
    """Exact range of a basic induction variable
        v = phi(c, pi_cond(v +/- step, k))     (c, step, k constants)
    i.e. a loop counter whose only back edge is guarded by `cmp v', #k; b<cond>`.
    The values are c, c+step, ... while cond(v') holds, so they are enumerated
    concretely (bounded by IV_LIMIT; returns None to fall back otherwise)."""
    if len(v.args) != 2:
        return None
    init = back = None
    for a in v.args.values():
        if a.kind == "ins" and a.ins.op == "mov" and isinstance(a.ins.a, int):
            init = a.ins.a & M32
        elif a.kind == "pi" and isinstance(a.env["b"], int):
            back = a
    if init is None or back is None or back.cond not in COND_EVAL:
        return None
    upd = back.env["x"]
    if upd.kind != "ins" or upd.ins.op not in ("add", "sub") or upd.env.get(
            int(upd.ins.a[1:]) if isinstance(upd.ins.a, str) else -1) is not v:
        return None
    if not isinstance(upd.ins.b, int):
        return None
    step = upd.ins.b if upd.ins.op == "add" else -upd.ins.b
    k = back.env["b"] & M32
    cond = COND_EVAL[back.cond]
    x, lo, hi, slo, shi = init, init, init, _s(init), _s(init)
    for _ in range(IV_LIMIT):
        nx_ = (x + step) & M32
        if not cond(nx_, k, _s(nx_), _s(k)):
            return norm((lo, hi, slo, shi))
        x = nx_
        lo, hi, slo, shi = min(lo, x), max(hi, x), min(slo, _s(x)), max(shi, _s(x))
    return None


WIDEN_AFTER = 3
GIVE_UP = 40


def analyze(ssa: SSAProgram, assume: dict | None = None):
    """Worklist interval propagation. `assume` maps Value -> range that is
    intersected into the value (used by profile-guided pruning; every assumed
    value must be protected by a runtime guard)."""
    assume = assume or {}
    users = {v: [] for v in ssa.values}
    for v in ssa.values:
        for d in list(v.env.values()) + list(v.args.values()) + list(v.links or []):
            if isinstance(d, Value):
                users[d].append(v)
    count = {v: 0 for v in ssa.values}
    work = list(ssa.values)
    inwork = set(work)
    while work:
        v = work.pop(0)
        inwork.discard(v)
        new = norm(transfer(v))
        if new is not None and (new[0] > new[1] or new[2] > new[3]):
            new = None
        if new is not None and v in assume:
            new = meet(new, assume[v])
        old = v.proven
        if new == old:
            continue
        count[v] += 1
        if count[v] > GIVE_UP:
            new = TOP
        elif count[v] > WIDEN_AFTER:
            new = widen(old, join(old, new))
        else:
            new = join(old, new) if v.kind == "phi" else new
        if new is not None and v in assume:  # assumptions survive widening
            new = meet(new, assume[v])
        if new == old:
            continue
        v.proven = new
        for u in users[v]:
            if u not in inwork:
                work.append(u)
                inwork.add(u)
    return ssa


def merge_profile(ssa: SSAProgram, profile: dict | None):
    if not profile:
        return
    keys = ssa.by_key()
    for k, st in profile["regs"].items():
        v = keys.get(k)
        if v is not None:
            v.observed = (st["umin"], st["umax"], st["smin"], st["smax"])
    # phi / pi values have no PC: derive their observed range from their inputs
    for _ in range(len(ssa.values)):
        changed = False
        for v in ssa.values:
            if v.kind == "pi":
                o = v.env["x"].observed
            elif v.kind == "phi":
                o = None
                for a in v.args.values():
                    o = join(o, a.observed)
            else:
                continue
            if o is not None and v.proven is not None:
                o = meet(o, v.proven) or o  # derived hint: clip to what is provable
            if o != v.observed:
                v.observed, v.observed_derived, changed = o, True, True
        if not changed:
            break

def analyze_file(elf, profile_path=None):
    ssa = analyze(SSAProgram(lift_file(elf)))
    if profile_path and os.path.exists(profile_path):
        merge_profile(ssa, json.load(open(profile_path)))
    return ssa


def counted(ssa):
    """SSA values reported in the width table: instruction and phi definitions of
    data registers (SP/LR, parameters, pi copies and BL call-clobber placeholders excluded)."""
    return [v for v in ssa.values if v.kind in ("ins", "phi") and v.reg not in (13, 14)
            and not (v.ins is not None and v.ins.op == "bl")]


def annotate(ssa):
    out = []
    for v in counted(ssa):
        out.append({
            "id": v.id, "reg": f"r{v.reg}", "kind": v.kind,
            "pc": f"{v.ins.addr:#010x}" if v.ins else None,
            "block": f"{v.block:#010x}", "text": v.ins.text if v.ins else "phi",
            "proven_range": None if v.proven is None else {
                "u": [v.proven[0], v.proven[1]], "s": [v.proven[2], v.proven[3]],
                "class": width_class(v.proven)},
            "observed_range": None if v.observed is None else {
                "u": [v.observed[0], v.observed[1]], "s": [v.observed[2], v.observed[3]],
                "class": width_class(v.observed),
                "derived": getattr(v, "observed_derived", False)},
        })
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("elfs", nargs="*")
    ap.add_argument("--profiles", default=os.path.join(ROOT, "build", "profiles"))
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "ranges"))
    a = ap.parse_args(argv)
    elfs = a.elfs or sorted(glob.glob(os.path.join(ROOT, "build", "kernels", "k*.elf")))
    os.makedirs(a.out, exist_ok=True)
    print("| kernel | SSA values | static 8 | static 16 | static 32 | dyn 8 | dyn 16 | dyn 32 | unobserved |")
    print("|---|---|---|---|---|---|---|---|---|")
    tot = [0] * 8
    for e in elfs:
        name = os.path.basename(e)[:-4]
        ssa = analyze_file(e, os.path.join(a.profiles, name + ".json"))
        vals = counted(ssa)
        st = [sum(bucket(width_class(v.proven)) == b for v in vals) for b in ("8", "16", "32")]
        dy = [sum(bucket(width_class(v.observed)) == b for v in vals) for b in ("8", "16", "32")]
        un = sum(v.observed is None for v in vals)
        row = [len(vals)] + st + dy + [un]
        tot = [t + r for t, r in zip(tot, row)]
        print(f"| {name} | " + " | ".join(map(str, row)) + " |")
        with open(os.path.join(a.out, name + ".json"), "w") as fh:
            json.dump({"kernel": name, "values": annotate(ssa)}, fh, indent=1)
    print("| **total** | " + " | ".join(map(str, tot)) + " |")


if __name__ == "__main__":
    main()
