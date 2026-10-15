"""Large GBA ROM images in MBC5 banks 256.. (CONFIG["rom_banked"], HAL_ROMB_ADDR)."""
import os
import shutil
import subprocess

import pytest

from tools.backend.gba2gbc_core import build

DEMO_DIR = os.path.join(os.path.dirname(__file__), "demos")

SRC = r'''
#include "gba.h"
#define N 24000
static const unsigned short big[N] = { [0] = 0x1234, [9000] = 0x5678, [N - 1] = 0x9ABC };
volatile unsigned out[4];
int main(void) {
    volatile unsigned i = 9000, j = N - 1;
    out[0] = big[0]; out[1] = big[i]; out[2] = big[j]; out[3] = 0xA5;
    while (1) { __asm__ volatile("swi 5"); }
}
'''


def test_rom_banked_reads(tmp_path):
    for t in ("arm-none-eabi-gcc", "rgbasm"):
        if not shutil.which(t):
            pytest.skip(f"{t} missing")
    pytest.importorskip("pyboy")
    c, e = tmp_path / "t.c", tmp_path / "t.elf"
    c.write_text(SRC)
    subprocess.run(["arm-none-eabi-gcc", "-mcpu=arm7tdmi", "-mthumb", "-O2", "-ffreestanding", "-nostdlib",
                    "-fno-builtin", "-I", DEMO_DIR, "-T", os.path.join(DEMO_DIR, "gba.ld"), "-o", str(e),
                    os.path.join(DEMO_DIR, "crt0.s"), str(c)], check=True)
    rom = str(tmp_path / "t.gbc")
    port = {"rom_banked": True, "defines": ["ROM_BANKED"]}
    build(str(e), rom, entry="main", hal=True, port=port, snapshot=False, late_vsync=False)
    assert os.path.getsize(rom) >= (256 + 3) * 0x4000
    from tools.hal.gb_run import GBRun
    from elftools.elf.elffile import ELFFile
    with open(e, "rb") as fh:
        out = next(s["st_value"] for s in ELFFile(fh).get_section_by_name(".symtab").iter_symbols() if s.name == "out")
    g = GBRun(rom, check_access=False)
    try:
        for _ in range(600):
            g.tick()
            if g.frame() >= 3:
                break
        w = lambda k: sum(g.m[0xC000 | ((out + 4 * k + i) & 0xFFF)] << (8 * i) for i in range(4))
        assert [w(k) for k in range(4)] == [0x1234, 0x5678, 0x9ABC, 0xA5]
    finally:
        g.stop()


SRC_CTOR = r'''
volatile unsigned out[2];
struct S { S() { out[0] = 0x77; } } s;
int main(void) { out[1] = out[0] + 1; while (1) { __asm__ volatile("swi 5"); } }
'''


def test_static_constructors_run_before_main(tmp_path):
    for t in ("arm-none-eabi-g++", "rgbasm"):
        if not shutil.which(t):
            pytest.skip(f"{t} missing")
    pytest.importorskip("pyboy")
    c, e = tmp_path / "t.cpp", tmp_path / "t.elf"
    c.write_text(SRC_CTOR)
    subprocess.run(["arm-none-eabi-g++", "-mcpu=arm7tdmi", "-mthumb", "-O2", "-ffreestanding", "-nostdlib",
                    "-fno-exceptions", "-fno-rtti", "-T", os.path.join(DEMO_DIR, "gba.ld"), "-o", str(e),
                    os.path.join(DEMO_DIR, "crt0.s"), str(c)], check=True)
    from tools.lift.lift import lift_file
    assert lift_file(str(e), "main").inits
    rom = str(tmp_path / "t.gbc")
    build(str(e), rom, entry="main", hal=True, snapshot=False, late_vsync=False)
    from tools.hal.gb_run import GBRun
    from elftools.elf.elffile import ELFFile
    with open(e, "rb") as fh:
        out = next(s["st_value"] for s in ELFFile(fh).get_section_by_name(".symtab").iter_symbols() if s.name == "out")
    g = GBRun(rom, check_access=False)
    try:
        for _ in range(600):
            g.tick()
            if g.frame() >= 3:
                break
        assert g.m[0xC000 | (out & 0xFFF)] == 0x77 and g.m[0xC000 | ((out + 4) & 0xFFF)] == 0x78
    finally:
        g.stop()


SRC_DMA = r'''
static const unsigned src32[6] = {0x11223344, 0x55667788, 0x99AABBCC, 0xDDEEFF00, 0x01020304, 0x0A0B0C0D};
volatile unsigned dst[8];
volatile unsigned short dst16[4];
int main(void) {
    volatile unsigned* d3 = (volatile unsigned*)0x040000D4;
    d3[0] = (unsigned)src32; d3[1] = (unsigned)dst; d3[2] = 6 | (1u << 26) | (1u << 31);
    unsigned short v = 0xBEEF;
    d3[0] = (unsigned)&v; d3[1] = (unsigned)dst16; d3[2] = 4 | (2u << 23) | (1u << 31);  /* fixed source fill */
    dst[7] = 0xA5;
    while (1) { __asm__ volatile("swi 5"); }
}
'''


def test_dma3_immediate_copy(tmp_path):
    for t in ("arm-none-eabi-gcc", "rgbasm"):
        if not shutil.which(t):
            pytest.skip(f"{t} missing")
    pytest.importorskip("pyboy")
    c, e = tmp_path / "t.c", tmp_path / "t.elf"
    c.write_text(SRC_DMA)
    subprocess.run(["arm-none-eabi-gcc", "-mcpu=arm7tdmi", "-mthumb", "-O2", "-ffreestanding", "-nostdlib",
                    "-fno-builtin", "-T", os.path.join(DEMO_DIR, "gba.ld"), "-o", str(e),
                    os.path.join(DEMO_DIR, "crt0.s"), str(c)], check=True)
    rom = str(tmp_path / "t.gbc")
    build(str(e), rom, entry="main", hal=True, port={"rom_banked": True, "defines": ["ROM_BANKED"]},
          snapshot=False, late_vsync=False)
    from tools.hal.gb_run import GBRun
    from elftools.elf.elffile import ELFFile
    with open(e, "rb") as fh:
        syms = {s.name: s["st_value"] for s in ELFFile(fh).get_section_by_name(".symtab").iter_symbols()}
    g = GBRun(rom, check_access=False)
    try:
        for _ in range(600):
            g.tick()
            if g.frame() >= 3:
                break
        rd = lambda a, n: sum(g.m[0xC000 | ((a + i) & 0xFFF)] << (8 * i) for i in range(n))
        d = syms["dst"]
        assert [rd(d + 4 * k, 4) for k in range(6)] == [0x11223344, 0x55667788, 0x99AABBCC, 0xDDEEFF00,
                                                         0x01020304, 0x0A0B0C0D]
        assert rd(d + 28, 4) == 0xA5
        assert [rd(syms["dst16"] + 2 * k, 2) for k in range(4)] == [0xBEEF] * 4
    finally:
        g.stop()
