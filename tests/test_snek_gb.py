"""Phase 5 B3: the transpiled Snek runs on the DMG (PyBoy, cgb=False): title ->
gameplay (bot steering to the frog) without crashes, MBC5 multi-bank kernel, and
the GB-computed g_state equals the original Thumb code's (Unicorn, replaying the
GB-read KEYINPUT / timer values) at every KEYINPUT read."""
import os
import pytest
from tools.slice import snek_bot as sb

pytest.importorskip("pyboy")


@pytest.fixture(scope="module")
def gb(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("snek") / "snek_dmg.gb")
    return sb.build_gb(out)


def test_rom_header_mbc5(gb):
    rom = open(gb, "rb").read()
    assert rom[0x147] in (0x19, 0x1A, 0x1B)       # MBC5 (+RAM, +battery)
    assert len(rom) == 0x8000 << rom[0x148]
    assert rom[0x143] in (0x00, 0x80)             # DMG-compatible


def test_bot_run_matches_reference(gb):
    r = sb.run_gb(3000, gb=gb, log=lambda *a: None)
    st = r["stats"]
    assert st["crashes"] == []
    assert 0xD800 <= st["sp_min"] <= 0xE000
    assert st["frames_by_room"].get("game", 0) > 1000
    assert st["max_score"] >= 1                   # the bot ate at least one frog
    rep = sb.Replay(sb.ELF, r["keys"], r["timers"])
    cmp = sb.compare(r["snaps"], rep.run())
    assert cmp["compared"] >= 100
    assert cmp["match"] == cmp["compared"], cmp["first_mismatch"]
