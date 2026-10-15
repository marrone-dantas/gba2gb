"""Generic audio removal (tools/audio/strip.py): detection rules on a synthetic ELF,
and an audio-off HAL build of sound_demo makes no APU writes."""
import os
import shutil
import subprocess
import pytest
from tools.audio.strip import detect, demangle_base

SRC = r"""
#define REG16(a) (*(volatile unsigned short *)(a))
volatile int game_state;
__attribute__((noinline)) void mmFrame(void) { REG16(0x04000084) = 0x80; }           /* library name */
void mixer_isr(void) { REG16(0x040000C6) = 0; REG16(0x04000082) = 0x0B0E; }  /* regs */
void play_jingle(int n) { if (!game_state) mmFrame(); }    /* wrapper */
void init_video(void) { REG16(0x04000008) = 0x0403; REG16(0x04000084) = 0; }  /* mixed: kept */
void update(void) { game_state++; mmFrame(); }             /* real work: kept */
int main(void) { init_video(); mixer_isr(); for (;;) { update(); play_jingle(1); } }
"""


@pytest.fixture(scope="module")
def elf(tmp_path_factory):
    if not shutil.which("arm-none-eabi-gcc"):
        pytest.skip("arm-none-eabi-gcc missing")
    d = tmp_path_factory.mktemp("strip")
    c, e = d / "t.c", d / "t.elf"
    c.write_text(SRC)
    subprocess.run(["arm-none-eabi-gcc", "-mthumb", "-O2", "-nostdlib", "-Wl,-e,main",
                    "-Wl,-Ttext=0x08000000", "-o", str(e), str(c)], check=True)
    return str(e)


def test_detect_rules(elf):
    got = detect(elf)
    assert got.get("mmFrame") == "name"
    assert got.get("mixer_isr") == "regs"
    assert got.get("play_jingle") == "wrapper"
    for kept in ("init_video", "update", "main"):
        assert kept not in got


def test_demangle():
    assert demangle_base("_Z3sfxh") == "sfx"
    assert demangle_base("_ZL4psfxh") == "psfx"
    assert demangle_base("mmStart") == "mmStart"


def test_audio_off_build_drops_apu_writes():
    from tools.hal.demos import build_demo
    rom, prog = build_demo("sound_demo", audio=False)
    asm = open(rom[:-4] + ".asm").read()
    assert "call HAL_SND_WR" not in asm and "HAL_WR_DMA1SAD" not in asm
    assert prog.hal_info["audio"].get("off")
