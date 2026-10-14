"""Phase 5 A2: EWRAM -> MBC5 SRAM paging (tools/sram/, docs/sram_paging.md).

ewram_demo uses about 30 KiB of EWRAM in five objects over four SRAM banks
(the allocator places them); the GB build (DMG PyBoy) must compute exactly the
same results as the GBA reference (Unicorn), both for the init work and for the
per-frame updates through run-time banked and dynamically dispatched pointers."""
import json
import os
import pytest
from tools.sram.ewram_alloc import allocate, AllocError, BANK, banks_of
from tools.hal.demos import build_demo, elf, ROOT
from tools.hal.gba_ref import GBARef
from tools.hal.gb_run import GBRun
from tools.lift.lift import lift_file
from tools.prune import range_analysis as ra
from tools.hal.lower import analyze

FRAMES = 60


def test_allocator_packing():
    objs = [("a", 6000, 1), ("b", 6000, 1), ("big", 12288, 2), ("h", 1024, 4), ("l", 128, 2), ("x", 3000, 4)]
    p = allocate(objs)
    for n, (off, size) in p.items():
        if size <= BANK:
            assert len(banks_of(off, size)) == 1, n          # small objects never straddle
        else:
            assert off % BANK == 0                           # big ones start a bank
    spans = sorted((o, o + s) for o, s in p.values())
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))  # no overlap
    assert len({o // BANK for o, _ in p.values()}) >= 4
    with pytest.raises(AllocError):
        allocate([("huge", 17 * BANK, 4)])
    with pytest.raises(AllocError):
        allocate([(f"o{i}", 5000, 4) for i in range(17)])


def test_ewram_layout_and_plan():
    build_demo("ewram_demo")
    rep = json.load(open(os.path.join(ROOT, "build", "demos", "ewram_demo_ewram.json")))
    assert sum(v["size"] for v in rep.values()) > 8192
    assert set(rep["buf_a"]["banks"]) != set(rep["buf_b"]["banks"])
    assert rep["big"]["banks"] == [0, 1]
    p = lift_file(elf("ewram_demo"), "main")
    s = ra.SSAProgram(p)
    ra.analyze(s)
    acc, info = analyze(s)
    ew = [d for d in acc.values() if d["region"] == "ewram"]
    assert {d["bank"] for d in ew if d["bank"] is not None} >= {1, 2, 3}
    assert any(d["bank"] is None for d in ew)                # run-time bank (big spans 2 banks)
    assert any(d["region"] == "dyn" for d in acc.values())   # pick[] pointers
    assert info["sram"]["hoisted_loops"] >= 1
    hoisted = [d for d in ew if d["bank"] is not None and not d["switch"]]
    assert hoisted                                           # switches removed by the pass


def run_gb(rom):
    g = GBRun(rom)
    res = 0xC000
    rec, start = {}, []

    def at_compose(_):
        m = g.m
        r = [int.from_bytes(bytes(m[res + 4 * i + j] for j in range(4)), "little") for i in range(8)]
        if not start:
            start.append((g.pb._cycles(), r[:4]))
        rec[r[5]] = r[4]
    b_, a_ = g.sym["Compose.fin"]
    g.pb.hook_register(b_, a_, at_compose, None)
    while len(rec) < FRAMES:
        g.tick()
    return g, start[0], rec


def test_ewram_demo_matches_gba():
    rom, prog = build_demo("ewram_demo")
    ref = GBARef(elf("ewram_demo"))
    snap = ref.snapshot
    ref.snapshot = lambda: {**snap(), "iw": bytes(ref.uc.mem_read(0x03000000, 0x24))}
    snaps = ref.run([0] * (FRAMES + 5), FRAMES + 5)
    gba = {}
    for sn in snaps:
        r = [int.from_bytes(sn["iw"][4 * i:4 * i + 4], "little") for i in range(9)]
        if r[8]:                         # done
            gba[r[5]] = (r[:4], r[4])
    g, (cyc, init), rec = run_gb(rom)
    g.screenshot(os.path.join(ROOT, "docs", "img", "ewram_demo.png"))
    g.stop()
    k0 = min(gba)
    assert init == gba[k0][0], (init, gba[k0][0])
    common = sorted(set(rec) & set(gba))
    assert len(common) >= FRAMES - 10
    for k in common:
        assert rec[k] == gba[k][1], (k, rec[k], gba[k][1])


def test_hoisting_saves_cycles(monkeypatch):
    rom, _ = build_demo("ewram_demo")
    _, (cyc_h, _), _ = run_gb(rom)
    monkeypatch.setenv("GBA2GB_NO_HOIST", "1")
    rom2, prog2 = build_demo("ewram_demo")
    _, (cyc_n, init_n), _ = run_gb(rom2)
    monkeypatch.delenv("GBA2GB_NO_HOIST")
    build_demo("ewram_demo")
    assert prog2.hal_info["sram"]["hoisted_loops"] == 0
    # 6000 iterations of the buf_a loop lose one `ld a, b / ld [$4000], a` (4 M) each
    assert cyc_n - cyc_h >= 4 * 4 * 6000 * 0.9, (cyc_h, cyc_n)
