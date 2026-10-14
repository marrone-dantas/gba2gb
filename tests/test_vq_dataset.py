"""Phase 3.2: dataset builds, >= 10 scenes, loadable, multi-layer, collision flags present."""
import os
import numpy as np
from tools.vq.dataset import build
from tools.vq.snapshot import load
from tools.vq.vram_scene_dumper import dump


def test_dataset(tmp_path):
    names = build(str(tmp_path))
    assert len(names) >= 10
    multi = 0
    for n in names:
        d = dump(load(os.path.join(tmp_path, n + ".npz")))
        assert d["composite"].shape == (160, 240, 3)
        assert not d["unsupported"]
        multi += len(d["layers"]) > 1
        if n != "proc_glyphs":
            assert d["solid"].any(), n
    assert multi >= 5


def test_committed_dataset_up_to_date(tmp_path):
    root = os.path.join(os.path.dirname(__file__), "..", "data", "vq", "scenes")
    build(str(tmp_path))
    for f in os.listdir(tmp_path):
        a, b = load(os.path.join(tmp_path, f)), load(os.path.join(root, f))
        for k in ("vram", "pal", "io"):
            assert np.array_equal(a[k], b[k]), (f, k)
