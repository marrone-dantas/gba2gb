"""Bit-width pruning (Phase 1, part B1).

Produces a `Plan` consumed by the narrowed backend (tools/backend/codegen.py):

* **Storage classes** (sound, default): each SSA value gets a storage width
  (1, 2 or 4 bytes) and an extension kind ('z' zero / 's' sign) from its PROVEN
  range. Values connected through phi/pi nodes form a *web* that shares one
  register slot, so the whole web uses the width of the join of its ranges.
  Invariant used by the backend: the low `n` bytes of the register slot hold the
  value; bytes above `n` are undefined and are re-materialized (zero/sign
  extension) by consumers that need them (ret, BL, push, word stores, wide ops).

* **Profile-guided mode** (`profile=...`, opt-in): instruction values whose
  OBSERVED class is narrower than their proven class are *assumed* to have the
  observed class; the range analysis is re-run with those assumptions and every
  assumed value gets a **runtime guard**: it is computed at full width and its
  upper bytes are checked against the assumed extension; a violation jumps to the
  runtime debug handler `GuardTrap` (HR_DONE = 2, guard id in HR_GUARD). The
  result therefore stays checkable: either the guards hold and the narrowed code
  is exact, or execution traps.

* **Dead-extension elimination / extension fusion**: `lsls rX, rY, #24` followed
  by `lsrs|asrs rX, rX, #24` (also #16) where the shifted value has no other use
  and no flag reader in between is fused into one zero/sign extension of the low
  byte/halfword of rY (`uxtb/sxtb/uxth/sxth` pseudo-ops); the LSL is deleted. When
  rY is already proven inside the extension range, the pair is *dead*: it becomes
  a plain copy (or nothing when rX == rY).

* **Q16.16 -> Q8.8 requantization** (`requantize_q88`, explicit opt-in; CHANGES
  SEMANTICS): detects fixed-point webs (values flowing through add/sub/mov/neg/
  phi/compare into an `asr #16` "to integer" site), divides every constant of the
  web by 256 and turns the `asr #16` sites into `asr #8`. The result is a patched
  ELF; precision loss must be validated separately (tests/test_physics_q88.py).
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
from dataclasses import dataclass, field
from tools.lift.lift import lift_file
from tools.prune import range_analysis as ra

CLASS_RANGE = {"u8": ra.urange(0, 0xFF), "i8": ra.srange(-128, 127),
               "u16": ra.urange(0, 0xFFFF), "i16": ra.srange(-32768, 32767)}
STORAGE = {"u8": (1, "z"), "i8": (1, "s"), "u16": (2, "z"), "i16": (2, "s"), "i32": (4, "z"), None: (4, "z")}
WIDTH_ORDER = {"u8": 1, "i8": 1, "u16": 2, "i16": 2, "i32": 4, None: 4}


@dataclass
class Plan:
    ssa: ra.SSAProgram
    mode: str = "sound"
    storage: dict = field(default_factory=dict)    # Value -> (nbytes, 'z'|'s')
    guards: dict = field(default_factory=dict)     # Value -> class name
    fused: dict = field(default_factory=dict)      # addr -> (kind, src_reg, dead)
    deleted: set = field(default_factory=set)      # addresses of removed instructions
    fused_src: dict = field(default_factory=dict)  # addr -> source Value of a fused extension
    frame: object = None                           # tools.prune.frame.Frame (save-slot elision)
    opts: dict = field(default_factory=dict)

    def store(self, v):
        return self.storage.get(v, (4, "z"))

    def summary(self):
        vals = ra.counted(self.ssa)
        by = {1: 0, 2: 0, 4: 0}
        for v in vals:
            by[self.store(v)[0]] += 1
        return {"mode": self.mode, "values": len(vals), "bytes1": by[1], "bytes2": by[2], "bytes4": by[4],
                "guards": len(self.guards), "fused_ext": sum(not d for _, _, d in self.fused.values()),
                "dead_ext": sum(d for _, _, d in self.fused.values()),
                "reg_bytes_before": 4 * len(vals), "reg_bytes_after": sum(self.store(v)[0] for v in vals)}


# ---------------------------------------------------------------- webs
class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] is not x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def live_values(ssa):
    """Values read by some instruction (or interprocedural link), plus the phi/pi
    values that transitively feed them. Dead phis do not constrain storage."""
    live = set()
    for env in ssa.envs.values():
        live.update(env.values())
    for v in ssa.values:
        live.update(v.links or [])
    work = list(live)
    while work:
        v = work.pop()
        srcs = list(v.args.values()) if v.kind == "phi" else ([v.env["x"]] if v.kind == "pi" else [])
        if v.kind == "pi" and isinstance(v.env["b"], ra.Value):
            srcs.append(v.env["b"])
        for a in srcs:
            if a not in live:
                live.add(a)
                work.append(a)
    return live


def webs(ssa):
    uf = UF()
    live = live_values(ssa)
    for v in ssa.values:
        uf.find(v)
        if v not in live:
            continue
        if v.kind == "phi":
            for a in v.args.values():
                uf.union(v, a)
        elif v.kind == "pi":
            uf.union(v, v.env["x"])
    groups = {}
    for v in ssa.values:
        groups.setdefault(uf.find(v), []).append(v)
    return list(groups.values())


def users_map(ssa):
    users = {v: [] for v in ssa.values}
    for v in ssa.values:
        for d in list(v.env.values()) + list(v.args.values()) + list(v.links or []):
            if isinstance(d, ra.Value):
                users[d].append(v)
    return users


def instr_users(ssa, v):
    """Addresses of instructions that read value v (from the per-instruction envs)."""
    return [a for a, env in ssa.envs.items() if v in env.values()]


# ---------------------------------------------------------------- storage
def assign_storage(plan: Plan):
    for web in webs(plan.ssa):
        r = None
        forced = False
        for v in web:
            if v.proven is None:
                continue
            r = ra.join(r, v.proven)
            if v.kind == "param" or v.reg in (13, 14, 15) or (v.ins is not None and v.ins.op in ("bl", "pop", "pop_ret", "ldm")):
                forced = True
        n, ext = (4, "z") if forced else STORAGE[ra.width_class(r)]
        for v in web:
            plan.storage[v] = (n, ext)


# ---------------------------------------------------------------- extension fusion
def fuse_extensions(plan: Plan):
    prog, ssa = plan.ssa.prog, plan.ssa
    for f in ssa.funcs.values():
        for n in f.g:
            ins = f.g.nodes[n]["ins"]
            for j, x2 in enumerate(ins):
                if x2.op not in ("lsr", "asr") or not isinstance(x2.b, int) or x2.b not in (16, 24):
                    continue
                v1 = ssa.envs[x2.addr].get(int(x2.a[1:]))
                if v1 is None or v1.kind != "ins" or v1.ins.op != "lsl" or v1.ins.b != x2.b:
                    continue
                x1 = v1.ins
                if x1 not in ins or x1.addr in plan.deleted:
                    continue
                i1 = ins.index(x1)
                between = ins[i1 + 1:j]
                if any(b.op in ("bcc", "adc", "sbc") for b in between):
                    continue  # a flag reader sees the LSL flags
                if instr_users(ssa, v1) != [x2.addr]:
                    continue
                if any(u.kind == "phi" and v1 in u.args.values() for u in ssa.values):
                    continue
                v0 = ssa.envs[x1.addr].get(int(x1.a[1:]))
                if v0 is None:
                    continue
                if any(v0.reg in ra.defs(b) for b in between):
                    continue  # source register overwritten before the extension
                k = x2.b
                kind = ("u" if x2.op == "lsr" else "s") + ("xtb" if k == 24 else "xth")
                lim = {"uxtb": "u8", "sxtb": "i8", "uxth": "u16", "sxth": "i16"}[kind]
                dead = v0.proven is not None and ra.meet(v0.proven, CLASS_RANGE[lim]) == v0.proven
                plan.fused[x2.addr] = (kind, v0.reg, dead)
                plan.fused_src[x2.addr] = v0
                plan.deleted.add(x1.addr)


# ---------------------------------------------------------------- driver
DEFAULT_OPTS = {"skip_lr": True, "entry_abi": "aapcs", "frame_trim": True, "hram_alloc": True}


def build_plan(elf_or_prog, profile=None, mode="sound", opts=None):
    """opts: skip_lr (Phase 1.5 item 1, default on): do not save LR on the emulated
    stack; entry_abi ("aapcs" | "none", item 2, opt-in "none"): the entry function
    need not preserve callee-saved registers."""
    opts = {**DEFAULT_OPTS, **(opts or {})}
    prog = lift_file(elf_or_prog) if isinstance(elf_or_prog, str) else elf_or_prog
    rename = {}
    if opts["hram_alloc"]:  # item 4: renames the IR in place (tools/prune/regalloc.py)
        from tools.prune.regalloc import allocate, translate_profile
        rename = allocate(prog, opts["entry_abi"], opts["skip_lr"])
        profile = translate_profile(profile, rename)
    ssa = ra.SSAProgram(prog)
    ra.analyze(ssa)
    plan = Plan(ssa=ssa, mode=mode, opts=opts)
    plan.rename = rename
    if mode == "profile":
        if profile is None:
            raise ValueError("profile-guided mode needs a profile")
        ra.merge_profile(ssa, profile)
        assume = {}
        for _ in range(3):
            changed = False
            for v in ssa.values:
                if v.kind != "ins" or v.observed is None or v in assume or v.reg in (13, 14):
                    continue
                if getattr(v, "observed_derived", False) or v.ins.op in ("bl", "pop", "pop_ret", "ldm"):
                    continue  # call results / restored caller registers: harness artifacts
                if v.ins.op == "mov" and isinstance(v.ins.a, str) and v.env.get(int(v.ins.a[1:])) is not None \
                        and v.env[int(v.ins.a[1:])].kind == "param":
                    continue  # plain copy of an incoming register (its value is the caller's)
                oc, pc = ra.width_class(v.observed), ra.width_class(v.proven)
                if WIDTH_ORDER[oc] < WIDTH_ORDER[pc]:
                    assume[v] = CLASS_RANGE[oc]
                    plan.guards[v] = oc
                    changed = True
            if not changed:
                break
            for v in ssa.values:
                v.proven = None
            ra.analyze(ssa, assume)
    assign_storage(plan)
    fuse_extensions(plan)
    if opts["skip_lr"] or opts["entry_abi"] != "aapcs" or opts["frame_trim"]:
        from tools.prune.frame import Frame
        plan.frame = Frame(ssa, opts["entry_abi"], opts["skip_lr"], opts["frame_trim"])
    return plan


# ---------------------------------------------------------------- Q16.16 -> Q8.8
FIXED_OPS = ("add", "sub", "mov", "cmp", "cmn")


def detect_q16(ssa):
    """Return (web_values, to_int_sites): the fixed-point web and the `asr #16`
    instructions that convert it to integers (heuristic, see module docstring)."""
    uf = UF()
    sites = []
    for v in ssa.values:
        uf.find(v)
        if v.kind == "phi":
            for a in v.args.values():
                uf.union(v, a)
        elif v.kind == "pi":
            uf.union(v, v.env["x"])
            if isinstance(v.env["b"], ra.Value):
                uf.union(v, v.env["b"])
    for a, env in ssa.envs.items():
        x = ssa.prog.ins[a]
        regs = [int(o[1:]) for o in (x.a, x.b) if isinstance(o, str)]
        vals = [env[r] for r in regs if r in env]
        if x.op in FIXED_OPS:
            d = ssa.defval.get((a, x.rd)) if x.rd is not None else None
            grp = vals + ([d] if d else [])
            for o in grp[1:]:
                uf.union(grp[0], o)
        elif x.op == "asr" and isinstance(x.b, int) and x.b != 16 and vals:
            d = ssa.defval.get((a, x.rd))
            if d:
                uf.union(d, vals[0])  # v >> k keeps the Q format (scaling by 2^-k)
    for a, env in ssa.envs.items():
        x = ssa.prog.ins[a]
        if x.op == "asr" and x.b == 16:
            src = env.get(int(x.a[1:]))
            if src is not None and not (src.kind == "ins" and src.ins.op == "lsl" and src.ins.b == 16):
                sites.append((x, src))
    roots = {uf.find(s) for _, s in sites}
    web = [v for v in ssa.values if uf.find(v) in roots]
    return web, [x for x, _ in sites]


def requantize_q88(elf, out_elf):
    """Patch a copy of `elf`: Q16.16 constants of the detected web -> Q8.8, asr #16 -> #8.
    Returns a dict describing every patch."""
    from elftools.elf.elffile import ELFFile
    prog = lift_file(elf)
    ssa = ra.SSAProgram(prog)
    web, sites = detect_q16(ssa)
    with open(elf, "rb") as fh:
        text = ELFFile(fh).get_section_by_name(".text")
        toff, tbase = text["sh_offset"], text["sh_addr"]
    shutil.copy(elf, out_elf)
    patches = []
    data = bytearray(open(out_elf, "rb").read())

    def hw(addr):
        o = toff + addr - tbase
        return o, data[o] | data[o + 1] << 8

    def put(addr, val):
        o = toff + addr - tbase
        data[o], data[o + 1] = val & 0xFF, val >> 8

    done = set()
    for v in web:
        if v.kind != "ins" or v.ins.addr in done:
            continue
        x = v.ins
        if x.op == "mov" and isinstance(x.a, int):
            c = x.a - (1 << 32) if x.a & 0x80000000 else x.a
            if x.lit is not None:
                if c % 256:
                    raise ValueError(f"constant {c} at {x.addr:#x} is not representable in Q8.8")
                o = toff + x.lit - tbase
                data[o:o + 4] = ((c >> 8) & 0xFFFFFFFF).to_bytes(4, "little")
                patches.append(f"{x.addr:#x}: literal {c} -> {c >> 8}")
            elif c:
                # movs rd, #imm used through a following `lsls rd, rd, #k` (constant synthesis)
                users = [u for u in ssa.values if u.kind == "ins" and v in u.env.values()]
                raise ValueError(f"bare Q16.16 immediate {c} at {x.addr:#x} not supported ({users})")
            done.add(x.addr)
        elif x.op == "lsl" and isinstance(x.b, int):
            src = ssa.envs[x.addr].get(int(x.a[1:]))
            if not (src and src.kind == "ins" and src.ins.op == "mov" and isinstance(src.ins.a, int) and src.ins.lit is None):
                continue
            value = src.ins.a << x.b
            if value % 256:
                raise ValueError(f"constant {value} at {x.addr:#x} is not representable in Q8.8")
            nv = value >> 8
            k = max(0, x.b - 8)
            imm = nv >> k
            while imm << k != nv or imm > 255:
                k -= 1
                imm = nv >> k
                if k < 0:
                    raise ValueError(f"cannot re-encode constant {nv}")
            o, h = hw(src.ins.addr)
            put(src.ins.addr, (h & 0xFF00) | imm)
            o, h = hw(x.addr)
            put(x.addr, (h & ~(0x1F << 6)) | (k << 6))
            patches.append(f"{src.ins.addr:#x}/{x.addr:#x}: {value} -> {nv} (movs #{imm}; lsls #{k})")
            done.update((x.addr, src.ins.addr))
        elif x.op in ("add", "sub", "cmp") and isinstance(x.b, int) and x.b:
            raise ValueError(f"immediate operand {x.b} in fixed-point op at {x.addr:#x} not supported")
    for x in sites:
        o, h = hw(x.addr)
        put(x.addr, (h & ~(0x1F << 6)) | (8 << 6))
        patches.append(f"{x.addr:#x}: asr #16 -> asr #8")
    open(out_elf, "wb").write(data)
    return {"web_values": len(web), "to_int_sites": [hex(x.addr) for x in sites], "patches": patches}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("elf")
    ap.add_argument("--profile-guided", metavar="PROFILE_JSON")
    ap.add_argument("--requant-q88", metavar="OUT_ELF", help="write a Q8.8-requantized ELF (changes semantics)")
    a = ap.parse_args(argv)
    if a.requant_q88:
        print(json.dumps(requantize_q88(a.elf, a.requant_q88), indent=1))
        return
    prof = json.load(open(a.profile_guided)) if a.profile_guided else None
    plan = build_plan(a.elf, prof, "profile" if prof else "sound")
    print(json.dumps(plan.summary(), indent=1))


if __name__ == "__main__":
    main()
