import struct
from tools.lift.romscan import header, scan


def _rom():
    # ARM: b 0x080000c0 ; at c0: ldr r0,=0x080000d1 ; bx r0 ; pool ; Thumb at d0: swi 5 ; b .
    rom = bytearray(0x100)
    struct.pack_into("<I", rom, 0, 0xEA00002E)
    struct.pack_into("<III", rom, 0xC0, 0xE59F0000, 0xE12FFF10, 0)
    struct.pack_into("<I", rom, 0xC8, 0x080000D1)
    struct.pack_into("<HH", rom, 0xD0, 0xDF05, 0xE7FE)
    return bytes(rom)


def test_header_entry():
    assert header(_rom())["entry"] == 0x080000C0


def test_scan_follows_bx_to_thumb():
    r = scan(_rom())
    assert r["insns"] == {"arm": 2, "thumb": 2}
    assert r["swi"] == {"0x05": 1}
    assert r["indirect_branches"] == 0
