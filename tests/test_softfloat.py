"""Phase 5 B2: native SM83 soft-float / integer helpers (runtime/gb_softfloat.asm)
in lockstep with the real libgcc AEABI helpers. Each tests/softfloat/s_<op>.c kernel
calls one helper; the Unicorn reference runs libgcc, the GB ROM (lifted with the
helper replaced by `call NAT_<op>`) runs the native code. R0 and R1 must match bit
for bit. Inputs: edge values (zeros, subnormals, infinities, NaNs, extremes,
ties) plus random patterns biased towards close exponents.

Count per op: SOFTFLOAT_SEEDS (default 300)."""
import os
import random
import struct
import subprocess
import pytest
from unicorn import arm_const as U
from tools.harness import RefARM, GB, SP0, SENTINEL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDIR = os.path.join(ROOT, "tests", "softfloat")
BUILD = os.path.join(ROOT, "build", "softfloat")
N = int(os.environ.get("SOFTFLOAT_SEEDS", "300"))

DEDGE = [0, 1 << 63, 1, 0x000FFFFFFFFFFFFF, 0x0010000000000000, 0x3FF0000000000000,
         0xBFF0000000000000, 0x7FEFFFFFFFFFFFFF, 0x7FF0000000000000, 0xFFF0000000000000,
         0x7FF8000000000000, 0x7FF0000000000001, 0xFFF4000000000123, 0x3FF0000000000001,
         0x3CA0000000000000, 0x4330000000000000, 0x8010000000000000, 0x3FE0000000000000]
FEDGE = [0, 0x80000000, 1, 0x007FFFFF, 0x00800000, 0x3F800000, 0xBF800000, 0x7F7FFFFF,
         0x7F800000, 0xFF800000, 0x7FC00000, 0x7F800001, 0xFFA00123, 0x3F800001,
         0x33800000, 0x4F000000, 0xCF000000, 0x4EFFFFFF, 0x3F000000, 0xBF7FFFFF]
IEDGE = [0, 1, 0xFFFFFFFF, 0x7FFFFFFF, 0x80000000, 2, 0xFFFFFFFE, 7, 0xFFFFFFF9,
         0x01000001, 0x00FFFFFF, 0x12345678]


def rd(r):
    """random double pattern: mostly moderate exponents, sometimes anything"""
    if r.random() < 0.2:
        return r.getrandbits(64)
    e = r.randrange(1023 - 40, 1023 + 40)
    return (r.getrandbits(1) << 63) | (e << 52) | r.getrandbits(52)


def rf(r):
    if r.random() < 0.2:
        return r.getrandbits(32)
    e = r.randrange(127 - 20, 127 + 20)
    return (r.getrandbits(1) << 31) | (e << 23) | r.getrandbits(23)


def near(r, x, bits, mbits):
    """a value with an exponent close to x (exercises alignment / cancellation)"""
    d = r.randrange(-3, 4) << mbits
    m = x + d + r.randrange(-8, 9) if r.random() < 0.5 else (x & ~((1 << mbits) - 1)) | r.getrandbits(mbits)
    return m & ((1 << bits) - 1)


def split(x):
    return [x & 0xFFFFFFFF, x >> 32]


