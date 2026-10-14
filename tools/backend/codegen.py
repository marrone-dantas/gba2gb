"""Phase 0 backend: Thumb IR -> RGBDS (SM83) assembly.

Each ARM register lives in HRAM (see docs/hram_map.md). 32-bit operations are
emitted inline byte by byte (using the SM83 carry chain); NZCV flags are
computed with ARM semantics. Shifts and MUL call runtime routines
(runtime/runtime.asm)."""
from __future__ import annotations
from tools.lift.lift import Program, LiftError

R = lambda n: 0xFF80 + 4 * n
FN, FZ, FC, FV = 0xFFC0, 0xFFC1, 0xFFC2, 0xFFC3
T0, T1, T2 = 0xFFC4, 0xFFC8, 0xFFCC
SP = R(13)


def h(x):
    return f"${x:04X}"


class Gen:
    def __init__(self, prog: Program, hal=None):
        self.p = prog
        self.out: list[str] = []
        self.hal = hal or {}  # addr -> access (tools/hal/intercept.py), Phase 2

    def e(self, *lines):
        self.out.extend("    " + l for l in lines)

    # ---- utilities ----
    def ldimm(self, dst, v):
        v &= 0xFFFFFFFF
        for i in range(4):
            self.e(f"ld a, ${(v >> 8 * i) & 0xFF:02X}", f"ldh [{h(dst + i)}], a")

    def copy(self, dst, src):
        if dst == src:
            return
        for i in range(4):
            self.e(f"ldh a, [{h(src + i)}]", f"ldh [{h(dst + i)}], a")

    def src(self, x, tmp):
        """Return the HRAM address of the operand (register, or immediate placed in tmp)."""
        if isinstance(x, str):
            return R(int(x[1:]))
        self.ldimm(tmp, x)
        return tmp

    def hl_from(self, addr):
        """hl = $C000 | (value32[addr] & $0FFF)  (docs/memory_map.md)"""
        self.e(f"ldh a, [{h(addr + 1)}]", "and $0F", "or $C0", "ld h, a",
               f"ldh a, [{h(addr)}]", "ld l, a")

    def addsub(self, op, A, B, dst, flags):
        mn = {"add": ("add", "adc"), "adc": ("adc", "adc"),
              "sub": ("sub", "sbc"), "sbc": ("sbc", "sbc")}[op]
        self.e(f"ld hl, {h(B)}")
        if op == "adc":
            self.e(f"ldh a, [{h(FC)}]", "rrca")
        elif op == "sbc":
            self.e(f"ldh a, [{h(FC)}]", "xor 1", "rrca")
        for i in range(4):
            self.e(f"ldh a, [{h(A + i)}]", f"{mn[0] if i == 0 else mn[1]} a, [hl]",
                   f"ldh [{h(dst + i)}], a")
            if i < 3:
                self.e("inc l")
        if flags:
            if self.need("C"):
                self.e("ld a, 0", "rla")
                if op in ("sub", "sbc"):
                    self.e("xor 1")  # ARM C = !borrow
                self.e(f"ldh [{h(FC)}], a")
            if self.need("V"):
                self.e(f"ldh a, [{h(A + 3)}]", "ld d, a", f"ldh a, [{h(B + 3)}]", "ld e, a",
                       "call V_ADD" if op in ("add", "adc") else "call V_SUB")
            self.nz_t0()

    def need(self, flag):
        """Is `flag` live after the current instruction? (Phase 0: always.)"""
        return True

    def nz_t0(self):
        if self.need("N") or self.need("Z"):
            self.e("call NZ_T0")

    def logic(self, op, A, B, dst):
        self.e(f"ld hl, {h(B)}")
        for i in range(4):
            if op == "bic":
                self.e("ld a, [hl]", "cpl", "ld c, a", f"ldh a, [{h(A + i)}]", "and c")
            else:
                self.e(f"ldh a, [{h(A + i)}]", f"{ {'and': 'and', 'orr': 'or', 'eor': 'xor'}[op]} a, [hl]")
            self.e(f"ldh [{h(dst + i)}], a")
            if i < 3:
                self.e("inc l")

    # ---- instructions ----
    def ins(self, x):
        op = x.op
        rd = R(x.rd) if x.rd is not None else None
        if op == "nop":
            return
        if op == "mov":
            if isinstance(x.a, int):
                self.ldimm(T0 if x.s else rd, x.a)
            else:
                self.copy(T0 if x.s else rd, R(int(x.a[1:])))
            if x.s:
                self.nz_t0()
                self.copy(rd, T0)
            return
        if op == "mvn":
            A = self.src(x.a, T1)
            for i in range(4):
                self.e(f"ldh a, [{h(A + i)}]", "cpl", f"ldh [{h(T0 + i)}], a")
            self.nz_t0()
            self.copy(rd, T0)
            return
        if op in ("add", "sub", "adc", "sbc", "cmp", "cmn"):
            real = {"cmp": "sub", "cmn": "add"}.get(op, op)
            A = self.src(x.a, T2)
            B = self.src(x.b, T1)
            if not x.s:
                self.addsub(real, A, B, rd, False)  # no flags: direct write is safe
            else:
                self.addsub(real, A, B, T0, True)
                if op not in ("cmp", "cmn"):
                    self.copy(rd, T0)
            return
        if op in ("and", "orr", "eor", "bic", "tst"):
            A = self.src(x.a, T2)
            B = self.src(x.b, T1)
            self.logic("and" if op == "tst" else op, A, B, T0)
            self.nz_t0()
            if op != "tst":
                self.copy(rd, T0)
            return
        if op in ("lsl", "lsr", "asr", "ror"):
            self.copy(T0, R(int(x.a[1:])))
            if isinstance(x.b, int):
                n = x.b
                if n == 0 and op in ("lsr", "asr"):
                    n = 32
                if n == 0:  # lsls #0 = movs
                    self.nz_t0()
                    self.copy(rd, T0)
                    return
                self.e(f"ld b, {n}")
            else:
                self.e(f"ldh a, [{h(R(int(x.b[1:])))}]", "ld b, a")
            self.e(f"call SH_{op.upper()}")
            self.nz_t0()
            self.copy(rd, T0)
            return
        if op == "mul":
            self.copy(T2, R(int(x.b[1:])))
            self.copy(T1, R(int(x.a[1:])))
            self.e("call MUL32")
            self.nz_t0()
            self.copy(rd, T0)
            return
        if op == "swi":
            self.e("call HAL_VBLANKINTRWAIT")  # the only BIOS call accepted by the interceptor
            return
        if x.addr in self.hal and self.hal[x.addr]["region"] != "ram":
            return self.hal_mem(x)
        if op in ("ldr", "ldrb", "ldrh", "ldrsb", "ldrsh", "str", "strb", "strh"):
            base, idx, disp = x.mem
            if idx is None and disp == 0:
                ad = R(base)
            else:
                B = R(idx) if idx is not None else self.src(disp, T1)
                self.addsub("add", R(base), B, T1, False)
                ad = T1
            self.hl_from(ad)
            n = {"": 4, "b": 1, "h": 2, "sb": 1, "sh": 2}[op[3:]]
            if op.startswith("str"):
                for i in range(n):
                    self.e(f"ldh a, [{h(rd + i)}]", "ld [hl+], a" if i < n - 1 else "ld [hl], a")
            else:
                for i in range(n):
                    self.e("ld a, [hl+]" if i < n - 1 else "ld a, [hl]", f"ldh [{h(rd + i)}], a")
                if n < 4:
                    if op[3:] in ("sb", "sh"):
                        self.e("rlca", "sbc a, a")
                    else:
                        self.e("xor a")
                    for i in range(n, 4):
                        self.e(f"ldh [{h(rd + i)}], a")
            return
        if op == "push":
            self.ldimm(T1, 4 * len(x.regs))
            self.addsub("sub", SP, T1, SP, False)
            self.hl_from(SP)
            for r in x.regs:
                for i in range(4):
                    self.e(f"ldh a, [{h(R(r) + i)}]", "ld [hl+], a")
            return
        if op in ("pop", "pop_ret", "ldm", "stm"):
            basereg = 13 if op.startswith("pop") else x.rd
            self.hl_from(R(basereg))
            for r in x.regs:
                for i in range(4):
                    if op == "stm":
                        self.e(f"ldh a, [{h(R(r) + i)}]", "ld [hl+], a")
                    else:
                        self.e("ld a, [hl+]", f"ldh [{h(R(r) + i)}], a")
            if op.startswith("pop") or (x.wb and not (op == "ldm" and x.rd in x.regs)):
                self.ldimm(T1, 4 * len(x.regs))
                self.addsub("add", R(basereg), T1, R(basereg), False)
            if op == "pop_ret":
                self.e("ret")
            return
        if op == "ret":
            self.e("ret")
            return
        if op == "b":
            self.e(f"jp L_{x.target:08X}")
            return
        if op == "bl":
            self.ldimm(R(14), (x.addr + 4) | 1)
            self.e(f"call L_{x.target:08X}")
            return
        if op == "bcc":
            self.cond(x.cond)
            self.e("or a", f"jp nz, L_{x.target:08X}")
            return
        raise LiftError(f"backend: unsupported op {op} ({x.text})")

    # ---- Phase 2: statically intercepted accesses (tools/hal/intercept.py) ----
    IO_WR = {0x000: "DISPCNT", 0x010: "BG0HOFS", 0x012: "BG0VOFS"}
    IO_RD = {0x006: "VCOUNT", 0x130: "KEYINPUT"}

    def load_bytes(self, rd, n, signed):
        """Load n bytes from [hl] into the slot rd, extended to 32 bits."""
        for i in range(n):
            self.e("ld a, [hl+]" if i < n - 1 else "ld a, [hl]", f"ldh [{h(rd + i)}], a")
        if n < 4:
            self.e("rlca", "sbc a, a") if signed else self.e("xor a")
            for i in range(n, 4):
                self.e(f"ldh [{h(rd + i)}], a")

    def hal_mem(self, x):
        acc = self.hal[x.addr]
        reg = acc["region"]
        if x.op in ("ldm", "stm"):
            base = x.rd
            for k, r in enumerate(x.regs):
                self.ldimm(T2, 4 * k)
                self.addsub("add", R(base), T2, T1, False)
                if x.op == "stm":   # VRAM
                    self.e(f"ld c, LOW({h(R(r))})", "call HAL_VRAM_STORE32")
                else:               # ROM
                    self.e(f"ldh a, [{h(T1 + 1)}]", "and $1F", "or $20", "ld h, a",
                           f"ldh a, [{h(T1)}]", "ld l, a")
                    self.load_bytes(R(r), 4, False)
            if x.wb and not (x.op == "ldm" and x.rd in x.regs):
                self.ldimm(T2, 4 * len(x.regs))
                self.addsub("add", R(base), T2, R(base), False)
            return
        base, idx, disp = x.mem
        n = acc["width"]
        rd = R(x.rd)
        st = acc["store"]
        signed = x.op in ("ldrsb", "ldrsh")
        if reg == "io":
            off = acc["const"] - 0x04000000
            name = (self.IO_WR if st else self.IO_RD).get(off)
            if name and st:
                self.e(f"ld c, LOW({h(rd)})", f"call HAL_WR_{name}")
            elif name:
                self.e(f"ld c, LOW({h(rd)})", f"call HAL_{name}")
            elif st:
                self.e(f"; I/O write to {off:#05x} ignored (HAL owns it)")
            else:
                self.ldimm(rd, 0)
            return
        if reg == "oam":
            o = acc["const"] - 0x07000000
            if o + n > 256:
                raise LiftError(f"OAM access {acc['const']:#x} at {x.addr:#x}: the GBA OAM mirror holds objects 0-31")
            if st:
                for i in range(n):
                    self.e(f"ldh a, [{h(rd + i)}]", f"ld [${0xD100 + o + i:04X}], a")
            else:
                self.e(f"ld hl, ${0xD100 + o:04X}")
                self.load_bytes(rd, n, signed)
            return
        if idx is None and disp == 0:
            self.copy(T1, R(base))
        else:
            B = R(idx) if idx is not None else self.src(disp, T1)
            self.addsub("add", R(base), B, T1, False)
        if reg == "rom":
            self.e(f"ldh a, [{h(T1 + 1)}]", "and $1F", "or $20", "ld h, a", f"ldh a, [{h(T1)}]", "ld l, a")
            self.load_bytes(rd, n, signed)
            return
        if n == 1:
            raise LiftError(f"8-bit store to {reg.upper()} at {x.addr:#x} is not supported")
        self.e(f"ld c, LOW({h(rd)})", f"call HAL_{reg.upper()}_STORE{8 * n}")

    def cond(self, c):
        """Leave the boolean value (0/1) of the ARM condition in a."""
        e = self.e
        neg = False
        base = {"ne": "eq", "cc": "cs", "pl": "mi", "vc": "vs", "ls": "hi",
                "lt": "ge", "le": "gt"}
        if c in base:
            c, neg = base[c], True
        if c == "eq":
            e(f"ldh a, [{h(FZ)}]")
        elif c == "cs":
            e(f"ldh a, [{h(FC)}]")
        elif c == "mi":
            e(f"ldh a, [{h(FN)}]")
        elif c == "vs":
            e(f"ldh a, [{h(FV)}]")
        elif c == "hi":
            e(f"ldh a, [{h(FZ)}]", "xor 1", "ld b, a", f"ldh a, [{h(FC)}]", "and b")
        elif c in ("ge", "gt"):
            e(f"ldh a, [{h(FN)}]", "ld b, a", f"ldh a, [{h(FV)}]", "xor b", "xor 1")
            if c == "gt":
                e("ld c, a", f"ldh a, [{h(FZ)}]", "xor 1", "and c")
        else:
            raise LiftError(f"unknown condition {c}")
        if neg:
            e("xor 1")

    def begin_block(self, addr):
        """Hook called at every label (narrowed backend resets its state)."""

    def generate(self):
        o = self.out
        o.append("; Generated by gba2gbc-core (Phase 0) — do not edit")
        o.append('INCLUDE "hram.inc"')
        o.append('SECTION "kernel", ROMX, BANK[1]')
        o.append("KernelEntry::")
        o.append(f"    jp L_{self.p.entry:08X}")
        for x in self.p.ordered():
            if x.addr in self.p.leaders or x.addr in self.p.funcs:
                o.append(f"L_{x.addr:08X}:")
                self.begin_block(x.addr)
            o.append(f"    ; {x.addr:08X}: {x.text}")
            self.ins(x)
        return "\n".join(o) + "\n"


def generate_asm(prog: Program, hal=None) -> str:
    return Gen(prog, hal).generate()
