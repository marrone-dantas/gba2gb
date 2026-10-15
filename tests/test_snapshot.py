"""Boot snapshot (tools/hal/snapshot.py) and late VSync (docs/hal.md, "Idle time"):
a demo booted from its snapshot shows the same screen as the normal boot at the same
VSync count, (the build only keeps a snapshot when init outlasts the restore)."""
import os
import numpy as np
from pyboy import PyBoy
from tools.backend.gba2gbc_core import build
from tools.hal.demos import make, elf, ROOT
from tools.hal.gb_run import read_sym


def run_to(rom, vs):
    sym = read_sym(rom[:-4] + ".sym")
    a = sym["wVsync"][1]
    pb = PyBoy(rom, window="null", cgb=False, sound_emulated=False)
    f = 0
    while (pb.memory[a] | pb.memory[a + 1] << 8) < vs and f < 3000:
        pb.tick(1, True)
        f += 1
    img = np.array(pb.screen.ndarray)[:, :, :3].copy()
    pb.stop(save=False)
    return f, img


def test_snapshot_boot(tmp_path):
    make()
    roms = {}
    for snap in (False, True):
        out = str(tmp_path / f"d{int(snap)}.gbc")
        prog = build(elf("key_demo"), out, entry="main", prune="sound", hal=True, snapshot="force" if snap else False)
        roms[snap] = out
    assert prog.snapshot["pages"] > 0
    f0, i0 = run_to(roms[False], 40)
    f1, i1 = run_to(roms[True], 40)
    assert f1 > 0  # (short init: the forced snapshot may boot slower)
    assert (i0 == i1).all()
