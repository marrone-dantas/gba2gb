"""Phase 2.1: static I/O interceptor (tools/hal/intercept.py) and HAL lowering."""
import os
import subprocess
import pytest
from tools.lift.lift import lift_file
from tools.prune import range_analysis as ra
from tools.hal.intercept import classify, InterceptError
from tools.hal.demos import make, elf, ROOT
from tools.backend.gba2gbc_core import build

DEMO_DIR = os.path.join(ROOT, "tests", "demos")


@pytest.fixture(scope="module", autouse=True)
def demos():
    make()


def regions(name):
    ssa = ra.SSAProgram(lift_file(elf(name), "main"))
    ra.analyze(ssa)
    acc, warnings = classify(ssa)
    return acc, warnings


@pytest.mark.parametrize("name", ["obj_demo", "key_demo", "brin_demo", "oam_stress", "input_test"])
def test_demo_accesses_resolved(name):
    acc, warnings = regions(name)
    kinds = {d["region"] for d in acc.values()}
    assert "io" in kinds and "rom" in kinds
    for d in acc.values():
        if d["region"] in ("io", "oam"):
            assert d["const"] is not None
    assert warnings == []


def test_literal_pool_base_plus_offset():
    acc, _ = regions("obj_demo")
    consts = {d["const"] for d in acc.values() if d["region"] == "oam"}
    # attr0/1/2 of objects 0-3: base 0x07000000 from the literal pool + offsets
    assert {0x07000000, 0x07000002, 0x07000004, 0x0700001C} <= consts


def compile_c(tmp_path, src):
    c = tmp_path / "t.c"
    c.write_text('#include "gba.h"\n' + src)
    out = tmp_path / "t.elf"
    subprocess.run(["arm-none-eabi-gcc", "-mcpu=arm7tdmi", "-mthumb", "-O2", "-ffreestanding", "-nostdlib",
                    "-fno-builtin", "-I", DEMO_DIR, "-T", os.path.join(DEMO_DIR, "gba.ld"), "-o", str(out),
                    os.path.join(DEMO_DIR, "crt0.s"), str(c)], check=True)
    return str(out)


def test_nonconstant_io_is_compile_error(tmp_path):
    e = compile_c(tmp_path, "int main(void){ u32 i = REG_KEYINPUT & 7;"
                            " ((volatile u16 *)0x04000000)[i] = 1; while (1) ; }")
    with pytest.raises(InterceptError) as ex:
        build(e, str(tmp_path / "t.gbc"), entry="main", prune="sound", hal=True)
    assert "non-constant IO address" in str(ex.value) and "0x080" in str(ex.value)


def test_nonconstant_oam_is_compile_error(tmp_path):
    e = compile_c(tmp_path, "int main(void){ u32 i = REG_KEYINPUT & 3;"
                            " ((volatile u16 *)0x07000000)[4 * i] = 0x200; while (1) ; }")
    with pytest.raises(InterceptError) as ex:
        build(e, str(tmp_path / "t.gbc"), entry="main", prune="sound", hal=True)
    assert "OAM" in str(ex.value)


def test_unsupported_bios_call_is_error(tmp_path):
    e = compile_c(tmp_path, 'int main(void){ __asm__ volatile("swi 6"); while (1) ; }')
    with pytest.raises(InterceptError) as ex:
        build(e, str(tmp_path / "t.gbc"), entry="main", prune="sound", hal=True)
    assert "swi 6" in str(ex.value)


@pytest.mark.parametrize("prune", [None, "sound"])
def test_data_bss_initialised(tmp_path, prune):
    from tools.hal.gb_run import GBRun
    from tools.hal.demos import build_demo
    rom, _ = build_demo("obj_demo", prune)
    g = GBRun(rom, check_access=False)
    try:
        while g.frame() < 2:
            g.tick()
        # .data px = 96, py = 32 at 0x03000000 -> $C000; .bss key_cur/key_prev after
        assert g.m[0xC000] == 96 and g.m[0xC004] == 32
        assert all(g.m[0xC008 + i] == 0 for i in range(8))
    finally:
        g.stop()
