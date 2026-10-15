"""Map-pure function detection and memo stub generation (tools/lift/memo.py)."""
import shutil
import subprocess

import pytest

from tools.lift import memo

SRC = r'''
const unsigned char flags[64] = {1, 2, 3};
unsigned char state;
const unsigned char map[256] = {4, 5};
__attribute__((noinline)) int flag_at(unsigned char x, unsigned char y) { return flags[map[y * 16 + x] & 63]; }
__attribute__((noinline)) int ram_at(unsigned char x) { return state + x; }
__attribute__((noinline)) void poke(unsigned char x) { state = x; }
__attribute__((noinline)) void empty(unsigned char x) { (void)x; }
int main(void) { poke(1); empty(2); return flag_at(1, 2) + ram_at(3); }
'''


@pytest.fixture
def elf(tmp_path):
    if not shutil.which("arm-none-eabi-g++"):
        pytest.skip("arm-none-eabi-g++ missing")
    c, out = tmp_path / "m.cpp", tmp_path / "m.elf"
    c.write_text(SRC)
    subprocess.run(["arm-none-eabi-g++", "-mthumb", "-O2", "-nostdlib", "-fno-exceptions", "-Wl,-e,main",
                    "-Wl,-Ttext=0x08000000", "-Wl,-Tdata=0x03000000", str(c), "-o", str(out), "-lgcc"], check=True)
    return str(out)


def test_find_only_map_pure(elf):
    found = memo.find(elf)
    assert any("flag_at" in n for n in found)
    assert not any(k in n for n in found for k in ("ram_at", "poke", "empty", "main"))


def test_asm_emits_stub():
    a = memo.asm({1: ("L_08000100", [1, 1])})
    assert "NAT_memo_1::" in a and "MemoLookup" in a and "wMemoOk" in a
    assert memo.asm({}) == ""
