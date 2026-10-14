"""Phase 0 frontend: decodes Thumb (ARM7TDMI) with Capstone, builds the CFG
(NetworkX) and produces a simple IR (one IR instruction per Thumb instruction).

Decoding is recursive from the entry points (FUNC symbols and BL targets),
which avoids decoding literal pools as code. PC-relative loads
(`ldr rX, [pc, #imm]`) are statically resolved to constants (``mov`` op)."""
from __future__ import annotations
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

    @property
    def is_term(self):
        return self.op in ("b", "bcc", "ret")


class Image:
    def __init__(self, data: bytes, base: int, entries: dict[str, int]):
        self.data, self.base, self.entries = data, base, entries

    @classmethod
    def from_elf(cls, path):
        with open(path, "rb") as fh:
            elf = ELFFile(fh)
            text = elf.get_section_by_name(".text")
            data, base = text.data(), text["sh_addr"]
            entries = {}
            for s in elf.get_section_by_name(".symtab").iter_symbols():
                if s["st_info"]["type"] == "STT_FUNC" and s["st_shndx"] != "SHN_UNDEF":
                    entries[s.name] = s["st_value"] & ~1
        return cls(data, base, entries)

    @classmethod
    def from_bin(cls, path, base=0x08000000, entry=0x08000000):
        return cls(open(path, "rb").read(), base, {"f": entry})

    def word(self, addr):
        o = addr - self.base
        return struct.unpack_from("<I", self.data, o)[0]


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
    if mn in ("ldr", "ldrb", "ldrh", "ldrsb", "ldrsh", "str", "strb", "strh"):
        rd, m = ops[0][1], ops[1][1]
        if mn == "ldr" and m[0] == 15:
            lit = ((i.address + 4) & ~3) + m[2]
            ins.op, ins.rd, ins.a = "mov", rd, img.word(lit)
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


class Program:
    """Lifting result: instructions by address, functions and CFG."""

    def __init__(self, img: Image, entry="f"):
        self.img = img
        self.md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB)
        self.md.detail = True
        self.ins: dict[int, Ins] = {}
        self.entry = img.entries[entry]
        self.funcs = {self.entry}
        self.cfg = nx.DiGraph()
        self._decode()
        self._build_cfg()

    def _decode_one(self, addr):
        o = addr - self.img.base
        if not 0 <= o < len(self.img.data):
            raise LiftError(f"address outside the image: {addr:#x}")
        i = next(self.md.disasm(self.img.data[o:o + 4], addr, 1), None)
        if i is None:
            raise LiftError(f"failed to decode at {addr:#x}")
        return convert(self.md, self.img, i)

    def _decode(self):
        work = [self.entry]
        while work:
            a = work.pop()
            while a not in self.ins:
                x = self._decode_one(a)
                self.ins[a] = x
                if x.op == "bl":
                    self.funcs.add(x.target)
                    work.append(x.target)
                if x.op in ("b", "bcc"):
                    work.append(x.target)
                if x.op in ("b", "ret", "pop_ret"):
                    break
                a += x.size

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

    def ordered(self):
        return [self.ins[a] for a in sorted(self.ins)]


def lift_file(path, entry="f"):
    img = Image.from_elf(path) if open(path, "rb").read(4) == b"\x7fELF" else Image.from_bin(path)
    return Program(img, entry)


if __name__ == "__main__":
    import sys
    p = lift_file(sys.argv[1])
    print(f"{len(p.ins)} instructions, {p.cfg.number_of_nodes()} blocks, functions: "
          + ", ".join(hex(f) for f in sorted(p.funcs)))
    for x in p.ordered():
        tag = "L:" if x.addr in p.leaders else "  "
        print(f"{tag}{x.addr:08x} {x.text:28s} -> {x.op} s={int(x.s)} rd={x.rd} a={x.a} b={x.b} mem={x.mem} regs={x.regs} {x.cond or ''} {hex(x.target) if x.target else ''}")
