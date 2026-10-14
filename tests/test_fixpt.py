"""float -> 16.16 fixed-point source transform (tools/fixpt): text rewrite and a
compiled sample that must not reference any soft-float helper."""
import os
import subprocess
import tempfile
from tools.fixpt.float2fix import transform

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = r'''
#define max(X,Y) (((X) > (Y))? (X): (Y))
typedef struct { float x, y; } P;
const float TAB[3] = { 0.5f, -1.25f, 2. };
static P this_p;
int f(int k, P *this) {
    /* 1.5 in a comment stays */ const char *s = "2.5";
    this->x += 0.21f;
    this->y = max(0.05, this->x / 32) + k / 1.5f + TAB[k] * 3;
    return (int)(this->y * 360) + (this->x < k) + s[0];
}
'''


def test_transform_text():
    out = transform(SAMPLE)
    assert "FIX16_RAW(13763)" in out          # 0.21 * 65536, rounded
    assert "FIX16_RAW(-" not in out and "-FIX16_RAW(81920)" in out
    assert "float" not in out.split("\n", 1)[1].replace('"2.5"', "")
    assert "this_" in out and "self" not in out
    assert "/* 1.5 in a comment stays */" in out and '"2.5"' in out
    assert "FIX16_TERN(" in out


def test_compiles_without_softfloat():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "s.cpp")
        open(src, "w").write(transform(SAMPLE))
        o = os.path.join(td, "s.o")
        subprocess.run(["arm-none-eabi-g++", "-mcpu=arm7tdmi", "-mthumb", "-Os", "-std=gnu++17",
                        "-fno-exceptions", "-fno-rtti", "-ffreestanding", "-fpermissive", "-w",
                        "-I", os.path.join(ROOT, "tools", "fixpt"), "-c", "-o", o, src], check=True)
        syms = subprocess.run(["arm-none-eabi-nm", o], capture_output=True, text=True, check=True).stdout
        for bad in ("__aeabi_f", "__aeabi_d", "__aeabi_ldiv", "__aeabi_lmul"):
            assert bad not in syms, syms
