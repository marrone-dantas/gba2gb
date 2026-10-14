"""Build a DMG .gb ROM showing a VQ-compiled scene (runtime/vq_scene.asm)."""
import os
import subprocess
import numpy as np
from .vq_tile_compiler import export

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASM = os.path.join(ROOT, "runtime", "vq_scene.asm")


def build_rom(res, out_dir, name="scene"):
    os.makedirs(out_dir, exist_ok=True)
    st = res["stats"]
    class16 = int(len(res["lut"]) > 256)
    lut = res["lut"]
    export(res, out_dir)
    if class16:
        open(os.path.join(out_dir, "classes.bin"), "wb").write(res["classes"].astype("<u2").tobytes())
    else:
        open(os.path.join(out_dir, "classes.bin"), "wb").write(res["classes"].astype(np.uint8).tobytes())
    mw, mh = st["map_w"], st["map_h"]
    max_x, max_y = max(mw * 8 - 160, 0), max(mh * 8 - 144, 0)
    o = os.path.join(out_dir, name + ".o")
    rom = os.path.join(out_dir, name + ".gb")
    defs = [f"-DMAP_W={mw}", f"-DMAP_H={mh}", f"-DCLASS16={class16}", f"-DMAX_X={max_x}", f"-DMAX_Y={max_y}"]
    subprocess.run(["rgbasm", *defs, "-I", out_dir, "-o", o, ASM], check=True)
    subprocess.run(["rgblink", "-o", rom, "-n", rom[:-3] + ".sym", o], check=True)
    subprocess.run(["rgbfix", "-v", "-p", "0xFF", "-t", "VQSCENE", rom], check=True, capture_output=True)
    return rom, {"class16": bool(class16), "max_x": max_x, "max_y": max_y, "classes": int(len(lut))}


def read_sym(path):
    out = {}
    for line in open(path):
        line = line.split(";")[0].strip()
        if not line:
            continue
        a, n = line.split()
        b, addr = a.split(":")
        out[n] = (int(b, 16), int(addr, 16))
    return out


class SceneRun:
    """Run the scene ROM in PyBoy (DMG); measure the remap and copy loops (M-cycles)."""

    def __init__(self, rom):
        from pyboy import PyBoy
        self.pb = PyBoy(rom, window="null", cgb=False, sound_emulated=False)
        sym = read_sym(rom[:-3] + ".sym")
        self.t = {}
        for lab in ("RemapStart", "RemapEnd", "CopyStart", "CopyEnd"):
            b, a = sym[lab]
            self.pb.hook_register(b, a, self._hook, lab)

    def _hook(self, lab):
        self.t.setdefault(lab, self.pb._cycles())

    def tick(self, n=1):
        for _ in range(n):
            self.pb.tick(1, True)

    def scroll(self):
        return self.pb.memory[0xFF43], self.pb.memory[0xFF42]

    def screen_levels(self):
        g = np.asarray(self.pb.screen.image.convert("L"), np.int32)
        return np.argmin(np.abs(g[..., None] - np.array([255, 170, 85, 0])[None, None]), -1)

    def loop_mcycles(self):
        return (self.t["RemapEnd"] - self.t["RemapStart"]) / 4, (self.t["CopyEnd"] - self.t["CopyStart"]) / 4

    def stop(self):
        self.pb.stop(save=False)
