"""Phase 5 B2: GBA timer 0/1 shims (runtime/gb_timer_shims.asm) on PyBoy DMG.
tests/demos/timer_demo.c logs TM0D (prescaler 64, 262144 Hz) and TM1D (prescaler
1024, 16384 Hz) once per frame and stops timer 1 at frame 30."""
from tools.hal.demos import build_demo
from tools.hal.gb_run import GBRun

GB_FPS = 4194304 / 70224          # 59.73 Hz


def test_timer_rates_and_stop():
    rom = build_demo("timer_demo")[0]
    g = GBRun(rom)
    try:
        while g.frame() < 2:
            g.tick()
        for _ in range(50):
            g.tick()
        m = g.m
        n = m[0xC000] | m[0xC001] << 8
        assert 40 <= n <= 64
        t0 = [m[0xC084 + 2 * i] | m[0xC085 + 2 * i] << 8 for i in range(n)]
        t1 = [m[0xC004 + 2 * i] | m[0xC005 + 2 * i] << 8 for i in range(n)]
        d0 = [(b - a) & 0xFFFF for a, b in zip(t0[5:], t0[6:])]
        d1 = [(b - a) & 0xFFFF for a, b in zip(t1[5:28], t1[6:29])]
        exp0, exp1 = 262144 / GB_FPS, 16384 / GB_FPS
        assert all(abs(d - exp0) <= 64 for d in d0), d0           # resolution 16 ticks
        assert all(abs(d - exp1) <= 4 for d in d1), d1
        assert abs(sum(d0) / len(d0) - exp0) < 8
        assert len(set(t1[31:])) == 1                              # stopped: frozen
        assert all(t % 16 == 0 for t in t0)                       # 1/16384 s resolution
        assert g.violations == []
    finally:
        g.stop()
