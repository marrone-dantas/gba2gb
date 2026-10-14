"""eval_scenes on CC0 dataset scenes (the commercial evaluation runs outside the repo)."""
import os
import numpy as np
from tools.vq.eval_scenes import evaluate, markdown, heuristic_solid
from tools.vq.snapshot import load

SC = os.path.join(os.path.dirname(__file__), "..", "data", "vq", "scenes")


def test_eval_report(tmp_path):
    man = {"scenes": {"a": {"path": os.path.join(SC, "platformer_b.npz"), "solid_bg": [1],
                            "parallax": {"far": 2, "near": [1]}},
                      "b": {"path": os.path.join(SC, "1bit_urban.npz")}}}
    rep = evaluate(man, str(tmp_path), run_roms=False)
    md = markdown(rep, "t")
    assert "| a |" in md and "Parallax" in md and rep["scenes"]["a"]["solid_cells"] > 0
    assert rep["scenes"]["a"]["frame_agreement"] is None
    assert os.path.exists(tmp_path / "img" / "a_vq.png")


def test_heuristic_solid():
    s = heuristic_solid(load(os.path.join(SC, "platformer_b.npz")), [1])
    assert s["solid_bg1"].sum() > 0 and s["solid_bg1"][0] in (0, 1)
