"""Indirect calls through Thumb-1 call-via stubs (tools/lift/icall.py)."""
import shutil
import subprocess

import pytest

from tools.lift import icall
from tools.lift.lift import lift_file

SRC = r'''
struct Base { virtual int f(int x) = 0; };
struct A : Base { int f(int x) override { return x + 1; } };
struct B : Base { int f(int x) override { return x * 3; } };
A a; B b;
volatile int sel;
__attribute__((noinline)) int call(Base* p, int x) { return p->f(x); }
int main(void) { Base* p = sel ? (Base*)&a : (Base*)&b; return call(p, 5); }
'''


@pytest.fixture
def elf(tmp_path):
    if not shutil.which("arm-none-eabi-g++"):
        pytest.skip("arm-none-eabi-g++ missing")
    c, out = tmp_path / "v.cpp", tmp_path / "v.elf"
    c.write_text(SRC)
    subprocess.run(["arm-none-eabi-g++", "-mcpu=arm7tdmi", "-mthumb", "-O2", "-nostdlib", "-fno-exceptions",
                    "-fno-rtti", "-Wl,-e,main", "-Wl,-Ttext=0x08000000", "-Wl,-Tdata=0x03000000",
                    str(c), "-o", str(out), "-lgcc"], check=True)
    return str(out)


def test_call_via_becomes_icall(elf):
    p = lift_file(elf, "main")
    calls = [x for x in p.ins.values() if x.op == "bl" and x.native and x.native.startswith("icall_")]
    assert calls and all(x.target is None for x in calls)
    names = {v: k for k, v in p.img.entries.items()}
    taken = {names[t] for t in p.img.taken if t in names}
    assert any("1A1f" in n for n in taken) and any("1B1f" in n for n in taken)
    assert all(t in p.funcs and t in p.ins for t in p.img.taken)    # lifted as roots
    a = icall.asm(p)
    assert "ICallDispatch" in a and "jp FarCall" in a
    for t in p.img.taken:
        assert f"BANK(L_{t:08X})" in a


def test_build_links(elf, tmp_path):
    if not shutil.which("rgbasm"):
        pytest.skip("rgbds missing")
    from tools.backend.gba2gbc_core import build
    build(elf, str(tmp_path / "v.gb"), entry="main")
    assert (tmp_path / "v.gb").stat().st_size >= 0x8000


SRC_F = r'''
__attribute__((noinline)) int fa(int x) { return x + 1; }
__attribute__((noinline)) int fb(int x) { return x * 3; }
__attribute__((noinline)) int call(int (*p)(int), int x) { return p(x) + 0; }
extern "C" int f(int s, int x) { return call(s ? fa : fb, x); }
'''


def test_dispatch_runs(tmp_path):
    for t in ("arm-none-eabi-g++", "rgbasm"):
        if not shutil.which(t):
            pytest.skip(f"{t} missing")
    pytest.importorskip("pyboy")
    c, out = tmp_path / "f.cpp", tmp_path / "f.elf"
    c.write_text(SRC_F)
    subprocess.run(["arm-none-eabi-g++", "-mcpu=arm7tdmi", "-mthumb", "-O2", "-nostdlib", "-fno-exceptions",
                    "-fno-rtti", "-Wl,-e,f", "-Wl,-Ttext=0x08000000", "-Wl,-Tdata=0x03000000",
                    str(c), "-o", str(out), "-lgcc"], check=True)
    from tools.backend.gba2gbc_core import build
    from tools.harness import GB
    rom = str(tmp_path / "f.gb")
    build(str(out), rom, entry="f")
    gb = GB(rom)
    try:
        for regs in ((1, 5), (0, 5), (1, 100), (0, 7)):
            assert gb.run(regs)[0] == ((regs[1] + 1) if regs[0] else regs[1] * 3)
    finally:
        gb.stop()


def test_udf_is_a_trap_loop():
    import capstone as cs
    from tools.lift.lift import convert, Image
    md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB)
    md.detail = True
    i = next(md.disasm(b"\xff\xde", 0x08000010, 1))
    x = convert(md, Image(b"\xff\xde", 0x08000010, {}), i)
    assert x.op == "b" and x.target == 0x08000010


SRC_SW = r'''
__attribute__((noinline)) int g(int k, int x) {
    switch (k) { case 0: return x + 7; case 1: return x * 5; case 2: return x - 3; case 3: return x ^ 9;
                 case 4: return x << 2; case 5: return x >> 1; case 6: return 100 - x; default: return 1; }
}
extern "C" int f(int k, int x) { return g(k, x); }
'''


def test_jump_table_runs(tmp_path):
    for t in ("arm-none-eabi-g++", "rgbasm"):
        if not shutil.which(t):
            pytest.skip(f"{t} missing")
    pytest.importorskip("pyboy")
    c, out = tmp_path / "s.cpp", tmp_path / "s.elf"
    c.write_text(SRC_SW)
    subprocess.run(["arm-none-eabi-g++", "-mcpu=arm7tdmi", "-mthumb", "-O2", "-nostdlib", "-fno-exceptions",
                    "-fno-rtti", "-Wl,-e,f", "-Wl,-Ttext=0x08000000", "-Wl,-Tdata=0x03000000",
                    str(c), "-o", str(out), "-lgcc"], check=True)
    p = lift_file(str(out), "f")
    if not p.jtabs:
        pytest.skip("compiler did not emit a jump table")
    from tools.backend.gba2gbc_core import build
    from tools.harness import GB
    rom = str(tmp_path / "s.gb")
    build(str(out), rom, entry="f")
    gb = GB(rom)
    exp = [lambda x: x + 7, lambda x: x * 5, lambda x: x - 3, lambda x: x ^ 9, lambda x: x << 2,
           lambda x: x >> 1, lambda x: 100 - x]
    try:
        for k in range(9):
            assert gb.run((k, 20))[0] == (exp[k](20) if k < 7 else 1) & 0xFFFFFFFF
    finally:
        gb.stop()
