"""Narrowed SM83 code generation (Phase 1, part B2).

Consumes a `Plan` from tools/prune/bitwidth_pruning.py:
  * every SSA value is stored in the low `n` bytes (1, 2 or 4) of its register
    slot; bytes above `n` are only (re)materialized when a consumer needs them;
  * 8-bit values are computed in A over a single HRAM byte, 16-bit values over two
    bytes (byte pairs), 32-bit values as in Phase 0;
  * flags are only computed when live (tools/backend/flags.py);
  * fused extensions (uxtb/sxtb/uxth/sxth) replace LSL+LSR/ASR pairs;
  * constant shifts become byte moves plus at most 7 bit shifts;
  * MUL runs only as many iterations as the multiplier's proven bit length (or
    8 x result bytes);
  * profile-guided values are computed at full width and checked by a guard that
    jumps to `GuardTrap` on violation.
Anything not narrowed falls back to the Phase 0 sequences (with flag elision).
"""
from tools.backend.codegen import Gen, R, T0, T1, T2, FN, FZ, FC, h
from tools.backend.flags import live_out
from tools.lift.defuse import defs, uses

NARROW_ALU = ("add", "sub", "and", "orr", "eor", "bic")


class NarrowGen(Gen):
    def __init__(self, plan, hal=None):
        super().__init__(plan.ssa.prog, hal)
        self.plan = plan
        self.ssa = plan.ssa
        self.live = live_out(plan.ssa)
        self.cur_live = set("NZCV")
        self.valid = {}          # reg -> (Value, valid bytes in the slot)
        self.guard_id = 0
        self.stats = {"narrow_ops": 0, "fallback_ops": 0, "guards": 0}

    # ---------------------------------------------------------------- state
    def need(self, flag):
        return flag in self.cur_live

    def begin_block(self, addr):
        self.valid = {}

    def val(self, x, reg):
        return self.ssa.envs.get(x.addr, {}).get(reg)

    def have(self, reg, v):
        cur = self.valid.get(reg)
        if cur is not None and cur[0] is v:
            return cur[1]
        return self.plan.store(v)[0] if v is not None else 4

    def ensure(self, x, reg, need):
        """Make sure the slot of `reg` holds at least `need` valid bytes."""
        v = self.val(x, reg)
        have = self.have(reg, v)
        if have >= need:
            return
        ext = self.plan.store(v)[1] if v is not None else "z"
        base = R(reg)
        if ext == "s":
            self.e(f"ldh a, [{h(base + have - 1)}]", "rlca", "sbc a, a")
        else:
            self.e("xor a")
        for i in range(have, need):
            self.e(f"ldh [{h(base + i)}], a")
        self.valid[reg] = (v, need)

    def ensure_all(self, x, need=4):
        for r in uses(x):
            if r != 15:
                self.ensure(x, r, need)

    def defined(self, x, reg, nbytes):
        v = self.ssa.defval.get((x.addr, reg))
        self.valid[reg] = (v, nbytes)

    def dstore(self, x):
        v = self.ssa.defval.get((x.addr, x.rd))
        return self.plan.store(v) if v is not None else (4, "z"), v

    # ---------------------------------------------------------------- helpers
    def opnd(self, x, o, w, tmp):
        if isinstance(o, int):
            for i in range(w):
                self.e(f"ld a, ${(o >> 8 * i) & 0xFF:02X}", f"ldh [{h(tmp + i)}], a")
            return tmp
        r = int(o[1:])
        self.ensure(x, r, w)
        return R(r)

    def nz(self, dst, w, ext):
        if self.need("Z"):
            self.e(f"ldh a, [{h(dst)}]")
            for i in range(1, w):
                self.e("ld b, a", f"ldh a, [{h(dst + i)}]", "or b")
            self.e("sub 1", "ld a, 0", "rla", f"ldh [{h(FZ)}], a")
        if self.need("N"):
            if w < 4 and ext == "z":
                self.e("xor a", f"ldh [{h(FN)}], a")
            else:
                self.e(f"ldh a, [{h(dst + w - 1)}]", "rlca", "and 1", f"ldh [{h(FN)}], a")

    def guard(self, v, rd):
        cls = self.plan.guards[v]
        n, ext = {"u8": (1, "z"), "i8": (1, "s"), "u16": (2, "z"), "i16": (2, "s")}[cls]
        gid = self.guard_id = self.guard_id + 1
        self.stats["guards"] += 1
        self.e(f"; guard v{v.id} in {cls}")
        if ext == "z":
            for i in range(n, 4):
                self.e(f"ldh a, [{h(rd + i)}]", "or a", f"ld a, {gid & 0xFF}", "jp nz, GuardTrap")
        else:
            self.e(f"ldh a, [{h(rd + n - 1)}]", "rlca", "sbc a, a", "ld b, a")
            for i in range(n, 4):
                self.e(f"ldh a, [{h(rd + i)}]", "cp b", f"ld a, {gid & 0xFF}", "jp nz, GuardTrap")

    def fallback(self, x):
        """Phase 0 sequence (32-bit), operands materialized, flags elided if dead."""
        self.stats["fallback_ops"] += 1
        self.ensure_all(x, 4)
        super().ins(x)
        for r in defs(x):
            if r != 15:
                self.defined(x, r, 4)
        v = self.ssa.defval.get((x.addr, x.rd)) if x.rd is not None else None
        if v is not None and v in self.plan.guards:
            self.guard(v, R(x.rd))

    # ---------------------------------------------------------------- instructions
    def ins(self, x):
        if x.addr in self.plan.deleted:
            self.e("; (deleted: fused extension)")
            return
        self.cur_live = self.live.get(x.addr, set("NZCV"))
        fr = self.plan.frame
        if fr is not None and x.addr in fr.trim:  # item 3: trimmed frame padding
            self.e(f"; frame trimmed: #{x.b} -> #{fr.trim[x.addr]}")
            x = type(x)(**{**x.__dict__, "b": fr.trim[x.addr]})
        op = x.op
        (w, ext), dv = self.dstore(x) if x.rd is not None else ((4, "z"), None)
        guarded = dv is not None and dv in self.plan.guards
        if x.addr in self.plan.fused:
            return self.fused(x, w, ext)
        if guarded:
            return self.fallback(x)
        if op == "mov" and x.rd not in (13, 15):
            rd = R(x.rd)
            if isinstance(x.a, int):
                for i in range(w):
                    self.e(f"ld a, ${(x.a >> 8 * i) & 0xFF:02X}", f"ldh [{h(rd + i)}], a")
            else:
                src = self.opnd(x, x.a, w, T1)
                if src != rd:
                    for i in range(w):
                        self.e(f"ldh a, [{h(src + i)}]", f"ldh [{h(rd + i)}], a")
            self.defined(x, x.rd, w)
            if x.s:
                self.nz(rd, w, ext)
            self.stats["narrow_ops"] += 1
            return
        if op == "mvn":
            rd = R(x.rd)
            src = self.opnd(x, x.a, w, T1)
            for i in range(w):
                self.e(f"ldh a, [{h(src + i)}]", "cpl", f"ldh [{h(rd + i)}], a")
            self.defined(x, x.rd, w)
            self.nz(rd, w, ext)
            self.stats["narrow_ops"] += 1
            return
        if op in NARROW_ALU and x.rd != 13 and not (op in ("add", "sub") and x.s and (self.need("C") or self.need("V"))):
            return self.alu(x, op, w, ext)
        if op in ("cmp", "tst") and not (self.need("C") or self.need("V") or self.need("N")):
            return self.zero_test(x)
        if op in ("lsl", "lsr", "asr") and isinstance(x.b, int) and not self.need("C"):
            return self.shift_const(x, op, w, ext)
        if op == "mul":
            return self.mul(x, w, ext)
        if op in ("ldr", "ldrb", "ldrh", "ldrsb", "ldrsh", "str", "strb", "strh"):
            return self.mem(x, w, ext)
        if op in ("push", "pop", "pop_ret"):
            return self.push_pop(x)
        if op == "ret":
            self.ensure(x, 0, 4)
        if op == "bl":
            for r in (0, 1, 2, 3):
                self.ensure(x, r, 4)
            super().ins(x)
            self.valid = {}
            return
        if op in ("b", "bcc", "ret", "nop"):
            super().ins(x)
            return
        self.fallback(x)

    def push_pop(self, x):
        """PUSH/POP with save-slot elision (tools/prune/frame.py): skipped slots are
        neither written by the push nor loaded by the pop (SP still moves)."""
        fr = self.plan.frame
        n = len(x.regs)
        if x.op == "push":
            skip = fr.skip_push.get(x.addr, set()) if fr else set()
            for r in x.regs:
                if r not in skip:
                    self.ensure(x, r, 4)
            self.ldimm(T1, 4 * n)
            self.addsub("sub", R(13), T1, R(13), False)
            if len(skip) < n:
                self.hl_from(R(13))
                for r in x.regs:
                    if r in skip:
                        self.e(f"; slot of r{r} elided", *["inc hl"] * 4)
                    else:
                        for i in range(4):
                            self.e(f"ldh a, [{h(R(r) + i)}]", "ld [hl+], a")
            self.defined(x, 13, 4)
            self.stats["narrow_ops"] += 1
            return
        if x.op == "pop_ret":
            self.ensure(x, 0, 4)
        skip = fr.skip_pop.get(x.addr, set()) if fr else set()
        if len(skip) < n:
            self.hl_from(R(13))
            for r in x.regs:
                if r in skip:
                    self.e(f"; r{r} restore elided", *["inc hl"] * 4)
                else:
                    for i in range(4):
                        self.e("ld a, [hl+]", f"ldh [{h(R(r) + i)}], a")
                    self.defined(x, r, 4)
        self.ldimm(T1, 4 * n)
        self.addsub("add", R(13), T1, R(13), False)
        self.defined(x, 13, 4)
        if x.op == "pop_ret":
            self.e("ret")
        self.stats["narrow_ops"] += 1

    def alu(self, x, op, w, ext):
        rd = R(x.rd)
        mn = {"add": ("add", "adc"), "sub": ("sub", "sbc"), "and": ("and", "and"),
              "orr": ("or", "or"), "eor": ("xor", "xor"), "bic": ("and", "and")}[op]
        if isinstance(x.b, int) and not isinstance(x.a, int):
            # Phase P1: immediate operand -> SM83 immediate forms (no T1 staging)
            A = self.opnd(x, x.a, w, T2)
            c = (~x.b if op == "bic" else x.b) & 0xFFFFFFFF
            for i in range(w):
                self.e(f"ldh a, [{h(A + i)}]", f"{mn[0] if i == 0 else mn[1]} a, ${(c >> 8 * i) & 0xFF:02X}",
                       f"ldh [{h(rd + i)}], a")
            self.defined(x, x.rd, w)
            if x.s:
                self.nz(rd, w, ext)
            self.stats["narrow_ops"] += 1
            return
        A = self.opnd(x, x.a, w, T2)
        B = self.opnd(x, x.b, w, T1)
        self.e(f"ld hl, {h(B)}")
        for i in range(w):
            if op == "bic":
                self.e("ld a, [hl]", "cpl", "ld c, a", f"ldh a, [{h(A + i)}]", "and c")
            else:
                self.e(f"ldh a, [{h(A + i)}]", f"{mn[0] if i == 0 else mn[1]} a, [hl]")
            self.e(f"ldh [{h(rd + i)}], a")
            if i < w - 1:
                self.e("inc l")
        self.defined(x, x.rd, w)
        if x.s:
            self.nz(rd, w, ext)
        self.stats["narrow_ops"] += 1

    def zero_test(self, x):
        """cmp/tst whose only live flag is Z: byte-wise equality / AND test."""
        if not self.need("Z"):
            self.e("; (dead compare)")
            return
        va = self.val(x, int(x.a[1:]))
        vb = self.val(x, int(x.b[1:])) if isinstance(x.b, str) else None
        sa = self.plan.store(va) if va is not None else (4, "z")
        sb = self.plan.store(vb) if vb is not None else (4, "z")
        if isinstance(x.b, int):
            c = x.b & 0xFFFFFFFF
            fits = (c < (1 << 8 * sa[0])) if sa[1] == "z" else False
            w = sa[0] if fits else 4
        else:
            w = max(sa[0], sb[0]) if sa[1] == sb[1] else 4
        if x.op == "tst" and (sa[1] == "z" or sb[1] == "z"):
            w = min(n for n, e in (sa, sb) if e == "z")
        A = self.opnd(x, x.a, w, T2)
        B = self.opnd(x, x.b, w, T1)
        self.e(f"ld hl, {h(B)}", "ld c, 0")
        for i in range(w):
            self.e(f"ldh a, [{h(A + i)}]", "xor [hl]" if x.op == "cmp" else "and [hl]", "or c", "ld c, a")
            if i < w - 1:
                self.e("inc l")
        self.e("ld a, c", "sub 1", "ld a, 0", "rla", f"ldh [{h(FZ)}], a")
        self.stats["narrow_ops"] += 1

    def shift_const(self, x, op, w, ext):
        k = x.b
        if k == 0 and op in ("lsr", "asr"):
            k = 32
        if k == 0:  # lsls #0 = movs
            x2 = type(x)(**{**x.__dict__, "op": "mov", "b": None})
            return self.ins_mov_like(x2, w, ext)
        rd = R(x.rd)
        src_reg = int(x.a[1:])
        q, r = divmod(min(k, 32), 8)
        if op == "lsl":
            if k >= 32:
                for i in range(w):
                    self.e("xor a", f"ldh [{h(rd + i)}], a")
            else:
                self.ensure(x, src_reg, max(1, w - q))
                S = R(src_reg)
                for i in reversed(range(w)):   # T0 = src << 8q (only w bytes)
                    if i - q >= 0:
                        self.e(f"ldh a, [{h(S + i - q)}]")
                    else:
                        self.e("xor a")
                    self.e(f"ldh [{h(T0 + i)}], a")
                for _ in range(r):
                    self.e(f"ld hl, {h(T0)}", "sla [hl]")
                    for i in range(1, w):
                        self.e("inc l", "rl [hl]")
                for i in range(w):
                    self.e(f"ldh a, [{h(T0 + i)}]", f"ldh [{h(rd + i)}], a")
        else:
            self.ensure(x, src_reg, 4)
            S = R(src_reg)
            top = min(3, w)  # bytes 0..top are needed (top supplies the shifted-in bits)
            if op == "asr":
                self.e(f"ldh a, [{h(S + 3)}]", "rlca", "sbc a, a", "ld d, a")
            for i in range(top + 1):
                if i + q <= 3:
                    self.e(f"ldh a, [{h(S + i + q)}]")
                else:
                    self.e("ld a, d" if op == "asr" else "xor a")
                self.e(f"ldh [{h(T0 + i)}], a")
            for _ in range(r):
                first = "sra" if (op == "asr" and top == 3) else "srl"
                self.e(f"ld hl, {h(T0 + top)}", f"{first} [hl]")
                for i in range(top - 1, -1, -1):
                    self.e("dec l", "rr [hl]")
            for i in range(w):
                self.e(f"ldh a, [{h(T0 + i)}]", f"ldh [{h(rd + i)}], a")
        self.defined(x, x.rd, w)
        self.nz(rd, w, ext)
        self.stats["narrow_ops"] += 1

    def ins_mov_like(self, x, w, ext):
        rd = R(x.rd)
        src = self.opnd(x, x.a, w, T1)
        if src != rd:
            for i in range(w):
                self.e(f"ldh a, [{h(src + i)}]", f"ldh [{h(rd + i)}], a")
        self.defined(x, x.rd, w)
        self.nz(rd, w, ext)

    def fused(self, x, w, ext):
        kind, src_reg, dead = self.plan.fused[x.addr]
        nb = 1 if kind.endswith("b") else 2
        self.e(f"; {'dead' if dead else 'fused'} extension {kind} r{src_reg}")
        rd = R(x.rd)
        # the LSL was deleted, so the source slot still holds v0
        v0 = self.plan.fused_src[x.addr]
        S = R(src_reg)
        have = self.have(src_reg, v0)
        if have < nb:
            e0 = self.plan.store(v0)[1]
            self.e(f"ldh a, [{h(S + have - 1)}]", "rlca", "sbc a, a") if e0 == "s" else self.e("xor a")
            for i in range(have, nb):
                self.e(f"ldh [{h(S + i)}], a")
            self.valid[src_reg] = (v0, nb)
        n_copy = min(nb, w)
        if S != rd:
            for i in range(n_copy):
                self.e(f"ldh a, [{h(S + i)}]", f"ldh [{h(rd + i)}], a")
        if w > nb:
            if kind[0] == "s":
                self.e(f"ldh a, [{h(rd + nb - 1)}]", "rlca", "sbc a, a")
            else:
                self.e("xor a")
            for i in range(nb, w):
                self.e(f"ldh [{h(rd + i)}], a")
        self.defined(x, x.rd, w)
        if self.need("C"):
            self.e("xor a", f"ldh [{h(FC)}], a")  # bits shifted out are the LSL zeros
        self.nz(rd, w, ext)
        self.stats["narrow_ops"] += 1

    def mul_const(self, x, src_reg, c, w, ext):
        """rd = src * c for a proven constant c: unrolled shift-and-add over the set
        bits of c, on the w result bytes only (byte moves for shifts >= 8)."""
        self.ensure(x, src_reg, w)
        S, rd = R(src_reg), R(x.rd)
        for i in range(w):
            self.e(f"ldh a, [{h(S + i)}]", f"ldh [{h(T1 + i)}], a", "xor a", f"ldh [{h(T0 + i)}], a")
        shifted = 0
        for j in range(8 * w):
            if not (c >> j) & 1:
                continue
            d = j - shifted
            q, r = divmod(d, 8)
            if q:
                for i in reversed(range(w)):
                    self.e(f"ldh a, [{h(T1 + i - q)}]" if i - q >= 0 else "xor a", f"ldh [{h(T1 + i)}], a")
            for _ in range(r):
                self.e(f"ld hl, {h(T1)}", "sla [hl]")
                for i in range(1, w):
                    self.e("inc l", "rl [hl]")
            shifted = j
            self.e(f"ld hl, {h(T1)}")
            for i in range(w):
                self.e(f"ldh a, [{h(T0 + i)}]", "add a, [hl]" if i == 0 else "adc a, [hl]", f"ldh [{h(T0 + i)}], a")
                if i < w - 1:
                    self.e("inc l")
        for i in range(w):
            self.e(f"ldh a, [{h(T0 + i)}]", f"ldh [{h(rd + i)}], a")
        self.defined(x, x.rd, w)
        self.nz(rd, w, ext)
        self.stats["narrow_ops"] += 1

    def mul(self, x, w, ext):
        ra_, rb_ = int(x.a[1:]), int(x.b[1:])
        for r_c, r_o in ((ra_, rb_), (rb_, ra_)):
            vc = self.val(x, r_c)
            if vc is not None and vc.proven is not None and vc.proven[0] == vc.proven[1]:
                c = vc.proven[0] & ((1 << 8 * w) - 1)
                if bin(c).count("1") <= 20:
                    return self.mul_const(x, r_o, c, w, ext)
        self.ensure(x, ra_, 4)
        self.ensure(x, rb_, 4)
        va, vb = self.val(x, ra_), self.val(x, rb_)
        bl = lambda v: v.proven[1].bit_length() if v is not None and v.proven else 32
        # the multiplier (T2) is the operand with the shorter proven bit length
        if bl(va) < bl(vb):
            ra_, rb_, va, vb = rb_, ra_, vb, va
        iters = max(1, min(32, 8 * w, bl(vb)))
        self.copy(T2, R(rb_))
        self.copy(T1, R(ra_))
        self.e(f"ld c, {iters}", "call MUL32N")
        rd = R(x.rd)
        for i in range(w):
            self.e(f"ldh a, [{h(T0 + i)}]", f"ldh [{h(rd + i)}], a")
        self.defined(x, x.rd, w)
        self.nz(rd, w, ext)
        self.stats["narrow_ops"] += 1

    def mem(self, x, w, ext):
        if x.addr in self.hal and self.hal[x.addr]["region"] != "ram":
            self.ensure_all(x, 4)
            self.hal_mem(x)
            if not x.op.startswith("str"):
                self.defined(x, x.rd, 4)
            self.stats["fallback_ops"] += 1
            return
        base, idx, disp = x.mem
        self.ensure(x, base, 2)
        if idx is None and disp == 0:
            ad = R(base)
        else:
            if idx is not None:
                self.ensure(x, idx, 2)
                B = R(idx)
            else:
                B = None
            if B is None:
                # Phase P1: base + immediate straight into hl ($C000 | low 12 bits)
                self.e(f"ldh a, [{h(R(base))}]", f"add a, ${disp & 0xFF:02X}", "ld l, a",
                       f"ldh a, [{h(R(base) + 1)}]", f"adc a, ${(disp >> 8) & 0xFF:02X}",
                       "and $0F", "or $C0", "ld h, a")
                ad = None
            else:
                self.e(f"ldh a, [{h(R(base))}]", f"ld hl, {h(B)}", "add a, [hl]", f"ldh [{h(T1)}], a",
                       f"ldh a, [{h(R(base) + 1)}]", "inc l", "adc a, [hl]", f"ldh [{h(T1 + 1)}], a")
                ad = T1
        if ad is not None:
            self.hl_from(ad)
        n = {"": 4, "b": 1, "h": 2, "sb": 1, "sh": 2}[x.op[3:]]
        rd = R(x.rd)
        if x.op.startswith("str"):
            self.ensure(x, x.rd, n)
            for i in range(n):
                self.e(f"ldh a, [{h(rd + i)}]", "ld [hl+], a" if i < n - 1 else "ld [hl], a")
        else:
            for i in range(n):
                self.e("ld a, [hl+]" if i < n - 1 else "ld a, [hl]", f"ldh [{h(rd + i)}], a")
            if n < w:
                self.e("rlca", "sbc a, a") if x.op[3:] in ("sb", "sh") else self.e("xor a")
                for i in range(n, w):
                    self.e(f"ldh [{h(rd + i)}], a")
            self.defined(x, x.rd, max(n, w))
        self.stats["narrow_ops"] += 1


def generate_narrow_asm(plan, hal=None):
    g = NarrowGen(plan, hal)
    asm = g.generate().replace("(Phase 0)", f"(Phase 1, {plan.mode} pruning)")
    return asm, g.stats
