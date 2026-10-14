"""Phase 4.2: mode-7-like raster tables for the DMG (docs/mode7.md).

The DMG can only change SCX/SCY between lines; it cannot scale or rotate a line.
This tool bakes, per camera yaw and forward phase, a 144-line (SCY, SCX) table such
that every screen line shows the texture row whose content (road half-width class,
stripe phase) matches the true ground-plane projection of that line, shifted so the
road centre lands where the projection puts it. The texture is organised in rows:
30 width classes x 8 stripe phases, plus 16 sky rows.

Reference ("simplified GBA side", no Thumb program): `true_view` renders the same
ground plane with a real per-pixel mode-7 projection (rotation + perspective
scaling, what GBA mode 1/2 with per-line affine parameters would show). `gb_view`
is the exact model of the DMG screen (map + table), compared pixel-exactly with
PyBoy; SSIM(true, gb) measures how much the per-line approximation loses."""
from __future__ import annotations
import math
import os
import subprocess
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HZ = 48                     # horizon line
F, HC, W, CAM_U, K = 120.0, 10.0, 8.0, 3.0, 0.5
NANG, NPH, NCLS = 32, 8, 30
YAW = math.radians(30)      # yaw range +-30 degrees
TABLE_BYTES = 290
PER_BANK = 16384 // TABLE_BYTES


