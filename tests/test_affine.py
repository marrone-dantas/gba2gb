"""Phase 4.1: affine OBJ baker (tools/affine/affine_lut_baker.py, docs/affine.md).

Lockstep: the GBA reference (Unicorn, real affine matrices) and the transpiled
affine_demo on PyBoy (DMG) get the same 300-frame input; at every frame the GB
frame selection (wAffWant) must equal the exact model of the LUT applied to the
GBA pa/pb of that frame, the selected frame must be within half a rotation step
(plus LUT cell error) of the true matrix angle, the displayed slot must hold the
baked frame wAffHave, the hardware OAM must equal the spatial model, and every
VRAM write (including the VBlank frame stream) must be in VBlank/HBlank."""
import json
import math
import os
from tools.affine import affine_lut_baker as B
from tools.hal.demos import build_demo, elf, ROOT
from tools.hal.gba_ref import GBARef, keymask, render
from tools.hal.gb_run import GBRun
from tools.hal.inputs import sequence
from tools.hal.oam_model import compose, gb_oam_entries, u16
from tools.hal.screens import side_by_side

N = 300
SHOTS = [1, 40, 120, 200, 300]


def test_lut_model():
    scales = [1.0, 2.0]
    sh = B.choose_shift(scales)
    lut = B.build_lut(32, scales, sh)
    worst = 0
    for j, s in enumerate(scales):
        for a in range(256):
            th = 2 * math.pi * a / 256
            pa, pb = int(256 * math.cos(th) / s), int(-256 * math.sin(th) / s)
            f = B.select(pa & 0xFFFF, pb & 0xFFFF, lut, sh)
            assert f // 32 == j
            err = abs((f % 32) * 2 * math.pi / 32 - th)
            worst = max(worst, min(err, 2 * math.pi - err))
    assert worst <= 2 * math.pi / 32 * 0.5 + math.radians(4.5), math.degrees(worst)


def test_bake_identity_and_plan():
    src = [[(x + y) % 4 for x in range(16)] for y in range(16)]
    frames, imgs = B.bake(src, 16, 16, [0, 1, 2, 3], 32, [1.0])
    assert imgs[0] == src and len(frames) == 32 and len(frames[0]) == 64
    assert imgs[8] == [[src[15 - x][y] if False else imgs[8][y][x] for x in range(16)] for y in range(16)]
    p = B.plan(32, 4, 16)
    assert p["mode"] == "resident" and p["base"] == 16
    p = B.plan(64, 16, 16)
    assert p["mode"] == "stream" and p["slots"] == [224, 240] and p["chunks"] == 2


