"""Phase 5 A1: pointer provenance through stack slots + run-time address-space
dispatch (tools/hal/provenance.py, HAL_DYN_ADDR / HAL_DYN_STORE).

Regression for the Phase 4 miscompile: in spill_demo GCC keeps &sin_lut (ROM) in a
stack slot; the sine loads use a base register reloaded from that slot and have no
proven address range, so the old interceptor classified them as RAM and the GB
build read WRAM instead of the table."""
import os
import pytest
from elftools.elf.elffile import ELFFile
from tools.lift.lift import lift_file
from tools.prune import range_analysis as ra
from tools.hal.demos import build_demo, elf, make, ROOT
from tools.hal.intercept import interval, pointer_induction, InterceptError
from tools.hal.lower import analyze
from tools.hal.gb_run import GBRun

N = 80


def ssa_of(name):
    make()
    p = lift_file(elf(name), "main")
    s = ra.SSAProgram(p)
    ra.analyze(s)
    return p, s


def syms(name):
    with open(elf(name), "rb") as fh:
        e = ELFFile(fh)
        st = e.get_section_by_name(".symtab")
        out = {x.name: x["st_value"] for x in st.iter_symbols() if x.name}
        rom = e.get_section_by_name(".rodata") or e.get_section_by_name(".text")
        sl = out["sin_lut"]
        for sec in e.iter_sections():
            if sec["sh_addr"] <= sl < sec["sh_addr"] + sec["sh_size"]:
                d = sec.data()[sl - sec["sh_addr"]: sl - sec["sh_addr"] + 512]
        lut = [int.from_bytes(d[2 * i:2 * i + 2], "little", signed=True) for i in range(256)]
    return out, lut


def test_spilled_rom_pointer_classified_rom():
    p, s = ssa_of("spill_demo")
    acc, _ = analyze(s, strict=False)
    ind = pointer_induction(s)
    spilled = []
    for a, x in p.ins.items():
        if x.op == "ldrsh" and a in acc:
            base, idx, _ = x.mem
            env = s.envs[a]
            # a register without a proven range (stack reload / loaded pointer):
            # the pre-Phase-5 rule classified exactly these accesses as "ram"
            if interval(env.get(base), ind) is None or interval(env.get(idx), ind) is None:
                spilled.append((a, acc[a]["region"]))
    regions = sorted(r for _, r in spilled)
    assert regions.count("rom") == 2, spilled          # sin_lut[cos], sin_lut[sin]
    assert regions.count("dyn") == 1, spilled          # srcs[ang & 1][...]
    assert "ram" not in regions


def test_strict_mode_rejects_unknown():
    p, s = ssa_of("spill_demo")
    with pytest.raises(InterceptError, match="unknown address space"):
        analyze(s, strict=True)


def test_other_demos_have_no_dyn_regression():
    # demos whose pointers are all provable must not get slower dynamic accesses
    for name in ("obj_demo", "affine_demo", "sound_demo"):
        p, s = ssa_of(name)
        acc, _ = analyze(s, strict=False)
        assert not [a for a, d in acc.items() if d["region"] == "dyn"], name


def test_spill_demo_runs_correctly():
    rom, prog = build_demo("spill_demo")
    sy, lut = syms("spill_demo")
    res = 0xC000 | (sy["res"] & 0x0FFF)
    g = GBRun(rom)
    rec = []

    def at_compose(_):
        m = g.m
        rec.append([int.from_bytes(bytes(m[res + 4 * i + j] for j in range(4)), "little", signed=True)
                    for i in range(9)])
    b_, a_ = g.sym["Compose.fin"]
    g.pb.hook_register(b_, a_, at_compose, None)
    while len(rec) < N:
        g.tick()
    g.screenshot(os.path.join(ROOT, "docs", "img", "spill_demo.png"))
    g.stop()
    ram_buf = [3 * i - 7 for i in range(16)]
    # Compose runs at the vsync, before that iteration's body: record k holds the
    # results of iteration k (k = 0: nothing computed yet)
    assert rec[0] == [0] * 9
    angs = [r[5] for r in rec[1:]]
    assert angs == list(range(1, len(rec))), angs
    for k, r in enumerate(rec[1:]):
        ang = r[5]
        c, s_ = lut[(ang + 64) & 255], lut[ang]
        assert r[0] == c and r[1] == s_, (k, r, c, s_)
        assert r[2] == (c * 256) >> 8 and r[3] == (-s_ * 256) >> 8
        exp8 = (lut if ang & 1 == 0 else ram_buf)[ang & 15]
        assert r[8] == exp8, (k, r[8], exp8)
    assert any(v != 0 for v in lut[:16])