def yaw(a):
    return (a - NANG // 2) / (NANG // 2) * YAW


def class_hw(c):
    return 2 + c * (80 - 2) / (NCLS - 1)


def texture_row(hw, s):
    """One 256-px texture row: road of half width hw centred at x = 128, stripe phase s."""
    x = np.arange(256) - 128 + 0.5
    on = s < NPH // 2
    row = np.full(256, 1 if on else 0, np.uint8)               # grass bands
    road = np.abs(x) < hw
    row[road] = 2
    rumble = road & (np.abs(x) >= hw - max(1.5, hw * 0.12))
    row[rumble] = 3 if on else 0
    centre = np.abs(x) < max(0.5, hw * 0.03)
    if on:
        row[centre & road] = 0
    return row


def texture():
    tex = np.zeros((256, 256), np.uint8)
    for c in range(NCLS):
        for s in range(NPH):
            tex[NPH * c + s] = texture_row(class_hw(c), s)
    for s in range(16):                                         # sky + hills
        y = 240 + s
        hill = 8 + 6 * np.sin(np.arange(256) * 2 * math.pi / 64) + 3 * np.sin(np.arange(256) * 2 * math.pi / 23)
        tex[y] = np.where(15 - s < hill * 0.5, 1, 0)
    return tex


def depth(y):
    d = y - HZ + 1
    return HC * F / d


def line_params(y, th, p):
    """(width class, stripe row, road-centre screen x) of screen line y >= HZ."""
    z = depth(y)
    X = -(z * math.sin(th) + CAM_U) / math.cos(th)
    xc = 80 + X * F / z
    hw = W * F / (z * math.cos(th)) if math.cos(th) else 80
    c = int(np.argmin([abs(class_hw(i) - hw) for i in range(NCLS)]))
    v = -X * math.sin(th) + z * math.cos(th)
    s = int(math.floor(v * K + p)) % NPH
    return c, s, xc


def table(a, p):
    th = yaw(a)
    out = []
    for y in range(144):
        if y < HZ:
            row = 240 + (y + 16 - HZ % 16) % 16 if y >= HZ - 16 else 240
            scx = int(round(th / YAW * 64)) & 255                  # sky pans with the yaw
        else:
            c, s, xc = line_params(y, th, p)
            row = NPH * c + s
            scx = int(round(128 - xc)) & 255
        out.append(((row - y) & 255, scx))
    out.append((0, 0))
    return out


def gb_view(tex, tab):
    """Exact DMG screen for a table: line y shows map row (y + SCY) & 255 from SCX."""
    img = np.zeros((144, 160), np.uint8)
    for y in range(144):
        scy, scx = tab[y]
        img[y] = tex[(y + scy) & 255][(np.arange(160) + scx) & 255]
    return img


def true_view(tex, a, p):
    """Per-pixel ground-plane projection (rotation + perspective) of the same world."""
    th = yaw(a)
    img = np.zeros((144, 160), np.uint8)
    t0 = table(a, p)
    for y in range(HZ):
        scy, scx = t0[y]
        img[y] = tex[(y + scy) & 255][(np.arange(160) + scx) & 255]
    xs = np.arange(160) - 80 + 0.5
    for y in range(HZ, 144):
        z = depth(y)
        X = xs * z / F
        u = X * math.cos(th) + z * math.sin(th) + CAM_U
        v = -X * math.sin(th) + z * math.cos(th)
        s = np.floor(v * K + p).astype(int) % NPH
        on = s < NPH // 2
        hw = W
        row = np.where(on, 1, 0).astype(np.uint8)
        road = np.abs(u) < hw
        row[road] = 2
        rumble = road & (np.abs(u) >= hw - hw * 0.12)
        row[rumble & on] = 3
        row[rumble & ~on] = 0
        row[road & on & (np.abs(u) < hw * 0.03)] = 0
        img[y] = row
    return img


def tiles_and_map(tex):
    tiles, index, m = [], {}, []
    for ty in range(32):
        for tx in range(32):
            t = tex[8 * ty:8 * ty + 8, 8 * tx:8 * tx + 8].tobytes()
            if t not in index:
                index[t] = len(tiles)
                tiles.append(t)
            m.append(index[t])
    if len(tiles) > 256:
        raise ValueError(f"{len(tiles)} unique tiles > 256")
    data = bytearray()
    for t in tiles:
        a = np.frombuffer(t, np.uint8).reshape(8, 8)
        for r in range(8):
            data.append(sum(((a[r, p] & 1) << (7 - p)) for p in range(8)))
            data.append(sum(((a[r, p] >> 1) << (7 - p)) for p in range(8)))
    return bytes(data), bytes(m), len(tiles)


def write_data(out):
    os.makedirs(out, exist_ok=True)
    tex = texture()
    tdata, mdata, nt = tiles_and_map(tex)
    open(os.path.join(out, "m7_tiles.2bpp"), "wb").write(tdata)
    open(os.path.join(out, "m7_map.bin"), "wb").write(mdata)
    tabs = [table(a, p) for a in range(NANG) for p in range(NPH)]
    L = [f"DEF NTILES EQU {nt}", f"DEF NTABLES EQU {len(tabs)}", 'SECTION "m7_track_gfx", ROM0',
         'Tiles:: INCBIN "m7_tiles.2bpp"', 'Map:: INCBIN "m7_map.bin"', "AddrTab::"]
    for t in range(len(tabs)):
        b, off = 1 + t // PER_BANK, 0x4000 + (t % PER_BANK) * TABLE_BYTES
        L.append(f"    db {b}, LOW(${off:04X}), HIGH(${off:04X})")
    nb = -(-len(tabs) // PER_BANK)
    for b in range(nb):
        blob = b"".join(bytes(v for e in tab for v in e) for tab in tabs[b * PER_BANK:(b + 1) * PER_BANK])
        fn = f"m7_tables_{b}.bin"
        open(os.path.join(out, fn), "wb").write(blob)
        L += [f'SECTION "m7_tables_{b}", ROMX[$4000], BANK[{1 + b}]', f'    INCBIN "{fn}"']
    open(os.path.join(out, "m7_track_data.inc"), "w").write("\n".join(L) + "\n")
    return {"tiles": nt, "tables": len(tabs), "banks": nb, "table_bytes": TABLE_BYTES,
            "rom_table_bytes": len(tabs) * TABLE_BYTES}, tex, tabs


def build_rom(out, src="mode7_track.asm", pinned=False, name=None):
    info, tex, tabs = write_data(out)
    name = name or ("mode7_track_pinned" if pinned else "mode7_track")
    o, rom = os.path.join(out, name + ".o"), os.path.join(out, name + ".gb")
    defs = ["-DM7_PINNED"] if pinned else []
    subprocess.run(["rgbasm", *defs, "-I", os.path.join(ROOT, "runtime"), "-I", out, "-o", o,
                    os.path.join(ROOT, "tests", "demos", src)], check=True)
    subprocess.run(["rgblink", "-o", rom, "-n", rom[:-3] + ".sym", o], check=True)
    subprocess.run(["rgbfix", "-v", "-p", "0xFF", "-m", "0x19", "-t", "MODE7", rom], check=True, capture_output=True)
    return rom, info, tex, tabs
