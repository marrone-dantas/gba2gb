"""Phase 2.2: GB HAL shims (runtime/gb_hal_shims.asm) on PyBoy in DMG mode."""
import json
import os
import pytest
from tools.hal.demos import build_demo, ROOT
from tools.hal.gb_run import GBRun

BUTTONS = ["a", "b", "select", "start", "right", "left", "up", "down"]  # GBA KEYINPUT bits 0-7


@pytest.fixture(scope="module")
def input_rom():
    return build_demo("input_test")[0]


def test_memory_map(input_rom):
    from tools.hal.gb_run import read_sym
    sym = read_sym(input_rom[:-4] + ".sym")
    assert sym["wShadowOAM"][1] == 0xD000      # outside the ARM window $C000-$CFFF
    assert sym["wGbaOAM"][1] == 0xD100
    assert all(0xD000 <= a < 0xD300 for n, (b, a) in sym.items() if n.startswith("w") and b == 1)


def test_keyinput_all_combinations(input_rom):
    """All 256 combinations of the 8 GB buttons: KEYINPUT seen by the ARM program
    (global keys_seen at 0x03000000 -> $C000) is the GBA active-low value with L/R
    released."""
    g = GBRun(input_rom, measure=[("HAL_KEYINPUT", "HAL_KEYINPUT_END")])
    try:
        while g.frame() < 2:
            g.tick()
        for mask in range(256):
            g.set_buttons({b for i, b in enumerate(BUTTONS) if mask >> i & 1})
            g.tick()
            g.tick()
            seen = g.m[0xC000] | (g.m[0xC001] << 8)
            assert seen == (~mask) & 0x3FF, (mask, hex(seen))
        cyc = sorted(set(g.cycles["HAL_KEYINPUT"]))
        assert len(cyc) == 1                        # straight-line code: constant cost
        # T-cycles from the first instruction to the final `ret` (exclusive); report
        # M-cycles including `ld c, n` + `call` + `ret` (2 + 6 + 4)
        mcycles = cyc[0] // 4 + 12
        os.makedirs(os.path.join(ROOT, "build", "reports"), exist_ok=True)
        json.dump({"HAL_KEYINPUT_mcycles": mcycles}, open(os.path.join(ROOT, "build", "reports", "keyinput.json"), "w"))
        assert mcycles < 80
    finally:
        g.stop()


def test_input_screenshot(input_rom):
    g = GBRun(input_rom)
    try:
        g.set_buttons({"a", "start", "left", "down"})
        for _ in range(10):
            g.tick()
        os.makedirs(os.path.join(ROOT, "docs", "img"), exist_ok=True)
        g.screenshot(os.path.join(ROOT, "docs", "img", "input_test_dmg.png"))
        assert g.violations == []
    finally:
        g.stop()


def test_vsync_full_speed():
    rom, _ = build_demo("brin_demo")
    g = GBRun(rom)
    try:
        for _ in range(150):
            g.tick()
        assert g.frame() > 0
        assert g.frame() == g.vblanks()   # one vsync per VBlank: no dropped frames
        assert g.violations == []
    finally:
        g.stop()
