"""Phase 3.5: reconstruction metrics on the dataset, visualizer, and a reconstructed
scene running as a real DMG ROM in PyBoy (cgb=False)."""
import os
import numpy as np
import pytest
from tools.vq.vq_tile_compiler import compile_scene
from tools.vq.metrics import scene_metrics, edges, edge_iou, ssim
from tools.vq.visualize import panel, side_by_side

SC = os.path.join(os.path.dirname(__file__), "..", "data", "vq", "scenes")
NAMES = sorted(f[:-4] for f in os.listdir(SC) if f.endswith(".npz"))


@pytest.fixture(scope="module")
def results():
    return {n: compile_scene(os.path.join(SC, n + ".npz")) for n in NAMES}


def test_metric_definitions():
    y = np.zeros((16, 16))
    y[:, 8:] = 0.5
    assert edges(y, 0.05)[:, 7:9].all() and not edges(y, 0.05)[:, :7].any()
    lv = (y > 0.25).astype(np.uint8)
    assert edge_iou(y, lv, np.ones_like(y, bool)) == 1.0
    assert edge_iou(y, np.zeros_like(lv), np.ones_like(y, bool)) == 0.0
    assert ssim(y, y) == pytest.approx(1.0)


def test_targets(results):
    m = {n: scene_metrics(r) for n, r in results.items()}
    assert len(m) >= 10
    assert np.mean([v["ssim_luma"] for v in m.values()]) >= 0.82
    solid = [n for n in m if m[n]["solid_cells"]]
    assert len(solid) >= 10
    for n in solid:
        assert m[n]["edge_iou_solid"] >= 0.95, (n, m[n])


def test_visualizer(results, tmp_path):
    p = str(tmp_path / "v.png")
    side_by_side(panel(results["platformer_b"]), ["a", "b", "c", "d"], p)
    from PIL import Image
    assert Image.open(p).size[0] > 4 * 240


@pytest.mark.parametrize("name", ["platformer_b", "proc_glyphs"])
def test_scene_rom_in_pyboy(name, results, tmp_path):
    """The reconstructed scene as a real .gb ROM: every screen pixel equals the
    reconstruction window at the current SCX/SCY; LUT remap <= 8 M-cycles per tile."""
    from tools.vq.scene_rom import build_rom, SceneRun
    res = results[name]
    rom, info = build_rom(res, str(tmp_path), name)
    g = SceneRun(rom)
    try:
        g.tick(300)
        remap, copy = g.loop_mcycles()
        cells = res["stats"]["map_w"] * res["stats"]["map_h"]
        assert (remap - copy) / cells <= 8.0
        assert info["class16"] == (name == "proc_glyphs")
        seen = set()
        for _ in range(8):
            g.tick(23)
            x, y = g.scroll()
            g.tick(1)
            assert np.array_equal(g.screen_levels(), res["recon"][y:y + 144, x:x + 160]), (x, y)
            seen.add(x)
        assert len(seen) >= 4                      # the window really scrolls
    finally:
        g.stop()
