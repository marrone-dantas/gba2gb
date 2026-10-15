"""Boot/init RAM snapshot (SNAPSHOT define, runtime/gb_snapshot.asm).

A GBA program's init (crt0 copies, clears, tile uploads, table setup) runs once and
is often seconds long when lifted. `capture_and_patch(rom)` runs the built ROM in
PyBoy (DMG) up to the first call of HAL_VBLANKINTRWAIT - the program's first frame
wait, i.e. the end of its init - records the whole machine state and patches it into
the space the SNAPSHOT build reserved, so the ROM boots straight into that state.
Generic: nothing depends on the program; the only assumptions are that init ends
with a VBlankIntrWait and that the state at that point does not depend on input.
"""
from __future__ import annotations
import os
import subprocess

NPAGES = 32 + 32 + 16 * 32
IO_REGS = [0x26, 0x41, 0x42, 0x43, 0x45, 0x47, 0x48, 0x49, 0x4A, 0x4B, 0x06, 0x07, 0x05]


def _sym(rom):
    out = {}
    for ln in open(os.path.splitext(rom)[0] + ".sym"):
        ln = ln.split(";")[0].split()
        if len(ln) == 2 and ":" in ln[0]:
            b, a = ln[0].split(":")
            out[ln[1]] = (int(b, 16), int(a, 16))
    return out


def capture(rom, max_frames=3600):
    from pyboy import PyBoy
    sym = _sym(rom)
    pb = PyBoy(rom, window="null", cgb=False, sound_emulated=False)
    st = {}

    def hook(_):
        if st:
            return
        try:
            grab()
        except Exception as e:      # PyBoy swallows hook exceptions
            st["error"] = repr(e)

    def grab():
        m = pb.memory
        r = pb.register_file
        st["regs"] = (r.A, r.F, r.B, r.C, r.D, r.E, r.HL, r.SP)
        st["vram"] = bytes(m[0x8000:0xA000])
        st["wram"] = bytearray(m[0xC000:0xE000])
        st["oam"] = bytes(m[0xFE00:0xFEA0])
        st["hram"] = bytes(m[0xFF80:0xFFFF])
        st["io"] = {k: m[0xFF00 + k] for k in IO_REGS}
        st["lcdc"], st["ie"] = m[0xFF40], m[0xFFFF]
        st["sram"] = [bytes(m[b, 0xA000:0xBFFF]) + bytes((m[b, 0xBFFF],)) for b in range(16)]  # PyBoy: end bound inclusive check
        st["rombank"] = m[sym["wRomBank"][1]]
        # the selected SRAM bank is write-only: probe it with a temporary write
        v = m[0xA000]
        m[0xA000] = v ^ 0xFF
        st["rambank"] = [b for b in range(16) if m[b, 0xA000] != st["sram"][b][0]][0]
        m[0xA000] = v
        st["frame"] = pb.frame_count

    pb.hook_register(0, sym["HAL_VBLANKINTRWAIT"][1], hook, None)
    f = 0
    while not st and f < max_frames:
        pb.tick(1, False)
        f += 1
    pb.stop(save=False)
    if "error" in st:
        raise RuntimeError("snapshot: " + st["error"])
    if not st:
        raise RuntimeError("snapshot: no VBlankIntrWait within %d frames" % max_frames)
    return st


def restore_frames(st):
    """Estimated GB frames SnapRestore needs (copy ~5.2, clear ~2.2 M-cycles/byte)."""
    blobs = [st["vram"], bytes(st["wram"])] + st["sram"]
    pages = [b[i:i + 256] for b in blobs for i in range(0, len(b), 256)]
    full = sum(1 for p in pages if any(p))
    return (full * 256 * 5.2 + (len(pages) - full) * 256 * 2.2) / 17556


def patch(rom, st):
    sym = _sym(rom)
    data = bytearray(open(rom, "rb").read())
    A, F, B, C, D, E, HL, SP = st["regs"]
    if not 0xC008 <= SP <= 0xE000:
        raise RuntimeError(f"snapshot: SP {SP:#06x} not in WRAM")
    w = st["wram"]
    w[SP - 8 - 0xC000:SP - 0xC000] = bytes((F, A, C, B, E, D, HL & 0xFF, HL >> 8))
    pages = []
    for blob in [st["vram"], bytes(w)] + st["sram"]:
        pages += [blob[i:i + 256] for i in range(0, len(blob), 256)]
    assert len(pages) == NPAGES
    flags = bytes(1 if any(p) else 0 for p in pages)
    stream = b"".join(p for p in pages if any(p))

    def at(name, k=0):
        b, a = sym[name]
        return (b * 0x4000 + a - 0x4000 if b else a) + k

    def put(name, blob):
        o = at(name)
        data[o:o + len(blob)] = blob

    io = b"".join(bytes((k, v)) for k, v in st["io"].items()) + b"\0"
    put("SnapSP", bytes((SP & 0xFF, SP >> 8, st["rombank"], st["rambank"], st["lcdc"], st["ie"])))
    put("SnapIo", io)
    put("SnapOam", st["oam"])
    put("SnapHram", st["hram"])
    put("SnapFlags", flags)
    for k in range(0, len(stream), 0x4000):
        put(f"SnapData{k // 0x4000}", stream[k:k + 0x4000])
    put("SnapMagic", b"\xA5")
    open(rom, "wb").write(data)
    subprocess.run(["rgbfix", "-v", rom], check=True, capture_output=True)
    return {"init_frames": st["frame"], "pages": sum(flags), "bytes": len(stream)}


def capture_and_patch(rom, force=False):
    """Patch the snapshot in when the captured init is longer than its restore (plus
    a margin); otherwise the ROM keeps its normal boot."""
    st = capture(rom)
    est = restore_frames(st)
    if not force and st["frame"] < est + 30:
        return {"skipped": f"init {st['frame']} frames <= restore ~{est:.0f} + 30", "init_frames": st["frame"]}
    rep = patch(rom, st)
    rep["restore_frames_est"] = round(est)
    return rep
