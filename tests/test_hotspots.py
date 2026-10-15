"""Hotspot report (tools/ports/hotspots.py): block labels fold into ELF functions,
helpers are charged to their calling function, lines come from addr2line."""
import collections
from tools.hal.demos import make, elf
from tools.ports.hotspots import analyse, markdown, elf_funcs


class FakeProf:
    def __init__(self, hist, blocks, helpers):
        self.hist, self.blocks, self.helpers = hist, blocks, helpers
        self.total = sum(hist.values())


def test_analyse_folds_blocks_and_helpers():
    make()
    e = elf("key_demo")
    fs = elf_funcs(e)
    main = [a for a, s, n in fs if n == "main"][0]
    blk = f"L_{main:08X}"
    hist = collections.Counter({blk: 6, "Div16Step": 3, "HAL_VBLANKINTRWAIT": 1})
    blocks = collections.Counter({blk: 9, "HAL_VBLANKINTRWAIT": 1})
    helpers = collections.Counter({(blk, "Div16Step"): 3})
    rep = analyse(FakeProf(hist, blocks, helpers), e, focus=["main"])
    assert dict(rep["self"])["thumb:main"] == 0.6
    assert dict(rep["with_helpers"])["thumb:main"] == 0.9
    assert rep["idle"] == 0.1
    f = rep["focus"]["main"]
    assert f["helpers"] == [("Div16Step", 0.3)] and f["lines"][0][0].endswith(":" + f["lines"][0][0].split(":")[1])
    assert "## `main`" in markdown(rep, "t")
