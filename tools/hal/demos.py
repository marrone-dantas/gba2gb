"""Build helpers for the Phase 2 demos (GBA ELF -> DMG .gbc)."""
import os
import subprocess
from tools.backend.gba2gbc_core import build

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEMOS = ["obj_demo", "key_demo", "brin_demo", "oam_stress", "input_test", "affine_demo", "sound_demo", "spill_demo", "ewram_demo"]


def make():
    subprocess.run(["make", "-s", "-C", os.path.join(ROOT, "tests", "demos")], check=True)


def elf(name):
    return os.path.join(ROOT, "build", "demos", name + ".elf")


def build_demo(name, prune="sound"):
    make()
    out = os.path.join(ROOT, "build", "demos_gb", name + ".gbc")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    prog = build(elf(name), out, entry="main", asm_out=out[:-4] + ".asm", prune=prune, hal=True)
    return out, prog
