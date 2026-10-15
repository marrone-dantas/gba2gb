"""Phase 0 frontend: decodes Thumb (ARM7TDMI) with Capstone, builds the CFG
(NetworkX) and produces a simple IR (one IR instruction per Thumb instruction).

Decoding is recursive from the entry points (FUNC symbols and BL targets),
which avoids decoding literal pools as code. PC-relative loads
(`ldr rX, [pc, #imm]`) are statically resolved to constants (``mov`` op)."""
from __future__ import annotations
import re
import struct
from dataclasses import dataclass, field
import capstone as cs
from capstone import arm as A
import networkx as nx
from elftools.elf.elffile import ELFFile

CONDS = {"eq", "ne", "hs", "lo", "cs", "cc", "mi", "pl", "vs", "vc",
         "hi", "ls", "ge", "lt", "gt", "le"}


class LiftError(Exception):
    pass


@dataclass
class Ins:
    """IR instruction.
    op: normalized mnemonic (no 's' suffix, no '.n'/'.w');
    s: updates flags; rd: destination; a/b: operands ('r<n>' or int immediate);
    mem: (base, index|None, disp) for LDR/STR; regs: list for PUSH/POP/LDM/STM;
    cond: Bcc condition; target: branch target."""
    addr: int
    size: int
    op: str
    text: str
    s: bool = False
    rd: int | None = None
    a: object = None
    b: object = None
    mem: tuple | None = None
    regs: list = field(default_factory=list)
    wb: bool = False
    cond: str | None = None
    target: int | None = None
    lit: int | None = None
    native: str | None = None     # Phase 5 B2: BL to a native SM83 helper

    @property
    def is_term(self):
        return self.op in ("b", "bcc", "ret")


class Image:
    def __init__(self, data: bytes, base: int, entries: dict[str, int], taken=None):
        self.data, self.base, self.entries = data, base, entries
        # Thumb functions whose address is stored as data (vtables, function pointers):
        # possible targets of indirect calls (Program._decode, tools/lift/icall.py)
        self.taken = set(taken or ())
        self.extra = []            # [(addr, bytes)] other allocated sections (jump tables)

    @classmethod
    def from_elf(cls, path):
        with open(path, "rb") as fh:
            elf = ELFFile(fh)
            text = elf.get_section_by_name(".text")
            data, base = text.data(), text["sh_addr"]
            entries, thumb = {}, set()
            for s in elf.get_section_by_name(".symtab").iter_symbols():
                if s["st_info"]["type"] == "STT_FUNC" and s["st_shndx"] != "SHN_UNDEF":
                    entries[s.name] = s["st_value"] & ~1
                    if s["st_value"] & 1 and base <= s["st_value"] < base + len(data):
                        thumb.add(s["st_value"])
            taken, extra = set(), []
            for sec in elf.iter_sections():
                if sec["sh_type"] == "SHT_PROGBITS" and sec["sh_flags"] & 2 and sec.name != ".text":
                    extra.append((sec["sh_addr"], sec.data()))
                if sec["sh_type"] == "SHT_PROGBITS" and sec["sh_flags"] & 2 and thumb:
                    d = sec.data()
                    for (w,) in struct.iter_unpack("<I", d[:len(d) & ~3]):
                        if w in thumb:
                            taken.add(w & ~1)
        img = cls(data, base, entries, taken)
        img.extra = extra
        return img

    @classmethod
    def from_bin(cls, path, base=0x08000000, entry=0x08000000):
        return cls(open(path, "rb").read(), base, {"f": entry})

    def word(self, addr):
        o = addr - self.base
        if 0 <= o <= len(self.data) - 4:
            return struct.unpack_from("<I", self.data, o)[0]
        for a, d in self.extra:
            if a <= addr <= a + len(d) - 4:
                return struct.unpack_from("<I", d, addr - a)[0]
        raise LiftError(f"no data at {addr:#x}")


def _reg(md, r):
    n = md.reg_name(r)
    return {"sb": 9, "sl": 10, "fp": 11, "ip": 12, "sp": 13, "lr": 14, "pc": 15}.get(
        n, int(n[1:]) if n[0] == "r" else None)


def _opnd(md, o):
    if o.type == A.ARM_OP_REG:
        return ("r", _reg(md, o.reg))
    if o.type == A.ARM_OP_IMM:
        return ("i", o.imm & 0xFFFFFFFF)
    if o.type == A.ARM_OP_MEM:
        idx = _reg(md, o.mem.index) if o.mem.index else None
        return ("m", (_reg(md, o.mem.base), idx, o.mem.disp))
    raise LiftError(f"unknown operand {o.type}")


