"""Unit tests for tools/prune/range_analysis.py (Phase 1 A2)."""
import glob
import os
import subprocess
import pytest
import networkx as nx
from tools.prune import range_analysis as ra
from tools.profile.range_tracer import trace_kernel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KBUILD = os.path.join(ROOT, "build", "kernels")


@pytest.fixture(scope="module", autouse=True)
def kernels():
    subprocess.run(["make", "-s", "-C", os.path.join(ROOT, "tests", "kernels")], check=True)


def U(lo, hi):
    return ra.urange(lo, hi)


# ---------------------------------------------------------------- intervals
def test_const_and_norm():
    assert ra.const(-1) == (0xFFFFFFFF, 0xFFFFFFFF, -1, -1)
    assert ra.norm((0, 100, ra.SMIN, ra.SMAX)) == (0, 100, 0, 100)
    # signed-negative range implies the unsigned high range
    assert ra.srange(-4, -1)[:2] == (0xFFFFFFFC, 0xFFFFFFFF)


def test_and_mask():
    assert ra.width_class(ra.t_and(ra.TOP, ra.const(0xFF))) == "u8"
    assert ra.t_and(ra.TOP, ra.const(47))[:2] == (0, 47)


def test_shifts_and_extension_pairs():
    t = ra.t_lsl(ra.TOP, ra.const(24))
    assert t == ra.TOP
    assert ra.t_lsr(t, ra.const(24))[:2] == (0, 255)            # zero-extend byte
    assert ra.t_asr(t, ra.const(24))[2:] == (-128, 127)         # sign-extend byte
    assert ra.width_class(ra.t_asr(ra.t_lsl(ra.TOP, ra.const(16)), ra.const(16))) == "i16"
    assert ra.t_lsl(U(0, 15), ra.const(4))[:2] == (0, 240)
    assert ra.t_lsr(ra.TOP, U(0, 255))[:2] == (0, ra.M32)


def test_add_sub_mul_wrap_is_top():
    assert ra.t_add(U(0, 10), U(5, 5))[:2] == (5, 15)
    assert ra.t_add(U(0, ra.M32), ra.const(1))[:2] == (0, ra.M32)
    s = ra.t_sub(U(0, 10), ra.const(20))
    assert s[2:] == (-20, -10)
    assert ra.t_mul(U(0, 255), U(0, 255))[:2] == (0, 65025)


def test_orr_eor_bound():
    assert ra.t_orr(U(0, 5), U(0, 64))[:2] == (0, 127)
    assert ra.t_eor(U(0, 255), U(0, 3))[:2] == (0, 255)


def test_widen_and_join():
    j = ra.join(ra.const(0), ra.const(5))
    assert j[:2] == (0, 5)
    w = ra.widen(j, ra.join(j, ra.const(6)))
    assert w[0] == 0 and w[1] == 0x7F and w[3] == 0x7F  # upper bounds jump to the next threshold
    w = ra.widen(w, ra.join(w, ra.const(0x20000)))
    assert w[1] >= ra.SMAX and w[3] == ra.SMAX           # past 16 bits: the 32-bit limits


def test_spill_slot_and_swapped_cmp_bound():
    """A loop counter compared against a spilled, byte-bounded value stays narrow."""
    assert ra.mangled_arg_types("_Z12tile_flag_athhhhh") == ["h"] * 5
    assert ra.mangled_arg_types("_Z8is_solidP6Objectaa") == [None, "a", "a"]
    assert ra.mangled_arg_types("_Z9draw_hair5fix16S_a") == [None, None, "a"]


def test_constraints():
    assert ra.constraint("cc", ra.const(8))[:2] == (0, 7)
    assert ra.constraint("lt", ra.const(8))[2:] == (ra.SMIN, 7)
    assert ra.constraint("cc", ra.const(0)) is None   # x <u 0 never holds


# ---------------------------------------------------------------- SSA
def elf(name):
    return glob.glob(os.path.join(KBUILD, name + "*.elf"))[0]


def test_ssa_single_definition_and_phis():
    ssa = ra.SSAProgram(ra.lift_file(elf("k15")))
    ids = [v.id for v in ssa.values]
    assert len(ids) == len(set(ids))
    loop_phis = [v for v in ssa.values if v.kind == "phi"]
    assert {v.reg for v in loop_phis} >= {0, 1, 2, 3}
    for v in loop_phis:  # every phi has one argument per predecessor
        g = ssa.funcs[ssa.prog.entry].g
        assert set(v.args) == set(g.predecessors(v.block))
    # each use refers to a value whose definition dominates it (same function)
    f = ssa.funcs[ssa.prog.entry]
    dom = nx.immediate_dominators(f.g, f.entry)

    def dominates(a, b):
        while True:
            if a == b:
                return True
            if dom[b] == b:
                return False
            b = dom[b]
    for v in f.values:
        if v.kind == "ins":
            for d in v.env.values():
                assert dominates(d.block, v.block)


def test_induction_variable_counter():
    ssa = ra.analyze_file(elf("k15"))
    counter = [v for v in ssa.values if v.kind == "phi" and v.reg == 2][0]
    assert counter.proven[:2] == (1, 32)   # for (i = 32; i != 0; i--)


def test_sign_extension_kernel_proves_narrow():
    ssa = ra.analyze_file(elf("k18"))
    classes = [ra.width_class(v.proven) for v in ra.counted(ssa)]
    assert "i8" in classes and "i16" in classes


def test_fibonacci_mask():
    ssa = ra.analyze_file(elf("k01"))
    ands = [v for v in ssa.values if v.ins is not None and v.ins.op == "and"]
    assert ands and ands[0].proven[:2] == (0, 47)


# ---------------------------------------------------------------- soundness
@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(ROOT, "tests", "kernels", "k*.c"))),
                         ids=lambda p: os.path.basename(p)[:-2])
def test_static_contains_dynamic(path):
    """Static ranges are sound: every value observed on Unicorn (200 seeds) at an
    instruction definition lies inside its proven range."""
    e = os.path.join(KBUILD, os.path.basename(path)[:-2] + ".elf")
    ssa = ra.analyze(ra.SSAProgram(ra.lift_file(e)))
    ra.merge_profile(ssa, trace_kernel(e, 200))
    checked = 0
    for v in ssa.values:
        if v.kind == "ins" and v.observed is not None:
            assert v.proven is not None, f"{v} observed but proven unreachable"
            o, p = v.observed, v.proven
            assert p[0] <= o[0] and o[1] <= p[1] and p[2] <= o[2] and o[3] <= p[3], (v, v.ins.text, p, o)
            checked += 1
    assert checked > 0


def test_interprocedural_params():
    """B0: callee parameters get the join of the call-site arguments."""
    ssa = ra.analyze_file(elf("k17"))
    sq = ssa.funcs[min(ssa.funcs)]  # sq(x) is the first function in .text
    assert sq.params[0].proven[:2] == (0, 0xFFF)      # called with r0 & 0xFFF and r3 & 0xFF
