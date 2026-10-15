"""Step 10 render decimation detection (tools/lift/decimate.py)."""
import shutil
import subprocess

import pytest

from tools.lift import lift, decimate

SRC = r'''
volatile int st, oam;
__attribute__((noinline)) void put(int x) { oam = x; }
__attribute__((noinline)) void logic(void) { st++; }
__attribute__((noinline)) void draw(void) { put(st); put(st + 1); }
int main(void) { for (;;) { __asm__ volatile("svc 5"); logic(); draw(); } }
'''


@pytest.fixture
def elf(tmp_path):
    if not shutil.which("arm-none-eabi-gcc"):
        pytest.skip("arm-none-eabi-gcc missing")
    c, o = tmp_path / "d.c", tmp_path / "d.elf"
    c.write_text(SRC)
    subprocess.run(["arm-none-eabi-gcc", "-mthumb", "-O2", "-nostdlib", "-Wl,-e,main", "-Wl,-Ttext=0x08000000",
                    "-Wl,-Tdata=0x03000000", str(c), "-o", str(o)], check=True)
    return str(o)


def test_render_sites(elf, monkeypatch):
    monkeypatch.setitem(lift.DECIMATE, "n", 2)
    monkeypatch.setitem(lift.DECIMATE, "render", {"put"})
    p = lift.lift_file(elf, "main")
    draw = p.img.entries["draw"]
    assert [t for _, t, _ in p.decim] == [f"L_{draw:08X}"]
    assert p.decim[-1][2]
    a = decimate.asm(p.decim, 2)
    assert "NAT_decim_0::" in a and "wDecimCnt" in a and "cp 2" in a


def test_no_split_without_logic(elf, monkeypatch):
    monkeypatch.setitem(lift.DECIMATE, "n", 2)
    monkeypatch.setitem(lift.DECIMATE, "render", {"put", "st"})
    p = lift.lift_file(elf, "main")
    assert p.decim and all("decim" in p.ins[a].native for a in p.ins if p.ins[a].op == "bl"
                           and p.ins[a].native and "decim" in p.ins[a].native)
    monkeypatch.setitem(lift.DECIMATE, "render", set())
    assert lift.lift_file(elf, "main").decim == []
