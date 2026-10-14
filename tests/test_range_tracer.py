"""Sanity checks for the dynamic range tracer."""
import os
import subprocess
from tools.profile.range_tracer import trace_kernel, Stat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_stat_stride_and_bounds():
    s = Stat()
    for v in (4, 12, 20, 0xFFFFFFFC):
        s.add(v)
    assert (s.umin, s.umax, s.smin, s.smax) == (4, 0xFFFFFFFC, -4, 20)
    assert s.stride == 8 and s.bor == 0xFFFFFFFC | 20 | 12


def test_fibonacci_counter_is_small():
    subprocess.run(["make", "-s", "-C", os.path.join(ROOT, "tests", "kernels")], check=True)
    p = trace_kernel(os.path.join(ROOT, "build", "kernels", "k01_fibonacci.elf"), 50)
    assert p["format"] == "gba2gb-range-profile/1" and p["seeds"] == 50
    # n = r0 & 47 is the first AND in the kernel
    ands = [v for k, v in p["regs"].items() if v["umax"] <= 47 and v["bitmask_or"] & ~47 == 0]
    assert ands
