"""Phase 4.2: HBlank raster tables (runtime/hblank_mode7.asm, docs/mode7.md).

* mode7_track (stack-blasting ISR and pinned-HL ISR): every PyBoy DMG screen pixel
  equals the exact model of the per-line (SCY, SCX) table, at several yaws; ISR
  M-cycles per line and the entry phase within the line are measured with PyBoy
  hooks; SSIM against the true per-pixel ground projection is reported.
* scanline_parallax: per-line SCX parallax on a CC0 scene, pixel-exact."""
import json
import os
import numpy as np
import pytest
from PIL import Image
from pyboy import PyBoy
from tools.hal.gb_run import read_sym
from tools.mode7 import mode7_tables as M
from tools.mode7 import scanline_parallax as P
from tools.vq.metrics import ssim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "docs", "img")
REP = os.path.join(ROOT, "build", "reports")
SHADE = np.array([255, 170, 85, 0], np.uint8)


def levels(pb):
    scr = np.asarray(pb.screen.image.convert("L"))
    return np.select([scr > 200, scr > 120, scr > 40], [0, 1, 2], 3).astype(np.uint8)


def pair(a, b, path, gap=6):
    im = np.hstack([a, np.full((a.shape[0], gap), 1, np.uint8), b])
    Image.fromarray(SHADE[im]).resize((im.shape[1] * 2, im.shape[0] * 2), Image.NEAREST).save(path)


def run(rom):
    pb = PyBoy(rom, window="null", cgb=False, sound_emulated=False)
    pb.set_emulation_speed(0)
    return pb, read_sym(rom[:-3] + ".sym")


@pytest.mark.parametrize("pinned", [False, True])
def test_track(pinned, tmp_path):
    rom, info, tex, tabs = M.build_rom(str(tmp_path), pinned=pinned)
    assert info["tables"] == M.NANG * M.NPH and info["tiles"] <= 256
    pb, sym = run(rom)
    m = pb.memory
    try:
        pb.tick(120, False)
        ev = []
        pb.hook_register(0, 0x48, lambda c: ev.append(("in", pb._cycles())), None)
        b, a = sym["M7HblRet"]
        pb.hook_register(b, a, lambda c: ev.append(("ret", pb._cycles())), None)
        pb.hook_register(0, 0x40, lambda c: ev.append(("vbl", pb._cycles())), None)
        pb.tick(3, False)
        body = {(ev[i + 1][1] - ev[i][1]) // 4 for i in range(len(ev) - 1) if ev[i][0] == "in" and ev[i + 1][0] == "ret"}
        v = [e[1] for e in ev if e[0] == "vbl"]
        per_frame = len([e for e in ev if e[0] == "in" and v[0] < e[1] < v[1]])
        phase = sorted({(e[1] - v[0]) % 456 for e in ev if e[0] == "in" and e[1] > v[0]})
        assert len(body) == 1 and per_frame == 144
        total = body.pop() + 4 + 5                          # + reti + interrupt dispatch
        assert total == (19 if pinned else 54)
        ss = []
        for a in (16, 0, 8, 24, 31):
            m[sym["wHold"][1]] = 1
            m[sym["wAngle"][1]] = a
            pb.tick(4, True)
            ph = m[sym["wPhase"][1]]
            got, exp = levels(pb), M.gb_view(tex, M.table(a, ph))
            assert np.array_equal(got, exp), (a, int((got != exp).sum()))
            tv = M.true_view(tex, a, ph)
            ss.append(ssim(1 - tv / 3.0, 1 - got / 3.0))
            if not pinned:
                pair(tv, got, os.path.join(IMG, f"mode7_track_yaw{a:02d}.png"))
        # free-running: the phase advances and steering works through the joypad
        m[sym["wHold"][1]] = 0
        pb.button_press("left")
        pb.tick(40, True)
        pb.button_release("left")
        assert m[sym["wAngle"][1]] < 31
        os.makedirs(REP, exist_ok=True)
        rep = {"isr_mcycles_per_line": total, "isr_body_mcycles_incl_vector_jp": total - 9,
               "lines_per_frame": per_frame, "frame_share": round(total * 144 / 17556, 3),
               "entry_phase_dots_after_vblank_entry": [phase[0], phase[-1]],
               "ssim_true_vs_gb": [round(float(x), 3) for x in ss], **info}
        json.dump(rep, open(os.path.join(REP, f"mode7_{'pinned' if pinned else 'stack'}.json"), "w"), indent=1)
        print(rep)
    finally:
        pb.stop()


def test_scanline_parallax(tmp_path):
    rom, res, max_cam = P.build_rom(os.path.join(ROOT, "data", "vq", "scenes", "platformer_b.npz"), str(tmp_path))
    pb, sym = run(rom)
    m = pb.memory
    try:
        pb.tick(100, False)
        for cam in (0, 40, max_cam, 23):
            m[sym["wHold"][1]] = 1
            m[sym["wCam"][1]] = cam
            pb.tick(4, True)
            got = levels(pb)
            exp = P.expected(res["recon"], cam)
            assert np.array_equal(got, exp), cam
            if cam in (0, 40, max_cam):
                pair(res["recon"][P.SCY0:P.SCY0 + 144, cam:cam + 160], got,
                     os.path.join(IMG, f"scanline_parallax_cam{cam:02d}.png"))
        # bands really move at different speeds
        e40 = P.expected(res["recon"], 40)
        assert P.scx_of_line(0, 40) == 10 and P.scx_of_line(P.BAND1, 40) == 20 and P.scx_of_line(143, 40) == 40
        assert not np.array_equal(e40[:P.BAND1], res["recon"][P.SCY0:P.SCY0 + P.BAND1, 40:200])
        m[sym["wHold"][1]] = 0
        c0 = m[sym["wCam"][1]]
        pb.tick(10, True)
        assert m[sym["wCam"][1]] != c0
    finally:
        pb.stop()
