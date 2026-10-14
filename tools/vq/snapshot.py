"""GBA scene snapshot format (input of the VQ pipeline).

A snapshot is the raw video state of one GBA frame:
  vram  96 KiB  (0x06000000-0x06017FFF)
  pal    1 KiB  (0x05000000-0x050003FF; BG palette = first 512 bytes)
  io     at least 0x60 bytes of I/O starting at 0x04000000 (DISPCNT, BGxCNT, BGxHOFS/VOFS)
  oam    1 KiB  (optional, not used by the BG dumper)
optional collision metadata:
  solid_bg0 .. solid_bg3: uint8[1024], 1 = GBA tile number (map entry bits 0-9) is solid
optional metadata: name (str), source/license (str).

Two on-disk forms are accepted, chosen to be easy to produce from any emulator:
  * a .npz file with the arrays above (uint8) and optional string fields;
  * a directory with vram.bin, pal.bin, io.bin [, oam.bin] [, solid_bg<n>.bin] [, meta.json].
"""
import json
import os
import numpy as np

SIZES = {"vram": 0x18000, "pal": 0x400, "io": 0x60, "oam": 0x400}


def _check(s):
    for k in ("vram", "pal", "io"):
        a = np.asarray(s[k], dtype=np.uint8)
        if a.size < SIZES[k]:
            raise ValueError(f"snapshot {k}: {a.size} bytes, need {SIZES[k]}")
        s[k] = a[:SIZES[k]].copy() if k != "io" else a.copy()
    return s


def make(vram, pal, io, oam=None, solid=None, **meta):
    s = {"vram": np.frombuffer(bytes(vram), np.uint8), "pal": np.frombuffer(bytes(pal), np.uint8),
         "io": np.frombuffer(bytes(io), np.uint8)}
    if oam is not None:
        s["oam"] = np.frombuffer(bytes(oam), np.uint8)
    for n, m in (solid or {}).items():
        s[f"solid_bg{n}"] = np.asarray(m, np.uint8)
    s.update(meta)
    return _check(s)


def from_ref(snap, **meta):
    """Snapshot of tools.hal.gba_ref.GBARef.snapshot()."""
    return make(snap["vram"], snap["pal"], snap["io"], snap.get("oam"), **meta)


def save(s, path):
    if path.endswith(".npz"):
        np.savez_compressed(path, **{k: (np.asarray(v) if not isinstance(v, str) else np.array(v)) for k, v in s.items()})
        return
    os.makedirs(path, exist_ok=True)
    meta = {}
    for k, v in s.items():
        if isinstance(v, str):
            meta[k] = v
        else:
            open(os.path.join(path, k + ".bin"), "wb").write(np.asarray(v, np.uint8).tobytes())
    json.dump(meta, open(os.path.join(path, "meta.json"), "w"), indent=1)


def load(path):
    s = {}
    if os.path.isdir(path):
        for f in os.listdir(path):
            k, ext = os.path.splitext(f)
            if ext == ".bin":
                s[k] = np.fromfile(os.path.join(path, f), np.uint8)
        mp = os.path.join(path, "meta.json")
        if os.path.exists(mp):
            s.update(json.load(open(mp)))
    else:
        z = np.load(path)
        for k in z.files:
            v = z[k]
            s[k] = str(v) if v.dtype.kind in "US" else v
    return _check(s)


def solid_flags(s, bg):
    v = s.get(f"solid_bg{bg}")
    return None if v is None else np.asarray(v, bool)
