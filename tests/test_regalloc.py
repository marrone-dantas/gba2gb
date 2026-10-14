"""Tests for tools/prune/regalloc.py (Phase 1.5 item 4: HRAM allocation per web)."""
import glob
import os
import subprocess
import pytest
from tools.lift.lift import lift_file
from tools.prune.regalloc import allocate, PINNED_OPS
from tools.backend.gba2gbc_core import build
from tools.backend.hram_usage import hram_reg_bytes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB = os.path.join(ROOT, "build", "kernels")


@pytest.fixture(scope="module", autouse=True)
def kernels():
    subprocess.run(["make", "-s", "-C", os.path.join(ROOT, "tests", "kernels")], check=True)


def elf(name):
    return glob.glob(os.path.join(KB, name + "*.elf"))[0]


@pytest.mark.parametrize("abi", ["aapcs", "none"])
def test_pinned_instructions_untouched(abi):
    for e in sorted(glob.glob(os.path.join(KB, "k*.elf"))):
        before = {a: (x.rd, x.a, x.b, x.mem, list(x.regs)) for a, x in lift_file(e).ins.items()}
        p = lift_file(e)
        allocate(p, abi)
        for a, x in p.ins.items():
            if x.op in PINNED_OPS:
                assert before[a] == (x.rd, x.a, x.b, x.mem, list(x.regs))
            assert x.rd is None or x.rd < 16


def asm_of(name, tmp_path, **opts):
    asm = tmp_path / f"{name}.asm"
    build(elf(name), str(tmp_path / f"{name}.gbc"), asm_out=str(asm), prune="sound", opts=opts)
    return hram_reg_bytes(asm.read_text())


def test_entry_abi_allocation_saves_hram(tmp_path):
    # k18 with the opt-in entry ABI: values of r3/r6/r7 reuse dead argument slots
    assert asm_of("k18", tmp_path, entry_abi="none") < asm_of("k18", tmp_path, entry_abi="none", hram_alloc=False)


def test_allocation_never_worse(tmp_path):
    for k in ("k02", "k04", "k15", "k19"):
        for abi in ("aapcs", "none"):
            assert asm_of(k, tmp_path, entry_abi=abi) <= asm_of(k, tmp_path, entry_abi=abi, hram_alloc=False)
