"""Phase 3.2 scene dataset: open-licensed pixel art (Kenney, CC0) and procedural scenes
composed into multi-layer GBA mode-0 snapshots (tools/vq/snapshot.py).

    python -m tools.vq.dataset [--out data/vq/scenes]

Provenance and licenses: docs/vq_dataset.md. Every scene is a 240x160 view (with BG
scroll) of up to 3 text BGs; collision flags (`solid_bg<n>`) are derived per scene as
documented there."""
import argparse
import os
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image
from .gba_encode import encode
from . import snapshot

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KEN = os.path.join(ROOT, "assets", "vq", "kenney")
FLIP_H, FLIP_V, FLIP_D = 0x80000000, 0x40000000, 0x20000000


class Sheet:
    def __init__(self, png, tw, th, spacing=0, columns=None, crop=0, key=None):
        im = np.asarray(Image.open(png).convert("RGBA")).copy()
        if key is not None:                       # colour key -> transparent
            im[(im[..., :3] == key).all(-1), 3] = 0
        self.im, self.tw, self.th, self.sp, self.crop = im, tw, th, spacing, crop
        self.cols = columns or (im.shape[1] + spacing) // (tw + spacing)

    def tile(self, i):
        y, x = divmod(i, self.cols)
        y0, x0 = y * (self.th + self.sp), x * (self.tw + self.sp)
        t = self.im[y0:y0 + self.th, x0:x0 + self.tw]
        c = self.crop
        return t[c:self.th - c, c:self.tw - c] if c else t


def read_tmx(path):
    root = ET.parse(path).getroot()
    w, h = int(root.get("width")), int(root.get("height"))
    tilesets = [(int(t.get("firstgid")), t.get("source")) for t in root.findall("tileset")]
    layers = {}
    for L in root.findall("layer"):
        data = L.find("data").text
        layers[L.get("name")] = np.array([int(v) for v in data.replace("\n", "").split(",") if v.strip()],
                                         np.uint64).reshape(h, w)
    return w, h, tilesets, layers


def render_layers(gids, sheets, cell):
    """gids: list of 2-D gid arrays merged in order (later on top); sheets: [(firstgid, Sheet)]."""
    h, w = gids[0].shape
    out = np.zeros((h * cell, w * cell, 4), np.uint8)
    nonempty = np.zeros((h, w), bool)
    for g in gids:
        for y in range(h):
            for x in range(w):
                v = int(g[y, x])
                gid = v & 0x0FFFFFFF
                if gid == 0:
                    continue
                first, sh = max((f, s) for f, s in sheets if f <= gid)
                t = sh.tile(gid - first)
                if t.shape[0] != cell:
                    continue                      # other tile size (e.g. 24 px characters): skipped
                if v & FLIP_D:
                    t = t.transpose(1, 0, 2)
                if v & FLIP_H:
                    t = t[:, ::-1]
                if v & FLIP_V:
                    t = t[::-1]
                dst = out[y * cell:(y + 1) * cell, x * cell:(x + 1) * cell]
                m = t[..., 3] >= 128
                dst[m] = t[m]
                nonempty[y, x] |= m.any()
    return out, nonempty


def bg_canvas(img, ox, oy, size=(256, 256), fill=None):
    """Crop a size[0]xsize[1] (w x h) GBA BG map out of a rendered layer starting at (ox, oy)."""
    w, h = size
    out = np.zeros((h, w, 4), np.uint8)
    if fill is not None:
        out[...] = fill
    src = img[oy:oy + h, ox:ox + w]
    m = src[..., 3] >= 128
    out[:src.shape[0], :src.shape[1]][m] = src[m]
    return out


