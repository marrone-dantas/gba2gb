"""Shared execution harness: Unicorn reference (ARM7 Thumb) and headless PyBoy
runner for the generated ROMs (used by the lockstep tests and the Phase 1 report)."""
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB
from unicorn import arm_const as U
from elftools.elf.elffile import ELFFile

SP0 = 0x03001F00
SENTINEL = 0x08F00000


class GuardFired(AssertionError):
    pass


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
        # wait for PyBoy's boot ROM to finish and the runtime to reach its wait loop
        for _ in range(600):
            self.pb.tick(1, False)
            if self.pb.register_file.PC >= 0x150:
                break
        self.pb.tick(1, False)

    def run(self, regs, fill=None):
        """Run the kernel once. `fill`: byte written to the non-argument register
        bytes (r4-r12, LR, PC) instead of 0 (used to measure HRAM usage)."""
        m = self.pb.memory
        for n, v in enumerate(list(regs) + [0] * 9 + [SP0, 0]):
            for i in range(4):
                a = 0xFF80 + 4 * n + i
                m[a] = fill if fill is not None and n >= 4 and n != 13 else (v >> (8 * i)) & 0xFF
        for a in range(0xFFC0, 0xFFC4):
            m[a] = 0
        m[0xFFD1] = 0
        m[0xFFD0] = 1
        for _ in range(20000):
            self.pb.tick(1, False)
            if m[0xFFD1]:
                break
        else:
            raise TimeoutError("SM83 kernel did not finish")
        if m[0xFFD1] == 2:
            raise GuardFired(f"range guard {m[0xFFD5]} fired for seed {regs}")
        r0 = sum(m[0xFF80 + i] << (8 * i) for i in range(4))
        mcyc = ((m[0xFFD3] << 8 | m[0xFFD2]) * 256 + m[0xFFD4]) * 4
        return r0, mcyc

    def stop(self):
        self.pb.stop(save=False)



    def hram_touched(self, regs, patterns=(0xA5, 0x5A)):
        """HRAM register-area bytes ($FF80-$FFBF) used in one run: bytes written by the
        kernel plus the argument bytes (r0-r3) and SP, which the caller provides."""
        m = self.pb.memory
        used = {0xFF80 + i for i in range(16)} | {0xFFB4 + i for i in range(4)}
        for pat in patterns:
            self.run(regs, fill=pat)
            used |= {a for a in range(0xFF90, 0xFFC0) if not 0xFFB4 <= a < 0xFFB8 and m[a] != pat}
        return used

    def wram_touched(self, regs, patterns=(0xA5, 0x5A)):
        """Set of WRAM addresses ($C000-$DFFF) written during one run."""
        m = self.pb.memory
        touched = set()
        for pat in patterns:
            for a in range(0xC000, 0xE000):
                m[a] = pat
            self.run(regs)
            touched |= {a for a in range(0xC000, 0xE000) if m[a] != pat}
        return touched