def convert(md, img: Image, i) -> Ins:
    mn = i.mnemonic.split(".")[0]
    ops = [_opnd(md, o) for o in i.operands]
    ins = Ins(i.address, i.size, mn, f"{i.mnemonic} {i.op_str}")
    val = lambda o: o[1] if o[0] == "i" else f"r{o[1]}"
    base = mn
    if mn in ("push", "pop"):
        ins.regs = [o[1] for o in ops]
        if mn == "pop" and 15 in ins.regs:
            ins.regs.remove(15)
            if ins.regs:
                # pop {regs, pc}: emitted as pop + ret
                ins.op = "pop_ret"
            else:
                ins.op = "ret"
        return ins
    if mn in ("ldm", "ldmia", "stm", "stmia"):
        ins.op = "ldm" if mn.startswith("ld") else "stm"
        ins.rd = ops[0][1]
        ins.regs = [o[1] for o in ops[1:]]
        ins.wb = i.writeback or "!" in i.op_str
        return ins
    if mn == "bx":
        ins.op = "ret"  # Phase 0: every BX is treated as a return
        return ins
    if mn == "bl":
        ins.op, ins.target = "bl", ops[0][1]
        return ins
    if mn == "b":
        ins.op, ins.target = "b", ops[0][1]
        return ins
    if mn.startswith("b") and mn[1:] in CONDS:
        c = {"hs": "cs", "lo": "cc"}.get(mn[1:], mn[1:])
        ins.op, ins.cond, ins.target = "bcc", c, ops[0][1]
        return ins
    if mn == "nop":
        return ins
    if mn == "udf":            # __builtin_trap / unreachable: hang in place
        ins.op, ins.target = "b", i.address
        return ins
    if mn in ("svc", "swi"):  # BIOS call: handled by the GB HAL (tools/hal/intercept.py)
        ins.op, ins.a = "swi", ops[0][1]
        return ins
    if mn in ("ldr", "ldrb", "ldrh", "ldrsb", "ldrsh", "str", "strb", "strh"):
        rd, m = ops[0][1], ops[1][1]
        if mn == "ldr" and m[0] == 15:
            lit = ((i.address + 4) & ~3) + m[2]
            ins.op, ins.rd, ins.a = "mov", rd, img.word(lit)
            ins.lit = lit  # literal-pool address (used by Q-format requantization)
            return ins
        ins.rd, ins.mem = rd, m
        return ins
    # ALU / data processing
    flag_ops = {"movs": "mov", "mvns": "mvn", "adds": "add", "subs": "sub", "ands": "and",
                "eors": "eor", "orrs": "orr", "bics": "bic", "lsls": "lsl", "lsrs": "lsr",
                "asrs": "asr", "rors": "ror", "adcs": "adc", "sbcs": "sbc", "muls": "mul",
                "negs": "neg", "rsbs": "neg"}
    if mn in flag_ops:
        base, ins.s = flag_ops[mn], True
    elif mn in ("cmp", "cmn", "tst"):
        ins.s = True
    elif mn in ("mov", "add", "sub", "adr"):
        pass
    else:
        raise LiftError(f"unsupported instruction: {ins.text} @ {i.address:#x}")
    ins.op = base
    if base == "mov" and ops[0] == ("r", 15) and ops[1][0] == "r":
        if ops[1][1] == 14:
            ins.op = "ret"                 # mov pc, lr
        else:
            ins.op, ins.a = "ijmp", f"r{ops[1][1]}"   # resolved by Program._jump_table
        return ins
    if base == "adr":
        ins.op, ins.rd, ins.a = "mov", ops[0][1], ((i.address + 4) & ~3) + ops[1][1]
        return ins
    if base in ("cmp", "cmn", "tst"):
        ins.a, ins.b = val(ops[0]), val(ops[1])
        return ins
    if base in ("mov", "mvn", "neg"):
        ins.rd, ins.a = ops[0][1], val(ops[1])
        if base == "neg":
            ins.op, ins.a, ins.b = "sub", 0, val(ops[1])  # rsbs rd, rm, #0
        return ins
    ins.rd = ops[0][1]
    if len(ops) == 3:
        ins.a, ins.b = val(ops[1]), val(ops[2])
    else:
        ins.a, ins.b = f"r{ins.rd}", val(ops[1])
    if "pc" in (ins.a, ins.b) or ins.a == "r15" or ins.b == "r15":
        if ins.a == "r15" and isinstance(ins.b, int):  # add rd, pc, #imm
            ins.op, ins.a, ins.b = "mov", ((i.address + 4) & ~3) + ins.b, None
        else:
            raise LiftError(f"unsupported use of PC: {ins.text}")
    return ins


