"""Phase 5 A3: SM83 peephole pass (tools/backend/peephole.py). The lockstep
tests (test_lockstep_cpu.py) and every demo test run with the pass on (default);
these are rule-level checks plus one end-to-end comparison."""
import os
from tools.backend.peephole import optimize
from tools.harness import RefARM, GB
from tools.profile.seeds import seeds


def opt(lines):
    return [l.strip() for l in optimize("\n".join("    " + l if not l.endswith(":") else l for l in lines))[0].split("\n")]


def test_redundant_loads_and_stores():
    o = opt(["ld a, $00", "ldh [$FF88], a", "ld a, $00", "ldh [$FF89], a",
             "ldh a, [$FF89]", "ldh [$FF89], a", "add a, [hl]"])
    assert o == ["xor a", "ldh [$FF88], a", "ldh [$FF89], a", "add a, [hl]"]


def test_io_and_aliasing_kept():
    # I/O register reads are never removed; [hl] writes forget HRAM knowledge
    o = opt(["ldh a, [$FF44]", "ldh a, [$FF44]", "ldh [$FF90], a", "ld [hl], a", "ldh a, [$FF90]", "or a"])
    assert o.count("ldh a, [$FF44]") == 2 and "ldh a, [$FF90]" in o
    # a label resets the tracking
    o = opt(["ld a, $05", "L_1:", "ld a, $05", "ldh [$FF90], a"])
    assert o.count("ld a, $05") == 2


def test_flags_live_keeps_ld_a_0():
    o = opt(["ld a, $00", "adc a, [hl]"])
    assert o[0] == "ld a, $00"


def test_x2_rewrite():
    o = opt(["ldh a, [$FF8C]", "ldh [$FFC4], a", "ld hl, $FFC4", "sla [hl]", "ld hl, $FFC4", "sla [hl]",
             "ldh a, [$FFC4]", "ldh [$FF8C], a", "ld hl, $FF90", "add a, [hl]"])
    assert o[:5] == ["ldh a, [$FF8C]", "add a, a", "add a, a", "ldh [$FFC4], a", "ldh [$FF8C], a"]
    assert "sla [hl]" not in o


def test_fusion_and_jumps():
    assert opt(["ld [hl], a", "inc hl"]) == ["ld [hl+], a"]
    o = opt(["jp nz, L_2", "jp L_3", "L_2:", "nop", "L_3:", "jp L_4", "L_4:", "ret"])
    assert o[0] == "jp z, L_4" and "jp L_4" not in o


def test_end_to_end_kernel():
    import subprocess
    from tools.backend.gba2gbc_core import build
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.run(["make", "-s", "-C", os.path.join(root, "tests", "kernels")], check=True)
    elf = os.path.join(root, "build", "kernels", "k07_popcount.elf")
    out = os.path.join(root, "build", "roms")
    os.makedirs(out, exist_ok=True)
    cyc = {}
    for pp in (False, True):
        rom = os.path.join(out, f"k07_popcount.pp{int(pp)}.gbc")
        p = build(elf, rom, prune="sound", peephole=pp)
        ref, gb = RefARM(elf), GB(rom)
        tot = 0
        for s in seeds("k07_popcount", 50):
            got, c = gb.run(s)
            assert got == ref.run(s)
            tot += c
        gb.stop()
        cyc[pp] = tot
        if pp:
            assert p.peephole["values"] > 0
    assert cyc[True] < cyc[False]
