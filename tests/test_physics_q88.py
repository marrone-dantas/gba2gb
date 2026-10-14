"""Phase 1 B3: physics precision test.

A jump parabola with gravity, ground bounce and friction (tests/physics/jump_q16.c)
is simulated for 600 frames:
  * reference: original Q16.16 kernel on Unicorn;
  * candidate: the same kernel requantized to Q8.8 by bitwidth_pruning (opt-in),
    profile-guided pruned (i16 storage, runtime guards) and run on headless PyBoy.
For every frame n = 1..600 both screen coordinates (y height and x) are compared in
whole pixels. Acceptance: max error <= 1 px, and no range guard fires.
"""
import os
import subprocess
from tools.backend.gba2gbc_core import build
from tools.harness import RefARM, GB
from tools.profile.range_tracer import Tracer
from tools.prune.bitwidth_pruning import requantize_q88

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "build", "physics")
FRAMES = 600
GCC = ["arm-none-eabi-gcc", "-mcpu=arm7tdmi", "-mthumb", "-O2", "-ffreestanding", "-nostdlib",
       "-fno-builtin", "-fno-jump-tables", "-Wl,-Ttext=0x08000000", "-Wl,-e,f"]


def s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def test_jump_q88_within_one_pixel():
    os.makedirs(OUT, exist_ok=True)
    e16, e8 = os.path.join(OUT, "jump_q16.elf"), os.path.join(OUT, "jump_q88.elf")
    subprocess.run(GCC + ["-o", e16, os.path.join(ROOT, "tests", "physics", "jump_q16.c")], check=True)
    rep = requantize_q88(e16, e8)
    inputs = [(n, axis, 0, 0) for n in range(1, FRAMES + 1) for axis in (0, 1)]

    ref = RefARM(e16)
    expected = [s32(ref.run(i)) for i in inputs]

    tr = Tracer(e8)               # profile of the Q8.8 program on the same inputs
    for i in inputs:
        tr.run(i)
    prof = tr.profile("jump_q88", len(inputs))
    rom = os.path.join(OUT, "jump_q88.profile.gbc")
    prog = build(e8, rom, asm_out=rom[:-4] + ".asm", prune="profile", profile=prof)
    narrow = prog.plan.summary()
    gb = GB(rom)
    errs, cyc = [], 0
    try:
        for i, e in zip(inputs, expected):
            got, c = gb.run(i)     # raises GuardFired if a guard trips
            errs.append(abs(s32(got) - e))
            cyc += c
    finally:
        gb.stop()
    worst = max(errs)
    # cost comparison on a sample of frames: Phase 0 Q16.16 vs pruned Q8.8
    sample = [(n, a, 0, 0) for n in range(50, FRAMES + 1, 50) for a in (0, 1)]
    rom0 = os.path.join(OUT, "jump_q16.phase0.gbc")
    build(e16, rom0, asm_out=rom0[:-4] + ".asm")
    cost = {}
    for tag, r in (("q16_phase0", rom0), ("q88_profile", rom)):
        g = GB(r)
        try:
            cost[tag] = sum(g.run(i)[1] for i in sample) / len(sample)
        finally:
            g.stop()
    with open(os.path.join(OUT, "physics_result.txt"), "w") as fh:
        fh.write(f"frames={FRAMES} max_error_px={worst} mismatching_samples={sum(e > 0 for e in errs)}/"
                 f"{len(errs)} mean_mcycles_per_call={cyc / len(inputs):.0f} guards={narrow['guards']} "
                 f"values_1B={narrow['bytes1']} values_2B={narrow['bytes2']} values_4B={narrow['bytes4']} "
                 f"patches={len(rep['patches'])} sample_mcycles_q16_phase0={cost['q16_phase0']:.0f} "
                 f"sample_mcycles_q88_profile={cost['q88_profile']:.0f}\n")
    assert worst <= 1, f"max screen error {worst} px"