def cells8(mask16, ox, oy, cell, size=(256, 256)):
    """Per-8x8-cell solid mask of a BG canvas from a per-map-cell mask."""
    w, h = size
    ys, xs = np.mgrid[0:h // 8, 0:w // 8]
    my, mx = (ys * 8 + oy + 4) // cell, (xs * 8 + ox + 4) // cell
    ok = (my < mask16.shape[0]) & (mx < mask16.shape[1])
    out = np.zeros((h // 8, w // 8), bool)
    out[ok] = mask16[my[ok], mx[ok]]
    return out


def kenney_scenes():
    scenes = []
    # tiny-ski and tiny-dungeon: 16 px tiles, sheet with 1 px spacing
    for pack, base_l, top_l, solid_top, views in (
            ("tiny-ski", ["Terrain", "Shadows"], ["Objects", "Lift"], True, [(0, 0), (240, 128)]),
            ("tiny-dungeon", ["Dungeon"], ["Objects", "Carts"], True, [(0, 0), (256, 160)])):
        d = os.path.join(KEN, pack)
        sh = Sheet(os.path.join(d, "tilemap.png"), 16, 16, spacing=1, columns=12)
        w, h, _, L = read_tmx(os.path.join(d, "sampleMap.tmx"))
        base, base_ne = render_layers([L[n] for n in base_l], [(1, sh)], 16)
        top, top_ne = render_layers([L[n] for n in top_l], [(1, sh)], 16)
        solid = top_ne.copy()
        if pack == "tiny-dungeon":            # walls: dungeon cells that are not one of the 4 most common (floor) tiles
            g = L["Dungeon"]
            vals, cnt = np.unique(g, return_counts=True)
            floor = set(vals[np.argsort(cnt)[-4:]].tolist()) | {0}
            solid |= ~np.isin(g, list(floor))
        for k, (ox, oy) in enumerate(views):
            ox, oy = min(ox, base.shape[1] - 240), min(oy, base.shape[0] - 160)
            layers = [{"rgba": bg_canvas(top, ox, oy), "prio": 0, "solid": cells8(solid, ox, oy, 16)},
                      {"rgba": bg_canvas(base, ox, oy), "prio": 1, "solid": np.zeros((32, 32), bool)}]
            scenes.append((f"{pack}_{k}", layers, (0, 0, 0), f"Kenney {pack} (CC0), sampleMap.tmx view {ox},{oy}"))
    # pixel-platformer: 18 px tiles cropped to the central 16x16, far background strip
    d = os.path.join(KEN, "pixel-platformer")
    tiles = Sheet(os.path.join(d, "tilemap_packed.png"), 18, 18, crop=1)
    bgs = Sheet(os.path.join(d, "tilemap-backgrounds_packed.png"), 24, 24)
    for k, (tmx, col0) in enumerate((("tilemap-example-a.tmx", 0), ("tilemap-example-b.tmx", 6))):
        w, h, _, L = read_tmx(os.path.join(d, tmx))
        names = [n for n in L if n != "Characters"]
        near, ne = render_layers([L[n] for n in names[:1]], [(28, tiles)], 16)
        deco, _ = render_layers([L[n] for n in names[1:]], [(28, tiles)], 16)
        far = np.zeros((256, 256, 4), np.uint8)
        sky = bgs.tile(col0)[0, 0]
        far[...] = sky
        ncol = 4 if col0 == 0 else 2
        for x in range(0, 256, 24):
            for r in range(3):
                t = bgs.tile(r * 8 + col0 + (x // 24) % ncol)
                y0 = 160 - 72 + 24 * r
                far[y0:y0 + 24, x:min(x + 24, 256)] = t[:, :min(24, 256 - x)]
        layers = [{"rgba": bg_canvas(deco, 0, h * 16 - 160), "prio": 0, "solid": np.zeros((32, 32), bool)},
                  {"rgba": bg_canvas(near, 0, h * 16 - 160), "prio": 1, "solid": cells8(ne, 0, h * 16 - 160, 16)},
                  {"rgba": far, "prio": 2, "hofs": 40, "solid": np.zeros((32, 32), bool)}]
        scenes.append((f"platformer_{'ab'[k]}", layers, tuple(int(v) for v in sky[:3]),
                       f"Kenney Pixel Platformer (CC0), {tmx} + tilemap-backgrounds"))
    # 1-bit pack: single layer, colour key = sheet background, 1 px spacing
    d = os.path.join(KEN, "1-bit-pack")
    sh = Sheet(os.path.join(d, "tileset_legacy.png"), 16, 16, spacing=1, columns=32, key=(71, 45, 60))
    for name in ("interior", "urban", "fantasy", "platformer"):
        w, h, _, L = read_tmx(os.path.join(d, f"sample_{name}.tmx"))
        img, ne = render_layers(list(L.values()), [(1, sh)], 16)
        ox, oy = (w * 16 - 240) // 2, (h * 16 - 160) // 2
        layers = [{"rgba": bg_canvas(img, ox, oy), "prio": 0, "solid": cells8(ne, ox, oy, 16)}]
        scenes.append((f"1bit_{name}", layers, (71, 45, 60), f"Kenney 1-Bit Pack (CC0), sample_{name}.tmx"))
    return scenes


def procedural_scenes(seed=7):
    rng = np.random.default_rng(seed)
    scenes = []
    # 1. hills parallax: gradient-banded sky (8bpp far), hills, brick platforms (solid)
    far = np.zeros((256, 256, 4), np.uint8)
    for y in range(256):
        c = np.array([40 + y // 2, 90 + y // 3, 200 - y // 4])
        far[y, :, :3] = np.clip(c[None, :] + (((np.arange(256) + y) % 4 == 0) * 6)[:, None], 0, 255)
    far[..., 3] = 255
    hill = np.zeros((256, 256, 4), np.uint8)
    xs = np.arange(256)
    top = (110 + 18 * np.sin(xs / 20) + 8 * np.sin(xs / 7)).astype(int)
    for x in xs:
        hill[top[x]:, x] = (34, 120 + (x % 16 < 8) * 20, 50, 255)
    near = np.zeros((256, 256, 4), np.uint8)
    solid = np.zeros((32, 32), bool)
    brick = np.zeros((8, 8, 4), np.uint8)
    brick[...] = (150, 70, 40, 255)
    brick[3, :] = brick[7, :] = (60, 30, 20, 255)
    brick[:4, 3] = brick[4:, 7] = (60, 30, 20, 255)
    for cy, cx0, n in ((17, 2, 8), (13, 12, 6), (19, 20, 10), (10, 22, 5)):
        for cx in range(cx0, cx0 + n):
            near[cy * 8:cy * 8 + 8, cx * 8:cx * 8 + 8] = brick
            solid[cy, cx] = True
    scenes.append(("proc_hills", [{"rgba": near, "prio": 0, "solid": solid},
                                  {"rgba": hill, "prio": 1, "hofs": 30, "solid": np.zeros((32, 32), bool)},
                                  {"rgba": far, "prio": 2, "solid": np.zeros((32, 32), bool), "bpp8": True}],
                   (0, 0, 0), "procedural (this project)"))
    # 2. cave: value-noise rock (solid), smooth gradients, 8bpp
    n = rng.random((9, 9))
    from PIL import Image as I
    noise = np.asarray(I.fromarray((n * 255).astype(np.uint8)).resize((256, 256), I.BICUBIC)) / 255.0
    cave = np.zeros((256, 256, 4), np.uint8)
    rock = noise > 0.55
    shade = (noise * 120 + 40).astype(np.uint8)
    cave[rock] = np.stack([shade, shade * 0.8, shade * 0.6, np.full_like(shade, 255)], -1)[rock]
    cave[..., :3] = (cave[..., :3] // 16) * 16                 # posterize: <= 256 colours
    rsolid = rock.reshape(32, 8, 32, 8).mean((1, 3)) > 0.5
    scenes.append(("proc_cave", [{"rgba": cave, "prio": 0, "solid": rsolid}], (20, 10, 30),
                   "procedural (this project)"))
    # 3. checker/text HUD stress: high-frequency patterns and many distinct glyph-like tiles
    hud = np.zeros((256, 256, 4), np.uint8)
    glyphs = rng.random((200, 8, 8)) < 0.4
    for cy in range(20):
        for cx in range(30):
            g = glyphs[(cy * 30 + cx) % 200]
            hud[cy * 8:cy * 8 + 8, cx * 8:cx * 8 + 8][g] = (230, 230, 210, 255)
            if (cx + cy) % 2:
                hud[cy * 8:cy * 8 + 8, cx * 8:cx * 8 + 8][~g] = (40, 60, 90, 255)
    scenes.append(("proc_glyphs", [{"rgba": hud, "prio": 0, "solid": np.zeros((32, 32), bool)}], (0, 0, 0),
                   "procedural (this project)"))
    return scenes


def phase2_brin():
    from .snapshot import from_ref
    from tools.hal.demos import elf
    from tools.hal.gba_ref import GBARef
    s = GBARef(elf("brin_demo")).run([0] * 40, 40)[-1]
    snap = from_ref(s, name="brin_demo", source="tests/demos/brin_demo.c (this project), Unicorn reference frame 40")
    snap["io"][1] &= 0xEF
    flags = np.zeros(1024, np.uint8)
    flags[1:] = 1                                  # every non-empty brick tile is solid
    snap["solid_bg0"] = flags
    return snap


def build(out):
    os.makedirs(out, exist_ok=True)
    names = []
    for name, layers, backdrop, src in kenney_scenes() + procedural_scenes():
        s = encode(layers, backdrop=backdrop, name=name, source=src)
        s.pop("_info")
        snapshot.save(s, os.path.join(out, name + ".npz"))
        names.append(name)
    try:
        snapshot.save(phase2_brin(), os.path.join(out, "brin_demo.npz"))
        names.append("brin_demo")
    except Exception as e:                         # demo toolchain missing
        print("brin_demo skipped:", e)
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "vq", "scenes"))
    print(build(ap.parse_args().out))


if __name__ == "__main__":
    main()
