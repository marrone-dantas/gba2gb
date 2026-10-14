"""Phase 3.4: parallax baker."""
import json
import os
import numpy as np
import pytest
from tools.vq.parallax_baker import bake, export, phase_of
from tools.vq.vq_tile_compiler import quantize_thresholds

SC = os.path.join(os.path.dirname(__file__), "..", "data", "vq", "scenes")


def render(res, p, kk):
    m = res["maps"][p, kk]
    cb = res["codebook"].reshape(-1, 8, 8)
    return cb[m].transpose(0, 2, 1, 3).reshape(m.shape[0] * 8, m.shape[1] * 8)


@pytest.mark.parametrize("name", ["proc_hills", "platformer_b"])
def test_phases_reconstruct_composite(name, tmp_path):
    res = bake(os.path.join(SC, name + ".npz"))
    pr = res["pressure"]
    assert len(pr["unique_tiles_per_phase"]) == 8 and pr["codewords"] <= 256
    for x in (0, 3, 17, 100, 255, 301):
        p, kk = phase_of(x)
        d = x - x // 2
        assert (p, kk) == (d % 8, (d // 8) % 32)
        exp = quantize_thresholds(res["composite"](d), res["thresholds"])
        got = render(res, p, kk)
        if pr["exact"]:
            assert np.array_equal(got, exp)
        else:
            assert (got == exp).mean() > 0.9
    info = export(res, str(tmp_path))
    banks = [f for f in os.listdir(tmp_path) if f.startswith("bank_")]
    assert len(banks) == info["rom_banks"] and all(os.path.getsize(tmp_path / f) <= 0x4000 for f in banks)
    layout = json.load(open(tmp_path / "layout.json"))
    assert len(layout) == 8 * res["ncoarse"]
    b, addr = layout["3,5"]
    blob = open(tmp_path / f"bank_{b:03d}.bin", "rb").read()
    off = addr - 0x4000
    assert blob[off:off + info["map_bytes"]] == res["maps"][3, 5].tobytes()
