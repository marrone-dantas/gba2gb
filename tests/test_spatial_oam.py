"""Phase 2.3: spatial OAM shim tables and model."""
import os
import subprocess
from tools.hal.make_luts import gb_x, gb_y, vcount
from tools.hal.oam_model import compose, per_line

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_luts_up_to_date():
    gen = subprocess.run(["python3", os.path.join(ROOT, "tools", "hal", "make_luts.py")],
                         capture_output=True, text=True, check=True).stdout
    assert gen == open(os.path.join(ROOT, "runtime", "hal_luts.inc")).read()


def test_formula_and_wrap():
    assert gb_x(0) == 8 and gb_x(239) == 159 + 8 and gb_x(1) == 8 and gb_x(2) == 9
    assert gb_y(0) == 16 and gb_y(159) == 143 + 16 and gb_y(10) == 25
    assert gb_x(511) == -1 + 8 and gb_x(500) == (-12 * 2) // 3 + 8   # 9-bit X wrap, floor
    assert gb_y(255) == -1 + 16 and gb_y(200) == (-56 * 9) // 10 + 16
    assert vcount(0) == 0 and vcount(143) == 158 and vcount(144) == 160 and vcount(153) == 221


def obj(x, y, size, shape=0, flags=0, tile=0, hide=False):
    a0 = (y & 0xFF) | (shape << 14) | (0x200 if hide else 0)
    a1 = (x & 0x1FF) | (size << 14) | flags
    return [a0 & 0xFF, a0 >> 8, a1 & 0xFF, a1 >> 8, tile & 0xFF, tile >> 8, 0, 0]


def test_split_flip_and_limit():
    oam = bytes(obj(30, 20, 2, flags=0x1000, tile=0) + obj(0, 0, 0, hide=True) + [0] * 240)
    out, dropped, origin = compose(oam, 2, 0x40)
    assert len(out) == 16 and dropped == 0 and origin[0] == (gb_x(30), gb_y(20))
    assert out[0][:3] == (gb_y(20), gb_x(30), 3)           # hflip: first column shows tile 3
    many = bytes(sum((obj(10 + 8 * i, 10, 2) for i in range(4)), []) + [0] * 224)
    out, dropped, _ = compose(many, 4, 0x40)
    assert len(out) == 40 and dropped > 0 and per_line(out) > 10
