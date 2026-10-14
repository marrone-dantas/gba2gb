"""Phase 2.5: OAM lockstep GBA reference (Unicorn, simulated KEYINPUT/VCOUNT/BIOS
VBlankIntrWait) vs transpiled program on PyBoy (DMG mode).

For each demo the same 300-frame input sequence is fed to both sides; at every
frame k (k-th completed vsync) every hardware sprite of the GB OAM must equal the
spatial OAM model applied to the GBA OAM of frame k (X_gb = floor(x*2/3)+8,
Y_gb = floor(y*9/10)+16, split into 8x8 sprites, 40-sprite priority filter), the
input the GB program read must be the frame's input, and no VRAM/OAM write may
happen outside VBlank/HBlank (strict checker on every write site of the HAL).
Screenshots (GBA | GB) are written to docs/img/."""
import json
import os
import pytest
from tools.hal.demos import build_demo, elf, ROOT
from tools.hal.gba_ref import GBARef, keymask, render
from tools.hal.gb_run import GBRun
from tools.hal.inputs import sequence
from tools.hal.oam_model import compose, gb_oam_entries, per_line, u16, tile_2bpp, levels_of
from tools.hal.screens import side_by_side

N = 300
DEMOS = {"obj_demo": [1, 60, 300], "key_demo": [60, 300], "brin_demo": [1, 300], "oam_stress": [300]}
REPORT = os.path.join(ROOT, "build", "reports")


@pytest.mark.parametrize("name", list(DEMOS))
def test_oam_lockstep(name):
    rom, prog = build_demo(name)
    nobj = prog.hal_info["nobj"]
    seq = sequence(N)
    inputs = [0] + [keymask(s) for s in seq]           # inputs[k] = keys during frame k
    snaps = GBARef(elf(name)).run(inputs, N + 1)
    g = GBRun(rom)
    img_dir = os.path.join(ROOT, "docs", "img")
    os.makedirs(img_dir, exist_ok=True)
    checked, max_line, dropped_frames, mism = 0, 0, 0, []
    try:
        seen = set()
        for _ in range(4 * N):
            k = g.frame()
            if k >= N:
                break
            g.set_buttons(seq[k])                      # read by frame k + 1
            g.tick(render=True)
            k = g.frame()
            if k < 1 or k in seen:
                continue
            seen.add(k)
            s = snaps[k - 1]
            exp, dropped, _ = compose(s["oam"], nobj, u16(s["io"], 0))
            got = gb_oam_entries(g.oam())
            if got != exp:
                mism.append((k, exp[:4], got[:4]))
            if k > 1 and name != "key_demo":              # key_demo polls every 8th frame
                assert g.keys() == (~inputs[k]) & 0x3FF or g.keys() == (~inputs[k - 1]) & 0x3FF
            max_line = max(max_line, per_line(got))
            dropped_frames += dropped > 0
            checked += 1
            if k in DEMOS[name]:
                side_by_side(render(s), g.pb.screen.image, os.path.join(img_dir, f"{name}_f{k:03d}.png"))
        assert not mism, mism[:3]
        missing = sorted(set(range(1, N)) - seen)
        assert not missing, missing[:10]
        assert g.violations == [], g.violations[:5]
        # VRAM: tiles uploaded by the program equal the 4bpp -> 2bpp model
        last = snaps[-1]
        vram = g.vram()
        objlv = levels_of(last["pal"], 0x200, True)
        for t in range(40):
            assert vram[16 * t:16 * t + 16] == tile_2bpp(last["vram"], 0x10000 + 32 * t, objlv), t
        if name == "brin_demo":
            bglv = levels_of(last["pal"], 0, False)
            for t in range(16):
                assert vram[0x1000 + 16 * t:0x1010 + 16 * t] == tile_2bpp(last["vram"], 32 * t, bglv)
            sbb = 30 * 0x800
            assert vram[0x1800:0x1C00] == bytes(last["vram"][sbb + 2 * i] for i in range(1024))
        os.makedirs(REPORT, exist_ok=True)
        json.dump({"frames": checked, "max_sprites_per_line": max_line, "frames_with_dropped": dropped_frames,
                   "vblanks": g.vblanks(), "vsyncs": g.frame(), "writes": g.writes},
                  open(os.path.join(REPORT, f"oam_lockstep_{name}.json"), "w"), indent=1)
        if max_line > 10:
            print(f"{name}: {max_line} sprites on one line (> 10: DMG shows only 10)")
    finally:
        g.stop()
