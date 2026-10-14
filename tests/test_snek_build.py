"""Phase 5 B1: the original Snek GBA (third_party/snek-gba, GPL-3.0) builds with
arm-none-eabi-gcc as Thumb code and runs in mGBA (title -> game -> death)."""
import os
import subprocess
import pytest
from elftools.elf.elffile import ELFFile
from tools.slice import snek_ref

ROOT = snek_ref.ROOT


def test_build_thumb():
    elf = os.path.join(ROOT, "build", "snek", "snek.elf")
    snek_ref.build()
    with open(elf, "rb") as fh:
        e = ELFFile(fh)
        syms = {s.name: s["st_value"] for s in e.get_section_by_name(".symtab").iter_symbols()}
        text = e.get_section_by_name(".text")["sh_size"]
        data = e.get_section_by_name(".data")["sh_size"]
    for f in ("main", "reset", "display_score", "load_sprites", "load_background", "rand", "srand"):
        assert syms[f] & 1, f + " must be Thumb"
    assert text + data <= 0x2000          # ARM image window of the HAL (8 KiB)
    for h in ("__aeabi_dadd", "__aeabi_dmul", "__aeabi_d2f", "__aeabi_f2iz", "__aeabi_idivmod"):
        assert h in syms


@pytest.mark.skipif(not os.path.exists(snek_ref.MGBA), reason="mGBA capturer not built")
def test_mgba_reference(tmp_path):
    ims = snek_ref.capture(str(tmp_path))
    assert set(ims) == set(snek_ref.SHOTS)
    # gameplay frames differ from the title (snake + frog sprites), death differs again
    assert ims["title"].tobytes() != ims["game_a"].tobytes() != ims["dead"].tobytes()