def cases(op):
    r = random.Random(f"softfloat-{op}")
    out = []
    if op in ("dadd", "dsub", "dmul"):
        out += [split(a) + split(b) for a in DEDGE for b in DEDGE]
        for _ in range(N):
            a = rd(r)
            b = near(r, a, 64, 52) if r.random() < 0.5 else rd(r)
            out.append(split(a) + split(b))
    elif op == "lmul":
        ed = [0, 1, (1 << 64) - 1, 1 << 63, 0xFFFFFFFF, 1 << 32, 0x123456789ABCDEF0]
        out += [split(a) + split(b) for a in ed for b in ed]
        out += [split(r.getrandbits(64)) + split(r.getrandbits(r.choice((8, 16, 32, 64))))
                for _ in range(N)]
    elif op in ("fadd", "fsub", "fmul", "fcmpeq", "fcmplt", "fcmpgt"):
        out += [[a, b] for a in FEDGE for b in FEDGE]
        for _ in range(N):
            a = rf(r)
            b = near(r, a, 32, 23) if r.random() < 0.5 else (a if r.random() < 0.05 else rf(r))
            out.append([a, b])
    elif op in ("i2d", "i2f"):
        out += [[a] for a in IEDGE] + [[r.getrandbits(r.choice((8, 24, 25, 32)))] for _ in range(N)]
    elif op == "f2d":
        out += [[a] for a in FEDGE] + [[r.getrandbits(32)] for _ in range(N)]
    elif op == "d2f":
        # doubles in and around the float range, and halfway (tie) cases
        out += [split(a) for a in DEDGE]
        for _ in range(N):
            e = r.randrange(1023 - 160, 1023 + 140)
            m = r.getrandbits(52)
            if r.random() < 0.3:
                m = (m & ~((1 << 29) - 1)) | (1 << 28)        # exact tie
            out.append(split((r.getrandbits(1) << 63) | (e << 52) | m))
    elif op == "f2iz":
        out += [[a] for a in FEDGE] + [[0xCF000000], [0xCF000001], [0x4F000000], [0xBF7FFFFF]]
        for _ in range(N):
            e = r.randrange(120, 160)
            out.append([(r.getrandbits(1) << 31) | (e << 23) | r.getrandbits(23)])
    elif op in ("idiv", "idivmod", "uidiv", "uidivmod"):
        out += [[a, b] for a in IEDGE for b in IEDGE]
        out += [[r.getrandbits(r.choice((8, 16, 32))), r.getrandbits(r.choice((4, 8, 16, 32)))]
                for _ in range(N)]
    return out


class Ref2(RefARM):
    def run2(self, regs):
        uc = self.uc
        regs = list(regs) + [0] * (4 - len(regs))
        for r, v in zip((U.UC_ARM_REG_R0, U.UC_ARM_REG_R1, U.UC_ARM_REG_R2, U.UC_ARM_REG_R3), regs):
            uc.reg_write(r, v)
        uc.reg_write(U.UC_ARM_REG_SP, SP0)
        uc.reg_write(U.UC_ARM_REG_LR, SENTINEL | 1)
        uc.emu_start(self.entry | 1, SENTINEL, count=2_000_000)
        return uc.reg_read(U.UC_ARM_REG_R0), uc.reg_read(U.UC_ARM_REG_R1)


def gb_run2(gb, regs):
    regs = list(regs) + [0] * (4 - len(regs))
    r0, cyc = gb.run(regs)
    m = gb.pb.memory
    return (r0, sum(m[0xFF84 + i] << (8 * i) for i in range(4))), cyc


OPS = sorted(f[2:-2] for f in os.listdir(SDIR) if f.startswith("s_") and f.endswith(".c"))
DOUBLE_RESULT = {"dadd", "dsub", "dmul", "lmul", "i2d", "f2d", "idivmod", "uidivmod"}


@pytest.fixture(scope="module", autouse=True)
def build_kernels():
    subprocess.run(["make", "-s", "-C", SDIR], check=True)


@pytest.mark.parametrize("op", OPS)
def test_softfloat_lockstep(op):
    from tools.backend.gba2gbc_core import build
    elf = os.path.join(BUILD, f"s_{op}.elf")
    rom = os.path.join(BUILD, f"s_{op}.gbc")
    prog = build(elf, rom, asm_out=rom[:-4] + ".asm")
    calls = [i for i in prog.ins.values() if getattr(i, "native", None)]
    assert calls and calls[0].native == op, "helper was not replaced by the native routine"
    ref, gb = Ref2(elf), GB(rom)
    fails, total, cmax = [], 0, 0
    try:
        for regs in cases(op):
            exp = ref.run2(regs)
            got, cyc = gb_run2(gb, regs)
            total += 1
            cmax = max(cmax, cyc)
            if op not in DOUBLE_RESULT:
                exp, got = exp[0], got[0]
            if exp != got:
                fails.append(([hex(x) for x in regs], exp, got))
                if len(fails) >= 6:
                    break
    finally:
        gb.stop()
    assert not fails, f"{op}: {len(fails)} mismatches, first: {fails}"
    with open(os.path.join(BUILD, "cycles.csv"), "a") as fh:
        fh.write(f"{op},{total},{cmax}\n")
