"""Tests for tools/prune/frame.py (Phase 1.5: save-slot elision)."""
import glob
import os
import subprocess
import pytest
from tools.lift.lift import lift_file
from tools.prune import range_analysis as ra
from tools.prune.frame import Frame, sp_offsets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB = os.path.join(ROOT, "build", "kernels")
GCC = ["arm-none-eabi-gcc", "-mcpu=arm7tdmi", "-mthumb", "-O2", "-ffreestanding", "-nostdlib",
       "-fno-builtin", "-fno-jump-tables", "-Wl,-Ttext=0x08000000", "-Wl,-e,f"]


@pytest.fixture(scope="module", autouse=True)
def kernels():
    subprocess.run(["make", "-s", "-C", os.path.join(ROOT, "tests", "kernels")], check=True)


def ssa_of(name):
    return ra.SSAProgram(lift_file(glob.glob(os.path.join(KB, name + "*.elf"))[0]))


def test_sp_offsets_balance():
    ssa = ssa_of("k05")
    off = sp_offsets(ssa)
    for a, env in ssa.ret_envs.items():
        assert off[env[13]] == 0  # SP is back at the entry value at every return


def test_lr_slot_elided_by_default():
    ssa = ssa_of("k02")
    fr = Frame(ssa)
    (push, regs), = fr.skip_push.items()
    assert ssa.prog.ins[push].op == "push" and regs == {14}


def test_lr_kept_when_disabled():
    assert not Frame(ssa_of("k02"), skip_lr=False).skip_push


def test_entry_abi_none_elides_callee_saved():
    fr = Frame(ssa_of("k02"), entry_abi="none")
    assert set().union(*fr.skip_push.values()) == {4, 5, 6, 7, 14}


def test_callee_keeps_abi_in_entry_mode():
    """Only the program entry gets the relaxed ABI; callees keep callee-saved regs."""
    ssa = ssa_of("k17")
    fr = Frame(ssa, entry_abi="none")
    for a in fr.skip_push:
        assert ssa.func_of[ssa.envs[a][13]] == ssa.prog.entry


def test_lr_holding_r9_is_kept(tmp_path):
    """`mov lr, r9; push {r7, lr}` saves a callee-saved register in the LR slot."""
    e = str(tmp_path / "j.elf")
    subprocess.run(GCC + ["-o", e, os.path.join(ROOT, "tests", "physics", "jump_q16.c")], check=True)
    ssa = ra.SSAProgram(lift_file(e))
    fr = Frame(ssa)
    second = [a for a, x in ssa.prog.ins.items() if x.op == "push"][1]
    assert second not in fr.skip_push


def trims_of(name):
    from tools.prune.frame import frame_trims
    ssa = ssa_of(name)
    ra.analyze(ssa)
    return frame_trims(ssa, sp_offsets(ssa))


def test_frame_trim_padding():
    # k02: 16 bytes of locals in a 20-byte frame; k18: 8 bytes in 12 (alignment padding)
    assert sorted(trims_of("k02").values()) == [16, 16]
    assert sorted(trims_of("k18").values()) == [8, 8]


def test_frame_trim_escape_blocks():
    # k05 walks its array with a pointer induction variable (no bounded interval):
    # the pointer escapes the analysis, so the frame is kept as is
    assert trims_of("k05") == {}
