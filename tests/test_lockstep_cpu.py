"""Teste lockstep da Fase 0: cada kernel roda no Unicorn (ARM7 Thumb, referência)
e no PyBoy headless (ROM SM83 gerada por gba2gbc-core) com as mesmas sementes
em R0-R3; R0 deve bater bit a bit (HRAM $FF80-$FF83).

Número de sementes por kernel: variável LOCKSTEP_SEEDS (padrão 1000).
Ciclos SM83 medidos pelo timer do runtime são gravados em build/ciclos.csv."""
import os
import random
import subprocess
import glob
import zlib
import pytest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB
from unicorn import arm_const as U
from elftools.elf.elffile import ELFFile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KDIR = os.path.join(ROOT, "tests", "kernels")
BUILD = os.path.join(ROOT, "build")
SEEDS = int(os.environ.get("LOCKSTEP_SEEDS", "1000"))
SP0 = 0x03001F00
SENTINEL = 0x08F00000
KERNELS = sorted(os.path.basename(p)[:-2] for p in glob.glob(os.path.join(KDIR, "k*.c")))


@pytest.fixture(scope="session", autouse=True)
def compilar():
    subprocess.run(["make", "-s", "-C", KDIR], check=True)
    os.makedirs(os.path.join(BUILD, "roms"), exist_ok=True)
    yield


class RefARM:
    def __init__(self, elf):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        self.uc.mem_map(0x08000000, 0x01000000)
        self.uc.mem_map(0x03000000, 0x10000)
        with open(elf, "rb") as fh:
            e = ELFFile(fh)
            t = e.get_section_by_name(".text")
            self.uc.mem_write(t["sh_addr"], t.data())
            self.entry = [s["st_value"] for s in e.get_section_by_name(".symtab").iter_symbols()
                          if s.name == "f"][0] & ~1

    def run(self, regs):
        uc = self.uc
        for r, v in zip((U.UC_ARM_REG_R0, U.UC_ARM_REG_R1, U.UC_ARM_REG_R2, U.UC_ARM_REG_R3), regs):
            uc.reg_write(r, v)
        uc.reg_write(U.UC_ARM_REG_SP, SP0)
        uc.reg_write(U.UC_ARM_REG_LR, SENTINEL | 1)
        uc.emu_start(self.entry | 1, SENTINEL, count=2_000_000)
        return uc.reg_read(U.UC_ARM_REG_R0) & 0xFFFFFFFF


class GB:
    def __init__(self, rom):
        from pyboy import PyBoy
        self.pb = PyBoy(rom, window="null", sound_emulated=False)
        self.pb.set_emulation_speed(0)
        # espera a boot ROM do PyBoy terminar e o runtime chegar ao laço de espera
        for _ in range(600):
            self.pb.tick(1, False)
            if self.pb.register_file.PC >= 0x150:
                break
        self.pb.tick(1, False)

    def run(self, regs):
        m = self.pb.memory
        for n, v in enumerate(list(regs) + [0] * 9 + [SP0, 0]):
            for i in range(4):
                m[0xFF80 + 4 * n + i] = (v >> (8 * i)) & 0xFF
        for a in range(0xFFC0, 0xFFC4):
            m[a] = 0
        m[0xFFD1] = 0
        m[0xFFD0] = 1
        for _ in range(20000):
            self.pb.tick(1, False)
            if m[0xFFD1] == 1:
                break
        else:
            raise TimeoutError("kernel SM83 não terminou")
        r0 = sum(m[0xFF80 + i] << (8 * i) for i in range(4))
        mcyc = ((m[0xFFD3] << 8 | m[0xFFD2]) * 256 + m[0xFFD4]) * 4
        return r0, mcyc

    def stop(self):
        self.pb.stop(save=False)


def seeds(name):
    rnd = random.Random(zlib.crc32(name.encode()))  # determinístico
    fixed = [(0, 0, 0, 0), (0xFFFFFFFF,) * 4, (0x80000000, 0x7FFFFFFF, 1, 0xFFFFFFFF), (1, 2, 3, 4)]
    out = fixed[:SEEDS]
    while len(out) < SEEDS:
        out.append(tuple(rnd.getrandbits(32) for _ in range(4)))
    return out


@pytest.mark.parametrize("kernel", KERNELS)
def test_lockstep(kernel):
    import sys
    sys.path.insert(0, ROOT)
    from tools.backend.gba2gbc_core import build
    elf = os.path.join(BUILD, "kernels", kernel + ".elf")
    rom = os.path.join(BUILD, "roms", kernel + ".gbc")
    build(elf, rom, asm_out=os.path.join(BUILD, "roms", kernel + ".asm"))
    ref, gb = RefARM(elf), GB(rom)
    total = 0
    falhas = []
    try:
        for s in seeds(kernel):
            exp = ref.run(s)
            got, cyc = gb.run(s)
            total += cyc
            if exp != got:
                falhas.append((s, exp, got))
                if len(falhas) >= 5:
                    break
    finally:
        gb.stop()
    with open(os.path.join(BUILD, "ciclos.csv"), "a") as fh:
        fh.write(f"{kernel},{SEEDS},{total / SEEDS:.0f}\n")
    assert not falhas, "divergências (R0..R3, esperado, obtido): " + "; ".join(
        f"{tuple(hex(v) for v in s)} {e:#010x} {g:#010x}" for s, e, g in falhas)
