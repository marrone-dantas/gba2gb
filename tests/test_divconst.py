"""ROM-table division by constant (tools/backend/divconst.py): the generated SM83
routines match C semantics for unsigned / signed quotient and remainder."""
import os
import random
import shutil
import subprocess
import pytest
from pyboy import PyBoy
from tools.backend.divconst import asm, eligible

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIVS = [3, 10, 60, 360, 960]


def build(tmp):
    src = ['INCLUDE "hram.inc"', 'SECTION "hdr", ROM0[$100]', "    nop", "    jp Start", 'SECTION "main", ROM0[$150]',
           "Start::", "    di", "    ld sp, $DFFF", "Loop::", "    nop", "    jr Loop", "FarCall::", "    ld [$2000], a",
           "    call .j", "    ld a, 1", "    ld [$2000], a", "    ret", ".j:", "    jp hl"]
    k = asm({(kd, d) for d in DIVS for kd in ("uidivmod", "idivmod")})
    open(tmp / "t.asm", "w").write("\n".join(src) + "\n" + k)
    o, rom = str(tmp / "t.o"), str(tmp / "t.gb")
    subprocess.run(["rgbasm", "-I", os.path.join(ROOT, "runtime"), "-o", o, str(tmp / "t.asm")], check=True)
    subprocess.run(["rgblink", "-o", rom, "-n", str(tmp / "t.sym"), o], check=True)
    subprocess.run(["rgbfix", "-v", "-p", "0xFF", "-m", "0x19", rom], check=True, capture_output=True)
    sym = {}
    for ln in open(tmp / "t.sym"):
        p = ln.split(";")[0].split()
        if len(p) == 2:
            sym[p[1]] = int(p[0].split(":")[1], 16)
    return rom, sym


@pytest.mark.skipif(not shutil.which("rgbasm"), reason="rgbds missing")
def test_divconst(tmp_path):
    rom, sym = build(tmp_path)
    pb = PyBoy(rom, window="null", cgb=False, sound_emulated=False)
    while not 0x150 <= pb.register_file.PC < 0x160:   # PyBoy's boot ROM runs first
        pb.tick(1, False)
    rnd = random.Random(1)
    m = pb.memory
    for d in DIVS:
        for signed in (False, True):
            for _ in range(40):
                x = rnd.choice([rnd.randrange(1 << 32), rnd.randrange(70000), rnd.randrange(300)])
                for i in range(4):
                    m[0xFF80 + i] = (x >> 8 * i) & 0xFF
                done = []
                stop = sym["Loop"]
                pb.hook_register(0, stop, lambda _: done.append(1), None)
                r = pb.register_file
                r.SP = 0xDFF0
                m[0xDFF0], m[0xDFF1] = stop & 0xFF, stop >> 8
                r.PC = sym[f"NAT_divc_{'idivmod' if signed else 'uidivmod'}_{d}"]
                for _ in range(30):
                    if done:
                        break
                    pb.tick(1, False)
                pb.hook_deregister(0, stop)
                q = int.from_bytes(bytes(m[0xFF80:0xFF84]), "little")
                rr = int.from_bytes(bytes(m[0xFF84:0xFF88]), "little")
                if signed:
                    sx = x - (1 << 32) if x >> 31 else x
                    eq, er = abs(sx) // d * (1 if sx >= 0 else -1), abs(sx) % d * (1 if sx >= 0 else -1)
                    assert (q, rr) == (eq & 0xFFFFFFFF, er & 0xFFFFFFFF), (d, x)
                else:
                    assert (q, rr) == (x // d, x % d), (d, x)
    pb.stop(save=False)


def test_eligible():
    assert eligible(3) and eligible(960) and not eligible(8) and not eligible(1) and not eligible(1001)
