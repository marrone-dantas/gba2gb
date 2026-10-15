"""Step 9 constant specialization (lift.Program._specialize)."""
import shutil
import subprocess

import pytest

from tools.lift import lift
from tools.prune import range_analysis as ra

SRC = r'''
volatile int out;
__attribute__((noinline)) int scale(int k, int x) { int s = 0; for (int i = 0; i < k; i++) s += x; return s; }
int main(void) { out = scale(3, out); out = scale(5, out); return 0; }
'''


@pytest.fixture
def elf(tmp_path):
    if not shutil.which("arm-none-eabi-gcc"):
        pytest.skip("arm-none-eabi-gcc missing")
    c, o = tmp_path / "s.c", tmp_path / "s.elf"
    c.write_text(SRC)
    subprocess.run(["arm-none-eabi-gcc", "-mthumb", "-O2", "-nostdlib", "-Wl,-e,main", "-Wl,-Ttext=0x08000000",
                    "-Wl,-Tdata=0x03000000", str(c), "-o", str(o), "-lgcc"], check=True)
    return str(o)


def test_clone_per_constant(elf, monkeypatch):
    monkeypatch.setitem(lift.CLONE, "enabled", True)
    p = lift.lift_file(elf, "main")
    consts = sorted(k[0] for _, k in p.clones.values())
    assert consts == [3, 5]
    s = ra.SSAProgram(p)
    ra.analyze(s)
    for c, (_, k) in p.clones.items():
        assert s.funcs[c].params[0].proven[:2] == (k[0], k[0])


def test_off_by_default(elf):
    assert lift.lift_file(elf, "main").clones == {}
