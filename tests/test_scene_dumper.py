"""Phase 3.1: VRAM scene dumper (text BGs, 4/8bpp, flips, palettes, scroll, priorities)."""
import numpy as np
import pytest
from tools.vq.gba_encode import encode, to555
from tools.vq.vram_scene_dumper import dump, bgr555_to_rgb
from tools.vq import snapshot

rng = np.random.default_rng(1)


def q(rgb):
    return bgr555_to_rgb(to555(rgb))


def tiled(h, w, ncol, ntiles, p, flips=True, per_tile=6):
    pc = rng.integers(0, 256, (ncol, 3))
    T = np.stack([rng.choice(rng.permutation(ncol)[:per_tile], (8, 8)) for _ in range(ntiles)])
    A = rng.random((ntiles, 8, 8)) < p
    L = np.zeros((h, w, 4), np.uint8)
    for y in range(0, h, 8):
        for x in range(0, w, 8):
            k, f = rng.integers(ntiles), rng.integers(4) if flips else 0
            t, a = T[k], A[k]
            if f & 1:
                t, a = t[:, ::-1], a[:, ::-1]
            if f & 2:
                t, a = t[::-1], a[::-1]
            L[y:y + 8, x:x + 8, :3] = pc[t]
            L[y:y + 8, x:x + 8, 3] = a * 255
    return L


def view(L, h, v):
    ys, xs = np.mgrid[0:160, 0:240]
    hh, ww = L.shape[:2]
    return L[(ys + v) % hh, (xs + h) % ww]


def test_roundtrip_multilayer(tmp_path):
    L0 = tiled(256, 512, 12, 40, 1.0)            # 4bpp, 512x256, opaque
    L1 = tiled(256, 256, 24, 60, 0.3)            # several 4bpp banks
    L2 = tiled(512, 256, 40, 80, 0.4, per_tile=20)           # 8bpp, 256x512
    layers = [{"rgba": L0, "prio": 1, "hofs": 300, "vofs": 17},
              {"rgba": L1, "prio": 0, "hofs": 5, "vofs": 250},
              {"rgba": L2, "prio": 0, "hofs": 0, "vofs": 400}]
    s = encode(layers, backdrop=(10, 20, 30))
    assert [i["bpp8"] for i in s.pop("_info")] == [False, False, True]
    for path in (str(tmp_path / "s.npz"), str(tmp_path / "dir")):
        snapshot.save(s, path)
        d = dump(snapshot.load(path))
        assert d["order"] == [1, 2, 0]           # prio 0 (BG1, BG2 by number) above prio 1
        exp = np.broadcast_to(q(np.array([10, 20, 30])), (160, 240, 3)).copy()
        for L, (h, v) in ((L0, (300, 17)), (L2, (0, 400)), (L1, (5, 250))):
            a = view(L, h, v)
            m = a[..., 3] >= 128
            exp[m] = q(a[..., :3])[m]
        assert (d["composite"] == exp).all()


def test_flips_and_palette_banks_used():
    s = encode([{"rgba": tiled(256, 256, 40, 30, 1.0)}])
    vram = s["vram"]
    ent = vram[24 * 0x800: 25 * 0x800].view(np.uint16)
    assert (ent & 0x400).any() and (ent & 0x800).any()        # flips deduplicated
    assert len(set((ent >> 12).tolist())) > 1                # several palette banks


def test_solid_mask():
    L = tiled(256, 256, 8, 20, 1.0, flips=False)
    solid = np.zeros((32, 32), bool)
    solid[20:, :] = True
    s = encode([{"rgba": L, "solid": solid}])
    d = dump(s)
    assert d["solid"][160 - 8:, :].all()


def test_matches_gba_reference_render():
    """brin_demo running in the Unicorn reference: dumper == reference BG renderer."""
    from tools.hal.demos import elf
    from tools.hal.gba_ref import GBARef, render
    snaps = GBARef(elf("brin_demo")).run([0] * 40, 40)
    s = snapshot.from_ref(snaps[-1])
    s["io"][1] &= 0xEF                                  # objects off: compare BGs only
    ref = np.asarray(render({**snaps[-1], "io": bytes(s["io"])}).convert("RGB"))
    d = dump(s)
    assert (d["composite"] == ref).all()