# Phase 5 B2: library helpers replaced by native SM83 routines (runtime/gb_softfloat.asm).
# A BL to one of these (directly, or through the linker's Thumb->ARM veneer
# `____<name>_from_thumb`) becomes `call NAT_<short>`; the helper body is not lifted.
NATIVES = {"__aeabi_dadd": "dadd", "__aeabi_dsub": "dsub", "__aeabi_dmul": "dmul",
           "__aeabi_i2d": "i2d", "__aeabi_f2d": "f2d", "__aeabi_d2f": "d2f",
           "__aeabi_f2iz": "f2iz", "__aeabi_i2f": "i2f", "__aeabi_fmul": "fmul",
           "__aeabi_fadd": "fadd", "__aeabi_fsub": "fsub", "__aeabi_fcmpeq": "fcmpeq",
           "__aeabi_fcmplt": "fcmplt", "__aeabi_fcmpgt": "fcmpgt", "__aeabi_idiv": "idiv",
           "__aeabi_idivmod": "idivmod", "__aeabi_lmul": "lmul",
           "__aeabi_uidiv": "uidiv", "__aeabi_uidivmod": "uidivmod"}


# Port overrides (docs/homebrew_port.md): {function name: native name}; a BL to the
# function (plain C name or its Itanium-mangled C++ name `_Z<len><name>...`) becomes
# `call NAT_<native>` (runtime/ports/*.asm). Set by gba2gbc_core.build(port=...).
EXTRA_NATIVES: dict[str, str] = {}
# Memoized map-pure functions {name: (id, param sizes)} (tools/lift/memo.py); set by
# gba2gbc_core.build for ports.
MEMO: dict[str, tuple] = {}
# Step 9 constant specialization (Program._specialize): a call site that passes
# constants in r0-r3 gets its own copy of the callee, so range analysis sees the
# exact argument values. Clone k lives at original + CLONE_DELTA + k * 16 MiB.
CLONE = {"enabled": False, "default": False, "max_ins": 160, "per_func": 4, "total": 48}
CLONE_DELTA = 0x08000000
# Step 10 render decimation (tools/lift/decimate.py): render every n-th frame.
DECIMATE = {"n": 1, "render": set()}
# Switch jump tables (Program._jump_table): compare chains at synthetic addresses.
JT_BASE = 0x0E000000
# Indirect calls (tools/lift/icall.py): `bl` to a `bx rN` stub becomes `call NAT_icall_rN`,
# a run-time dispatch over the functions whose address is taken (Image.taken).
ICALL = {"enabled": True}


def _override(name):
    if name in EXTRA_NATIVES:
        return EXTRA_NATIVES[name]
    m = re.match(r"_Z(\d+)", name)
    if m:
        n = int(m.group(1))
        base = name[m.end():m.end() + n]
        if base in EXTRA_NATIVES and len(base) == n:
            return EXTRA_NATIVES[base]
    return None


def native_targets(entries):
    """{address: short name} of the BL targets implemented natively."""
    out = {}
    for name, addr in entries.items():
        m = re.fullmatch(r"____(\w+)_from_thumb", name)
        base = "__" + m.group(1) if m else name
        if base in NATIVES:
            out[addr] = NATIVES[base]
        elif EXTRA_NATIVES and _override(name):
            out[addr] = _override(name)
    return out


