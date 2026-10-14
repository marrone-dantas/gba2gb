"""Phase 3.3: VQ tile compiler."""
import os
import numpy as np
import pytest
from tools.vq.vq_tile_compiler import (compile_scene, export, encode_2bpp, quantize, level_centres,
                                       edge_aware_cuts, quantize_thresholds)

SC = os.path.join(os.path.dirname(__file__), "..", "data", "vq", "scenes")


def scene(n):
    return os.path.join(SC, n + ".npz")


def test_2bpp_format():
    t = np.zeros((1, 64), np.uint8)
    t[0, :8] = [0, 1, 2, 3, 3, 2, 1, 0]
    b = encode_2bpp(t)
    assert len(b) == 16 and b[0] == 0b01011010 and b[1] == 0b00111100


@pytest.mark.parametrize("fov,shape", [("scroll", (20, 30)), ("downscale", (18, 20)), ("crop", (18, 20))])
def test_fov_and_limits(fov, shape, tmp_path):
    r = compile_scene(scene("tiny-ski_1"), fov=fov)
    st = r["stats"]
    assert (st["map_h"], st["map_w"]) == shape
    assert st["codewords"] <= 256 and r["tilemap"].max() < 256
    assert len(r["tiles_2bpp"]) == 16 * st["codewords"]
    assert np.array_equal(r["lut"][r["classes"]], r["tilemap"])     # LUT_Tile_Remap consistent
    export(r, str(tmp_path))
    assert sorted(os.listdir(tmp_path)) == ["classes.bin", "compile.json", "lut_tile_remap.bin",
                                            "tilemap.bin", "tiles.2bpp"]


def test_exact_when_codebook_fits():
    r = compile_scene(scene("platformer_a"))
    assert r["stats"]["exact"] and np.array_equal(r["recon"], r["levels"])


def test_vq_when_over_budget_with_reserve():
    r = compile_scene(scene("proc_glyphs"), reserve=64)
    st = r["stats"]
    assert st["unique_tiles"] > 192 and not st["exact"]
    assert st["codewords"] <= 192 and r["tilemap"].min() >= 64
    r2 = compile_scene(scene("proc_glyphs"), reserve=64)
    assert np.array_equal(r["tilemap"], r2["tilemap"])                # deterministic (seeded)
    # refinement keeps codewords on the 4 integer levels
    assert set(np.unique(r["codebook"])) <= {0, 1, 2, 3}


def test_solid_tiles_pinned_under_pressure():
    su = compile_scene(scene("tiny-dungeon_1"))["stats"]["solid_unique"]
    k = int(np.ceil(su / 0.75)) + 1
    r = compile_scene(scene("tiny-dungeon_1"), k=k)
    assert not r["stats"]["exact"] and r["stats"]["codewords"] <= k
    assert r["stats"]["solid_cells_exact"] == 1.0


def test_dither_and_levels():
    y = np.tile(np.linspace(0, 1, 240), (160, 1))
    c = level_centres(y, "uniform")
    q0, q1 = quantize(y, c, False), quantize(y, c, True)
    assert set(np.unique(q0)) == {0, 1, 2, 3}
    # Bayer 2x2: a mid-tone between two levels produces both levels in each 2x2 block
    mid = np.full((8, 8), (c[1] + c[2]) / 2)
    d = quantize(mid, c, True)
    assert set(np.unique(d)) == {1, 2}
    th, cen = edge_aware_cuts(y, np.zeros_like(y, bool))
    assert np.all(np.diff(th) < 0) and np.all(np.diff(cen) < 0)
    assert quantize_thresholds(np.array([[1.0, 0.0]]), th).tolist() == [[0, 3]]