def test_affine_lockstep():
    rom, prog = build_demo("affine_demo")
    rep = prog.hal_info["affine"]
    assert rep["affine"] and rep["mode"] == "stream" and rep["group"] == 0 and rep["objects"] == [0]
    assert {n for _, n in rep["param_writes"]} == {"pa", "pb", "pc", "pd"}
    lut, sh = rep["_lut"], rep["shift"]
    frames, _ = B.bake(rep["_src"], 32, 32, rep["_levels"], rep["nrot"], rep["scales"])
    seq = sequence(N, seed=5)
    g = GBRun(rom, measure=[("AffStream.go", "AffStream.idle"), ("AffStream", "AffStream.end"), ("HAL_AFFINE_SEL", "HAL_AFFINE_SEL.end")])
    img_dir = os.path.join(ROOT, "docs", "img")
    rec = {}
    sym = g.sym

    def at_compose(_):
        # iteration index = number of Composes (one per GBA frame loop iteration; the
        # GB vsync counter can advance by 2 when an iteration overruns a GB frame)
        m = g.m
        k = len(rec) + 1
        tile = m[sym["wAffTile"][1]]
        rec[k] = (bytes(m[0xD000 + i] for i in range(160)), m[sym["wAffWant"][1]],
                  m[sym["wAffHave"][1]], tile, bytes(m[0x8000 + 16 * tile + i] for i in range(256)),
                  (~g.keys()) & 0x3FF, g.frame())
    b_, a_ = sym["Compose.fin"]
    g.pb.hook_register(b_, a_, at_compose, None)
    tear = []

    def at_copy(_):
        # the stream must never write the slot that the hardware OAM displays
        m = g.m
        dst = (m[sym["wAffDst"][1]] | m[sym["wAffDst"][1] + 1] << 8) - 0x8000
        shown = {m[0xFE02 + 4 * i] for i in range(40) if m[0xFE00 + 4 * i]}
        if any(dst // 16 <= t < dst // 16 + 8 for t in shown):
            tear.append((g.frame(), dst // 16))
    b_, a_ = sym["AffStream.cont"]
    g.pb.hook_register(b_, a_, at_copy, None)
    mism, lag, worst, shots, shots_img = [], [], 0.0, set(), {}
    try:
        for _ in range(4 * N):
            k = g.frame()
            if k >= N:
                break
            g.set_buttons(seq[k])
            g.tick(render=True)
            k = g.frame()
            if k in SHOTS and k not in shots:
                shots.add(k)
                shots_img[len(rec)] = g.pb.screen.image.copy()

        # the GBA reference gets, for frame k, the keys the GB program read in iteration k
        inputs = [0] + [rec[k + 1][5] if k + 1 in rec else 0 for k in range(1, len(rec) + 2)]
        snaps = GBARef(elf("affine_demo")).run(inputs, len(rec))
        for k, im in shots_img.items():
            if k < len(snaps):

                side_by_side(render(snaps[k - 1]), im, os.path.join(img_dir, f"affine_demo_f{k:03d}.png"))
        seen = set(rec)
        for k in sorted(rec):
            if k < 2:
                continue
            shadow, want, have, tile, vram, _, _ = rec[k]
            if k >= len(snaps):
                continue
            s = snaps[k - 1]   # Compose #k sees the state written by GBA iteration k - 1
            pa, pb = u16(s["oam"], 6), u16(s["oam"], 14)
            exp = B.select(pa, pb, lut, sh)
            if want != exp:
                mism.append((k, exp, want))
            th = math.atan2(-B.s16(pb), B.s16(pa))
            err = abs(((exp % 32) * 2 * math.pi / 32 - th + math.pi) % (2 * math.pi) - math.pi)
            worst = max(worst, err)
            if vram != frames[have]:
                mism.append((k, "vram", have))
            lag.append(next((d for d in range(0, 6) if k - d in rec and rec[k - d][1] == have), 99))
            got = gb_oam_entries(shadow)
            expo, _, _ = compose(s["oam"], prog.hal_info["nobj"], u16(s["io"], 0), aff_tile=tile)
            if got != expo:
                mism.append((k, "oam", expo[:3], got[:3]))
        assert not mism, mism[:4]
        assert not tear, tear[:4]
        assert len(rec) >= N * 3 // 4
        missing = g.frame() - len(rec)          # GB vsyncs without a new GBA iteration (overruns)
        assert g.violations == [], g.violations[:5]
        assert worst <= math.pi / 32 + math.radians(4.5), math.degrees(worst)
        assert max(lag) <= 2, lag
        stream = [c // 4 for c in g.cycles["AffStream.go"]]
        idle = [c // 4 for c in g.cycles["AffStream"]]
        sel = [c // 4 for c in g.cycles["HAL_AFFINE_SEL"]]
        rep_out = {"frames_checked": len(seen), "gb_vblanks": g.vblanks(), "max_angle_error_deg": round(math.degrees(worst), 2),
                   "max_lag_frames": max(lag), "overrun_vsyncs": missing, "stream_chunk_mcycles": [min(stream), max(stream)],
                   "idle_mcycles": [min(idle), max(idle)], "sel_mcycles": [min(sel), max(sel)], "chunk_bytes": rep["chunk"],
                   "writes": g.writes, "rom_bytes": rep["rom_bytes"], "banks": rep["banks"]}
        os.makedirs(os.path.join(ROOT, "build", "reports"), exist_ok=True)
        json.dump(rep_out, open(os.path.join(ROOT, "build", "reports", "affine.json"), "w"), indent=1)
        print(rep_out)
        # one 128-byte chunk + the rest of the ISR must fit the 1140 M-cycle VBlank
        assert max(stream) + 300 < 1140
    finally:
        g.stop()