class Program:
    """Lifting result: instructions by address, functions and CFG."""

    def __init__(self, img: Image, entry="f", natives=True):
        self.img = img
        self.md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB)
        self.md.detail = True
        self.ins: dict[int, Ins] = {}
        self.entry = img.entries[entry]
        self.natives = native_targets(img.entries) if natives else {}
        # Phase P1: idiom -> HAL lifting (tools/lift/idioms.py); GBA2GB_IDIOMS=0 disables
        import os
        self.idioms = natives and os.environ.get("GBA2GB_IDIOMS", "1") not in ("0", "")
        self.funcs = {self.entry}
        self.icalls = set()
        self.jtabs = []
        self.cfg = nx.DiGraph()
        self._decode()
        self.clones = {}
        if natives and CLONE["enabled"]:
            self._specialize()
        self._build_cfg()
        self.divc = set()
        self.decim = []
        if natives and DECIMATE["n"] > 1:
            from tools.lift import decimate
            self.decim = decimate.apply(self, DECIMATE["n"], DECIMATE["render"])
        self.memo_used = {}
        if natives and MEMO:
            self._memo()
        if natives and os.environ.get("GBA2GB_DIVC", "1") not in ("0", ""):
            self._const_div()

    def _decode_one(self, addr):
        o = addr - self.img.base
        if not 0 <= o < len(self.img.data):
            raise LiftError(f"address outside the image: {addr:#x}")
        i = next(self.md.disasm(self.img.data[o:o + 4], addr, 1), None)
        if i is None:
            raise LiftError(f"failed to decode at {addr:#x}")
        return convert(self.md, self.img, i)

    def _back(self, a, n=48):
        """Straight-line predecessors of a (already decoded), nearest first."""
        out = []
        for _ in range(n):
            prev = next((p for p in (a - 2, a - 4) if p in self.ins and p + self.ins[p].size == a), None)
            if prev is None or prev in self.funcs:
                if prev is not None:
                    out.append(self.ins[prev])
                break
            out.append(self.ins[prev])
            a = prev
        return out

    def _jump_table(self, x):
        """`ldr rT, [rB, rI]; mov pc, rT` (gcc Thumb-1 switch, rI = 4 * case, bounded by
        `cmp case, #N` + `bhi`/`bls`, rB = table address from a literal): the computed
        jump becomes `b` into a compare chain at a synthetic address (JT_BASE + k * 1 KiB)
        that branches to each case target. Returns the case targets."""
        t = int(x.a[1:])
        back = self._back(x.addr)
        ld = next((i for i in back if t in (i.rd,) and i.op != "cmp"), None)
        if ld is None or ld.op != "ldr" or not ld.mem or ld.mem[1] is None:
            raise LiftError(f"unresolved computed jump {x.text} @ {x.addr:#x}")
        rb, ri, _ = ld.mem
        f = max((fa for fa in self.funcs if fa <= x.addr), default=x.addr)

        def const_def(r, start, depth=0):
            """Nearest earlier definition of r by address within the function (the base
            is typically set before the switch's loop; the table contents are validated
            below); register copies are followed."""
            for a in range(start - 2, max(f, start - 0x1000) - 2, -2):
                i = self.ins.get(a)
                if i is None:
                    continue
                if i.op == "bl" or (i.op in ("pop", "ldm") and r in i.regs):
                    return None
                if i.rd == r and i.op not in ("cmp", "cmn", "tst", "str", "strb", "strh", "stm", "ldm"):
                    if i.op == "mov" and isinstance(i.a, int) and i.b is None:
                        return i.a
                    if i.op == "mov" and isinstance(i.a, str) and depth < 4:
                        return const_def(int(i.a[1:]), a, depth + 1)
                    return None
            return None
        base = const_def(rb, ld.addr)
        if base is None:
            rb, ri = ri, rb           # ldr rT, [rI, rB]
            base = const_def(rb, ld.addr)
        if base is None:
            raise LiftError(f"jump table base not constant @ {x.addr:#x}")
        n = None
        for k, i in enumerate(back):
            if i.op == "bcc" and i.cond in ("hi", "ls"):
                c = back[k + 1] if k + 1 < len(back) else None
                if c is not None and c.op == "cmp" and isinstance(c.b, int):
                    n = c.b + 1
                    break
        fend = min((e for e in self.img.entries.values() if e > x.addr), default=x.addr + 0x4000)
        inside = lambda w: f <= (w & ~1) < fend
        if n is None:
            # no explicit bound (index of an enum type): the entries that point into the
            # function, up to the first one that does not
            tg = []
            while len(tg) < 256:
                try:
                    w = self.img.word(base + 4 * len(tg))
                except LiftError:
                    break
                if not inside(w):
                    break
                tg.append(w)
            if not tg:
                raise LiftError(f"jump table bound not found @ {x.addr:#x}")
        else:
            if n > 512:
                raise LiftError(f"jump table too large @ {x.addr:#x}")
            tg = [self.img.word(base + 4 * k) for k in range(n)]
        if not all(inside(w) for w in tg):
            raise LiftError(f"jump table entries are not code of the function @ {x.addr:#x}")
        tg = [w & ~1 for w in tg]
        k = len(self.jtabs)
        sa = JT_BASE + 0x400 * k
        self.jtabs.append(x.addr)
        x.op, x.target, x.a = "b", sa, None
        # the table load becomes `mov rT, rI`: the chain compares the scaled index, so
        # the table itself is never read at run time
        ld.op, ld.a, ld.b, ld.mem = "mov", f"r{ri}", None, None
        ld.text += "  ; jump table index"
        for j, w in enumerate(tg[:-1]):
            a = sa + 4 * j
            self.ins[a] = Ins(a, 2, "cmp", f"cmp r{t}, #{4 * j}  ; jump table @{x.addr:#x}",
                              s=True, a=f"r{t}", b=4 * j)
            self.ins[a + 2] = Ins(a + 2, 2, "bcc", f"beq {w:#x}", cond="eq", target=w)
        a = sa + 4 * (len(tg) - 1)
        self.ins[a] = Ins(a, 2, "b", f"b {tg[-1]:#x}", target=tg[-1])
        return tg

    def _call_via(self, t):
        """Register of a `bx rN` call-via stub at t (Thumb-1 indirect call: `bl stub`
        with `stub: bx rN`), else None."""
        o = t - self.img.base
        if not 0 <= o < len(self.img.data) - 1:
            return None
        hw = struct.unpack_from("<H", self.img.data, o)[0]
        if hw & 0xFF87 == 0x4700:          # bx rm
            r = (hw >> 3) & 15
            if r not in (14, 15):
                return r
        return None

    def _decode(self):
        work = [self.entry]
        roots = False
        while work or (self.icalls and not roots):
            if not work:
                # indirect calls found: every function whose address is taken is a root
                roots = True
                for t in sorted(self.img.taken):
                    if t not in self.natives and t not in self.ins:
                        self.funcs.add(t)
                        work.append(t)
                continue
            a = work.pop()
            while a not in self.ins:
                x = self._decode_one(a)
                self.ins[a] = x
                if x.op == "ijmp":
                    work.extend(self._jump_table(x))
                if x.op == "bl" and ICALL["enabled"] and x.target not in self.natives:
                    r = self._call_via(x.target)
                    if r is not None:            # indirect call through rN
                        x.native, x.a, x.target = f"icall_r{r}", f"r{r}", None
                        self.icalls.add(r)
                if x.op == "bl" and x.native:
                    pass
                elif x.op == "bl" and x.target not in self.natives and self.idioms:
                    from tools.lift import idioms
                    o = x.target - self.img.base
                    if 0 <= o < len(self.img.data):
                        nm = idioms.match(self.md, self.img, x.target,
                                          lambda a, n: self.img.data[a - self.img.base:a - self.img.base + n])
                        if nm:
                            self.natives[x.target] = nm
                if x.op == "bl" and x.target is None:
                    pass
                elif x.op == "bl" and x.target in self.natives:
                    x.native = self.natives[x.target]
                elif x.op == "bl":
                    self.funcs.add(x.target)
                    work.append(x.target)
                if x.op in ("b", "bcc"):
                    work.append(x.target)
                if x.op in ("b", "ret", "pop_ret"):
                    break
                a += x.size

    def _const_args(self, bl, targets):
        """Registers r0-r3 holding a constant at `bl` (straight-line scan back)."""
        known, dead = {}, set()
        a = bl.addr
        for _ in range(10):
            prev = next((p for p in (a - 2, a - 4) if p in self.ins and p + self.ins[p].size == a), None)
            if prev is None or a in targets:
                break
            x = self.ins[prev]
            if x.op in ("b", "bcc", "bl", "ret", "pop_ret"):
                break
            from tools.lift.defuse import defs
            for r in defs(x):
                if r in (0, 1, 2, 3) and r not in known and r not in dead:
                    if x.op == "mov" and isinstance(x.a, int) and not x.s:
                        known[r] = x.a
                    elif x.op == "mov" and isinstance(x.a, int):
                        known[r] = x.a
                    else:
                        dead.add(r)
            a = prev
        return known

    def _body(self, entry):
        """Intraprocedural instruction addresses of the function at `entry`."""
        seen, work = set(), [entry]
        while work:
            a = work.pop()
            while a in self.ins and a not in seen:
                seen.add(a)
                x = self.ins[a]
                if x.op in ("b", "bcc"):
                    work.append(x.target)
                if x.op in ("b", "ret", "pop_ret"):
                    break
                a += x.size
        return seen

    def _specialize(self):
        import copy
        targets = {x.target for x in self.ins.values() if x.op in ("b", "bcc")}
        groups = {}
        for x in sorted(self.ins.values(), key=lambda i: i.addr):
            if x.op != "bl" or x.native is not None or x.target == self.entry:
                continue
            k = self._const_args(x, targets)
            if k:
                groups.setdefault((x.target, tuple(sorted(k.items()))), []).append(x)
        per, total = {}, 0
        for (fn, consts), sites in sorted(groups.items(), key=lambda g: -len(g[1])):
            if total >= CLONE["total"] or per.get(fn, 0) >= CLONE["per_func"]:
                continue
            body = self._body(fn)
            if len(body) > CLONE["max_ins"] or any(self.ins[a].op == "bl" and self.ins[a].target == fn
                                                     for a in body):
                continue  # too big or recursive
            per[fn] = per.get(fn, 0) + 1
            total += 1
            d = CLONE_DELTA + 0x01000000 * total
            for a in body:
                c = copy.copy(self.ins[a])
                c.addr = a + d
                if c.op in ("b", "bcc") and c.target in body:
                    c.target += d
                self.ins[c.addr] = c
            self.funcs.add(fn + d)
            for x in sites:
                x.target = fn + d
            self.clones[fn + d] = (fn, dict(consts))

    def _build_cfg(self):
        addrs = sorted(self.ins)
        leaders = set(self.funcs)
        for a in addrs:
            x = self.ins[a]
            if x.target is not None and x.op != "bl":
                leaders.add(x.target)
            if x.op in ("b", "bcc", "ret", "pop_ret", "bl"):
                leaders.add(a + x.size)
        self.leaders = leaders
        cur = None
        for a in addrs:
            if a in leaders or cur is None:
                cur = a
                self.cfg.add_node(cur, ins=[])
            x = self.ins[a]
            self.cfg.nodes[cur]["ins"].append(x)
            nxt = a + x.size
            if x.op in ("b", "bcc"):
                self.cfg.add_edge(cur, x.target)
            if x.op not in ("b", "ret", "pop_ret") and nxt in self.ins:
                if nxt in leaders:
                    self.cfg.add_edge(cur, nxt)

    def _memo(self):
        """Calls to map-pure functions go through the memo cache (tools/lift/memo.py)."""
        addr = {a & ~1: n for n, a in self.img.entries.items() if n in MEMO}
        for x in self.ins.values():
            if x.op == "bl" and x.native is None and x.target in addr:
                fid, ps = MEMO[addr[x.target]]
                x.native = f"memo_{fid}"
                self.memo_used[fid] = (f"L_{x.target:08X}", ps)

    def _const_div(self):
        """Step 7: a division helper call whose divisor r1 is a block-local constant
        becomes `call NAT_divc_<kind>_<d>` (ROM-table long division,
        tools/backend/divconst.py)."""
        from tools.backend.divconst import KINDS, eligible
        for n in self.cfg.nodes:
            r1 = None
            for x in self.cfg.nodes[n]["ins"]:
                if x.op == "bl":
                    if x.native in KINDS and eligible(r1):
                        x.native = f"divc_{x.native}_{r1}"
                        self.divc.add((x.native.split("_")[1], r1))
                    r1 = None
                elif x.op == "mov" and x.rd == 1 and isinstance(x.a, int) and x.b is None:
                    r1 = x.a
                elif x.op == "lsl" and x.rd == 1 and x.a == "r1" and isinstance(x.b, int) and r1 is not None:
                    r1 = (r1 << x.b) & 0xFFFFFFFF
                elif (x.rd == 1 and not x.op.startswith(("str", "cmp", "tst", "cmn", "b"))) or \
                        (1 in (x.regs or []) and x.op not in ("push", "stm")):
                    r1 = None

    def ordered(self):
        return [self.ins[a] for a in sorted(self.ins)]


def lift_file(path, entry="f", natives=True):
    img = Image.from_elf(path) if open(path, "rb").read(4) == b"\x7fELF" else Image.from_bin(path)
    return Program(img, entry, natives)


if __name__ == "__main__":
    import sys
    p = lift_file(sys.argv[1])
    print(f"{len(p.ins)} instructions, {p.cfg.number_of_nodes()} blocks, functions: "
          + ", ".join(hex(f) for f in sorted(p.funcs)))
    for x in p.ordered():
        tag = "L:" if x.addr in p.leaders else "  "
        print(f"{tag}{x.addr:08x} {x.text:28s} -> {x.op} s={int(x.s)} rd={x.rd} a={x.a} b={x.b} mem={x.mem} regs={x.regs} {x.cond or ''} {hex(x.target) if x.target else ''}")
