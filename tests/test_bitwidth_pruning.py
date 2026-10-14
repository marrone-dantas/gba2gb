"""Unit tests for tools/prune/bitwidth_pruning.py (Phase 1 B1)."""
import glob
import os
import subprocess
import pytest
from tools.lift.lift import lift_file
from tools.prune import bitwidth_pruning as bp
from tools.prune import range_analysis as ra
from tools.profile.range_tracer import trace_kernel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB = os.path.join(ROOT, "build", "kernels")
GCC = ["arm-none-eabi-gcc", "-mcpu=arm7tdmi", "-mthumb", "-O2", "-ffreestanding", "-nostdlib",
       "-fno-builtin", "-fno-jump-tables", "-Wl,-Ttext=0x08000000", "-Wl,-e,f"]


@pytest.fixture(scope="module", autouse=True)
def kernels():
    subprocess.run(["make", "-s", "-C", os.path.join(ROOT, "tests", "kernels")], check=True)


def elf(name):
    return glob.glob(os.path.join(KB, name + "*.elf"))[0]


def asm_elf(tmp_path, body):
    s = tmp_path / "k.s"
    s.write_text(".syntax unified\n.thumb\n.global f\n.thumb_func\nf:\n" + body)
    out = str(tmp_path / "k.elf")
    subprocess.run(GCC + ["-o", out, str(s)], check=True)
    return out


def test_counter_web_is_one_byte():
    plan = bp.build_plan(elf("k15"))
    phi = [v for v in plan.ssa.values if v.kind == "phi" and v.reg == 2][0]
    assert plan.store(phi) == (1, "z")
    # params and SP are never narrowed
    for v in plan.ssa.values:
        if v.kind == "param" or v.reg == 13:
            assert plan.store(v)[0] == 4


def test_web_members_share_storage():
    plan = bp.build_plan(elf("k19"))
    for web in bp.webs(plan.ssa):
        assert len({plan.store(v) for v in web}) == 1


def test_storage_contains_proven_range():
    for e in sorted(glob.glob(os.path.join(KB, "k*.elf"))):
        plan = bp.build_plan(e)
        for v in plan.ssa.values:
            n, ext = plan.store(v)
            if n < 4 and v.proven is not None:
                lim = ra.urange(0, (1 << 8 * n) - 1) if ext == "z" else ra.srange(-(1 << 8 * n - 1), (1 << 8 * n - 1) - 1)
                assert ra.meet(v.proven, lim) == v.proven, (e, v)


def test_extension_fusion_found():
    plan = bp.build_plan(elf("k18"))
    assert plan.fused
    for a in plan.deleted:
        assert plan.ssa.prog.ins[a].op == "lsl"


def test_dead_extension(tmp_path):
    e = asm_elf(tmp_path, "movs r1, #255\nands r0, r1\nlsls r0, r0, #24\nlsrs r0, r0, #24\nbx lr\n")
    plan = bp.build_plan(e)
    (kind, src, dead), = plan.fused.values()
    assert kind == "uxtb" and src == 0 and dead


def test_no_fusion_when_flags_read(tmp_path):
    e = asm_elf(tmp_path, "lsls r0, r0, #24\nbeq 1f\nlsrs r0, r0, #24\n1:\nbx lr\n")
    assert not bp.build_plan(e).fused


def test_profile_guided_guards():
    e = elf("k20")
    prof = trace_kernel(e, 100)
    sound = bp.build_plan(e)
    plan = bp.build_plan(e, prof, "profile")
    assert plan.guards
    for v, cls in plan.guards.items():
        assert v.kind == "ins" and bp.WIDTH_ORDER[cls] < 4
    narrow = lambda p: sum(p.store(v)[0] < 4 for v in ra.counted(p.ssa))
    assert narrow(plan) >= narrow(sound)


def test_q16_detection_and_requant(tmp_path):
    src = os.path.join(ROOT, "tests", "physics", "jump_q16.c")
    e16, e8 = str(tmp_path / "q16.elf"), str(tmp_path / "q8.elf")
    subprocess.run(GCC + ["-o", e16, src], check=True)
    rep = bp.requantize_q88(e16, e8)
    assert len(rep["to_int_sites"]) == 2
    p8 = lift_file(e8)
    for a in rep["to_int_sites"]:
        x = p8.ins[int(a, 16)]
        assert x.op == "asr" and x.b == 8
    consts16 = {x.a for x in lift_file(e16).ins.values() if x.op == "mov" and isinstance(x.a, int)}
    assert 0xFFFFC000 in consts16                       # -GRAVITY in Q16.16
    assert 0xFFFFFFC0 in {x.a for x in p8.ins.values() if x.op == "mov" and isinstance(x.a, int)}
