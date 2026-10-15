"""Cosmetic loops (tools/lift/cosmetic.py) and array caps (tools/lift/array_cap.py)
on a synthetic ELF: the particle loop is found and removed / capped, the gameplay
loop (reads input, writes game state) is kept."""
import shutil
import subprocess
import capstone as cs
import pytest
from elftools.elf.elffile import ELFFile
from tools.lift.cosmetic import find, remove
from tools.lift.array_cap import cap_elf

SRC = r"""
typedef struct { int x, y, spd; } P;
P parts[16];
int score; unsigned rng = 1;
__attribute__((noinline)) void spr(int n, int x, int y) { *(volatile int *)0x06000000 = n + x + y; }
__attribute__((noinline)) int rnd(int m) { rng = rng * 1103515245u + 12345u; return (rng >> 16) % m; }
__attribute__((noinline)) void draw_parts(void) {
    for (P *p = parts; p != parts + 16; p++) {
        p->x += p->spd;
        if (p->x > 128) { p->x = 0; p->y = rnd(128); }
        spr(1, p->x, p->y);
    }
}
__attribute__((noinline)) void logic(void) {
    for (P *p = parts; p != parts + 16; p++) {
        if (*(volatile unsigned short *)0x04000130 & 1) score += p->x;
        spr(2, p->x, score);
    }
}
int main(void) { for (;;) { draw_parts(); logic(); } }
"""


@pytest.fixture(scope="module")
def elf(tmp_path_factory):
    if not shutil.which("arm-none-eabi-gcc"):
        pytest.skip("arm-none-eabi-gcc missing")
    d = tmp_path_factory.mktemp("cos")
    (d / "t.c").write_text(SRC)
    subprocess.run(["arm-none-eabi-gcc", "-mthumb", "-O2", "-nostdlib", "-Wl,-e,main", "-Wl,-Ttext=0x08000000",
                    "-Wl,-Tbss=0x02000000", "-o", str(d / "t.elf"), str(d / "t.c"), "-lgcc"], check=True)
    return str(d / "t.elf")


def test_find_and_remove(elf, tmp_path):
    loops = find(elf, {"spr"})
    assert [(l["func"], l["array"], l["count"]) for l in loops] == [("draw_parts", "parts", 16)]
    out = str(tmp_path / "r.elf")
    remove(elf, out, loops)
    with open(out, "rb") as fh:
        t = ELFFile(fh).get_section_by_name(".text")
        a, d = t["sh_addr"], t.data()
    h = loops[0]["header"]
    x = next(cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB).disasm(d[h - a:h - a + 2], h))
    assert x.mnemonic == "b" and int(x.op_str[1:], 16) == loops[0]["exit"]


def test_array_cap(elf, tmp_path):
    rep = cap_elf(elf, str(tmp_path / "c.elf"), {"parts": (4, 12)})
    assert any(r[1] == "draw_parts" and "->" in r[2] for r in rep)
