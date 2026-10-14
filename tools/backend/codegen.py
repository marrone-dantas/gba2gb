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


OAM_MIRROR = 0xD400   # GBA OAM mirror (runtime/gb_hal_shims.asm wGbaOAM, 128 objects)


class Gen:
    def __init__(self, prog: Program, hal=None):
        self.p = prog
        self.out: list[str] = []
        self.hal = hal or {}  # addr -> access (tools/hal/intercept.py), Phase 2
        self.stats = {}

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

    def const_shift(self, op, S, n):
        """Phase 5 B3: shift by a constant 1..31 inline (byte moves + at most 7 register
        bit steps) instead of the bit-loop SH_* helpers. T0 = result, FC = ARM carry out
        (lsl: bit 32-n of the input, lsr/asr: bit n-1)."""
        cb = 32 - n if op == "lsl" else n - 1
        self.e(f"ldh a, [{h(S + cb // 8)}]", f"and ${1 << (cb % 8):02X}", "add a, $FF",
               "ld a, 0", "rla", f"ldh [{h(FC)}], a")
        q, r = divmod(n, 8)
        regs = ["e", "d", "c", "b"]          # byte 0 .. byte 3
        if op == "asr":
            self.e(f"ldh a, [{h(S + 3)}]", "rlca", "sbc a, a", "ld l, a")   # l = sign fill
        for i in range(4):
            src = i - q if op == "lsl" else i + q
            if 0 <= src < 4:
                self.e(f"ldh a, [{h(S + src)}]", f"ld {regs[i]}, a")
            elif op == "asr":
                self.e(f"ld {regs[i]}, l")
            else:
                self.e(f"ld {regs[i]}, 0")
        for _ in range(r):
            if op == "lsl":
                self.e("sla e", "rl d", "rl c", "rl b")
            else:
                self.e("srl b" if op == "lsr" else "sra b", "rr c", "rr d", "rr e")
        for i in range(4):
            self.e(f"ld a, {regs[i]}", f"ldh [{h(T0 + i)}], a")

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
        if op in ("lsl", "lsr", "asr") and isinstance(x.b, int) and 1 <= x.b <= 31:
            self.const_shift(op, R(int(x.a[1:])), x.b)
            self.nz_t0()
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
            self.e(f"jp {self.tgt(x.target)}")
            return
        if op == "bl" and x.native:
            self.e(f"call NAT_{x.native}")      # Phase 5 B2: native helper (runtime/gb_softfloat.asm)
            return
        if op == "bl":
            self.ldimm(R(14), (x.addr + 4) | 1)
            self.e(f"call L_{x.target:08X}")
            return
        if op == "bcc":
            self.cond(x.cond)
            self.e("or a", f"jp nz, {self.tgt(x.target)}")
            return
        raise LiftError(f"backend: unsupported op {op} ({x.text})")

    # ---- Phase 2: statically intercepted accesses (tools/hal/intercept.py) ----
    IO_WR = {0x000: "DISPCNT", 0x00A: "BG1CNT", 0x010: "BG0HOFS", 0x012: "BG0VOFS",
             0x0BC: "DMA1SAD", 0x0C6: "DMA1CNT_H", 0x100: "TM0D", 0x102: "TM0CNT_H",
             0x104: "TM1D", 0x106: "TM1CNT_H"}
    IO_RD = {0x006: "VCOUNT", 0x100: "TM0D", 0x104: "TM1D", 0x130: "KEYINPUT"}

    def load_bytes(self, rd, n, signed):
        """Load n bytes from [hl] into the slot rd, extended to 32 bits."""
        for i in range(n):
            self.e("ld a, [hl+]" if i < n - 1 else "ld a, [hl]", f"ldh [{h(rd + i)}], a")
        if n < 4:
            self.e("rlca", "sbc a, a") if signed else self.e("xor a")
            for i in range(n, 4):
                self.e(f"ldh [{h(rd + i)}], a")

    def ew_hl(self, acc, src):
        """Phase 5 A2: select the SRAM bank of an EWRAM access (unless the bank-switch
        pass proved it current) and point hl at $A000 | (addr & $1FFF). src = HRAM
        slot holding the ARM address, or None for a constant address."""
        if acc["bank"] is None:
            self.e("call HAL_EW_SETBANK")
            self.stats["sram_dyn_bank"] = self.stats.get("sram_dyn_bank", 0) + 1
        elif acc.get("switch", True):
            self.e(f"ld a, {acc['bank']}", "ld [$4000], a")
            self.stats["sram_switches"] = self.stats.get("sram_switches", 0) + 1
        if src is None:
            self.e(f"ld hl, ${0xA000 | (acc['const'] & 0x1FFF):04X}")
        else:
            self.e(f"ldh a, [{h(src + 1)}]", "and $1F", "or $A0", "ld h, a", f"ldh a, [{h(src)}]", "ld l, a")

    def tgt(self, t):
        """Branch label: back edges of a loop with a hoisted SRAM bank switch skip it."""
        ho = getattr(self.hal, "hoist", {}) if self.hal else {}
        if t in ho and getattr(self, "cur_block", None) in ho[t]["body"]:
            return f"L_{t:08X}_in"
        return f"L_{t:08X}"

    def hal_mem(self, x):
        acc = self.hal[x.addr]
        reg = acc["region"]
        if x.op in ("ldm", "stm"):
            base = x.rd
            for k, r in enumerate(x.regs):
                self.ldimm(T2, 4 * k)
                self.addsub("add", R(base), T2, T1, False)
                if reg == "ewram":
                    self.ew_hl(acc, T1)
                    if x.op == "stm":
                        for i in range(4):
                            self.e(f"ldh a, [{h(R(r) + i)}]", "ld [hl+], a")
                    else:
                        self.load_bytes(R(r), 4, False)
                elif x.op == "stm" and reg == "dyn":
                    self.e(f"ld c, LOW({h(R(r))})", "ld e, 4", "call HAL_DYN_STORE")
                elif x.op == "stm":   # VRAM
                    self.e(f"ld c, LOW({h(R(r))})", "call HAL_VRAM_STORE32")
                elif reg == "dyn":
                    self.e("call HAL_DYN_ADDR")
                    self.load_bytes(R(r), 4, False)
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
            if st and 0x60 <= off < 0xA0:
                # GBA sound registers + wave RAM -> DMG APU (Phase 4.3, docs/audio.md)
                self.e(f"ld c, LOW({h(rd)})", f"ld b, ${off:02X}", f"ld e, {n}", "call HAL_SND_WR")
            elif name and st:
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
            if o + n > 1024:
                raise LiftError(f"OAM access {acc['const']:#x} at {x.addr:#x}: outside OAM")
            if st:
                for i in range(n):
                    self.e(f"ldh a, [{h(rd + i)}]", f"ld [${OAM_MIRROR + o + i:04X}], a")
                # Phase 5 B3: mark the mirror dirty so the key-read compose (GbaView) runs
                self.e("ld a, 1", "ld [wOamDirty], a")
                if o % 8 == 6 and (o % 32) // 8 in (0, 1):
                    # OBJ_AFFINE pa / pb: select a pre-rotated frame (Phase 4.1, docs/affine.md)
                    self.e("call HAL_AFFINE_SEL")
            else:
                self.e(f"ld hl, ${OAM_MIRROR + o:04X}")
                self.load_bytes(rd, n, signed)
            return
        if reg == "ewram" and acc["const"] is not None:
            self.ew_hl(acc, None)
        elif idx is None and disp == 0:
            self.copy(T1, R(base))
        else:
            B = R(idx) if idx is not None else self.src(disp, T1)
            self.addsub("add", R(base), B, T1, False)
        if reg == "ewram":
            if acc["const"] is None:
                self.ew_hl(acc, T1)
            if st:
                for i in range(n):
                    self.e(f"ldh a, [{h(rd + i)}]", "ld [hl+], a" if i < n - 1 else "ld [hl], a")
            else:
                self.load_bytes(rd, n, signed)
            return
        if reg == "rom":
            self.e(f"ldh a, [{h(T1 + 1)}]", "and $1F", "or $20", "ld h, a", f"ldh a, [{h(T1)}]", "ld l, a")
            self.load_bytes(rd, n, signed)
            return
        if reg == "dyn":
            # Phase 5 A1: address space unknown at compile time -> run-time dispatch
            if st:
                self.e(f"ld c, LOW({h(rd)})", f"ld e, {n}", "call HAL_DYN_STORE")
            else:
                self.e("call HAL_DYN_ADDR")
                self.load_bytes(rd, n, signed)
            self.stats["dyn_accesses"] = self.stats.get("dyn_accesses", 0) + 1
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
        """Emit the kernel. Large programs (Snek ~40 KiB) are split across MBC5
        floating ROMX sections placed by rgblink (soft-float is in bank 1). Cross-bank call/jp use
        FarCall / FarJump (runtime/gb_bank.asm).

        Banks are split only at function entries, so a function's `ret` always runs
        in the bank its caller mapped (or FarRet restores it). A cross-bank jump to
        a function entry (Thumb tail call `b func`) becomes `call FarCall; ret`, which
        keeps the callee's `ret` returning through FarRet with the right bank."""
        import re
        BUDGET = 0x3A00
        header = ["; Generated by gba2gbc-core (Phase 0) — do not edit",
                  'INCLUDE "hram.inc"']
        self.out = []
        ho = getattr(self.hal, "hoist", {}) if self.hal else {}
        # pass 1: per-function groups of (label, lines)
        groups = [[("KernelEntry", [f"    jp L_{self.p.entry:08X}"])]]
        for x in self.p.ordered():
            prefix = []
            lab = None
            if x.addr in self.p.funcs and groups[-1]:
                groups.append([])
            if x.addr in self.p.leaders or x.addr in self.p.funcs:
                if x.addr in ho and getattr(self, "cur_block", None) in ho[x.addr]["body"]:
                    prefix.append(f"    jp L_{x.addr:08X}_in   ; in-loop fall-through skips the hoisted switch")
                lab = f"L_{x.addr:08X}"
                self.cur_block = x.addr
                self.begin_block(x.addr)
                if x.addr in ho:
                    prefix += [f"    ld a, {ho[x.addr]['bank']}   ; SRAM bank hoisted out of the loop",
                               "    ld [$4000], a", f"L_{x.addr:08X}_in::"]
            self.out = []
            self.out.append(f"    ; {x.addr:08X}: {x.text}")
            self.ins(x)
            groups[-1].append((lab, prefix + self.out))
        est = lambda lines: sum(max(1, len(l) // 8) for l in lines)
        # pass 2: pack whole functions into banks
        chunks, banks = [], {}
        cur, bank, size = [], 2, 0
        funcs = {f"L_{a:08X}" for a in self.p.funcs}
        for g in groups:
            gs = sum(est(ls) for _, ls in g)

            def new_bank():
                nonlocal cur, bank, size
                nxt = f"BankCont_{bank + 1}"
                cur += [(f"    ld a, BANK(KBank{bank + 1})", bank), (f"    ld hl, {nxt}", bank), ("    jp FarJump", bank)]
                chunks.append((bank, cur))
                bank += 1
                cur, size = [(f"{nxt}::", bank)], 0
                banks[nxt] = bank

            if size + gs > BUDGET and cur and gs <= BUDGET:
                new_bank()
            entry_bank = bank
            # A function larger than one bank (Snek's main) is split at instruction
            # boundaries; a `ret` in a continuation bank first re-maps the entry bank
            # through ROM0 (RetBank), so the caller's return address is valid again.
            for lab, ls in g:
                e_ = est(ls)
                if size + e_ > BUDGET and cur and gs > BUDGET:
                    new_bank()
                if lab:
                    banks[lab] = bank
                    cur.append((f"{lab}::", entry_bank))
                    if f"{lab}_in::" in "\n".join(ls):
                        banks[f"{lab}_in"] = bank
                if bank != entry_bank:
                    ls = [f"    ld a, BANK(KBank{entry_bank})\n    jp RetBank" if l == "    ret" else l for l in ls]
                cur.extend((l, entry_bank) for l in ls)
                size += e_
        if cur:
            chunks.append((bank, cur))

        out = list(header)
        for b, lines in chunks:
            # floating ROMX: rgblink picks the bank, so kernel code never collides
            # with fixed data banks (affine frames, SFX, mode7 tables); banks are
            # referenced symbolically through the KBank<n> anchors.
            out.append(f'SECTION "kernel{b}", ROMX')
            out.append(f"KBank{b}::")
            for line, eb in lines:
                rt = ["    ret"] if eb == b else [f"    ld a, BANK(KBank{eb})", "    jp RetBank"]
                m = re.match(r"    (call|jp) (L_[0-9A-Fa-f]{8}|L_[0-9A-Fa-f]{8}_in|BankCont_\d+)\s*(;.*)?$", line)
                if m:
                    op, tgt = m.group(1), m.group(2)
                    tb = banks.get(tgt, b)
                    if tb == b:
                        out.append(line)
                    elif op == "call":
                        out += [f"    ld a, BANK(KBank{tb})", f"    ld hl, {tgt}", "    call FarCall"]
                    elif tgt in funcs:
                        out += [f"    ld a, BANK(KBank{tb})", f"    ld hl, {tgt}", "    call FarCall"] + rt
                    else:
                        out += [f"    ld a, BANK(KBank{tb})", f"    ld hl, {tgt}", "    jp FarJump"]
                    continue
                m2 = re.match(r"    jp (nz|z|nc|c), (L_[0-9A-Fa-f]{8}|L_[0-9A-Fa-f]{8}_in)\s*(;.*)?$", line)
                if m2 and banks.get(m2.group(2), b) != b:
                    cond, tgt = m2.group(1), m2.group(2)
                    inv = {"nz": "z", "z": "nz", "nc": "c", "c": "nc"}[cond]
                    self._ftag = getattr(self, "_ftag", 0) + 1
                    tag = f"{self._ftag}"
                    tail = ["    call FarCall"] + rt if tgt in funcs else ["    jp FarJump"]
                    out += [f"    jr {inv}, .f_{tag}",
                            f"    ld a, BANK(KBank{banks[tgt]})", f"    ld hl, {tgt}"] + tail + [f".f_{tag}:"]
                    continue
                out.append(line)
        return "\n".join(out) + "\n"


def generate_asm(prog: Program, hal=None) -> str:
    return Gen(prog, hal).generate()
