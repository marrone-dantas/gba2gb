"""CLI gba2gbc-core: ELF/bin Thumb -> ROM .gbc (MBC5) via RGBDS.

Usage: python -m tools.backend.gba2gbc_core kernel.elf -o kernel.gbc [--asm out.asm]"""
import argparse
import os
import subprocess
import sys
import tempfile
from tools.lift.lift import lift_file
from tools.backend.codegen import generate_asm

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNTIME = os.path.join(ROOT, "runtime")


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{' '.join(cmd)}\n{r.stdout}{r.stderr}")


def build(src, out, entry="f", asm_out=None, prune=None, profile=None, opts=None):
    """prune: None (Phase 0), 'flags' (narrowed backend but all values 32-bit),
    'sound' (proven ranges) or 'profile' (observed ranges + guards; needs profile)."""
    prog = lift_file(src, entry)
    if prune:
        from tools.prune.bitwidth_pruning import build_plan
        from tools.backend.narrow import generate_narrow_asm
        plan = build_plan(prog, profile, "profile" if prune == "profile" else "sound", opts)
        if prune == "flags":
            plan.mode = "flags-only"
            plan.storage = {}
            plan.fused, plan.deleted = {}, set()
        asm, stats = generate_narrow_asm(plan)
        prog.plan, prog.stats = plan, stats
    else:
        asm = generate_asm(prog)
    with tempfile.TemporaryDirectory() as td:
        k = asm_out or os.path.join(td, "kernel.asm")
        open(k, "w").write(asm)
        ko, ro = os.path.join(td, "kernel.o"), os.path.join(td, "runtime.o")
        run(["rgbasm", "-I", RUNTIME, "-o", ko, k])
        run(["rgbasm", "-I", RUNTIME, "-o", ro, os.path.join(RUNTIME, "runtime.asm")])
        run(["rgblink", "-o", out, "-m", out + ".map", ro, ko])
        run(["rgbfix", "-v", "-p", "0xFF", "-m", "0x1B", "-r", "0x04", "-t", "GBA2GB", out])
    return prog


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gba2gbc-core", description=__doc__)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--entry", default="f")
    ap.add_argument("--asm")
    ap.add_argument("--prune", choices=["flags", "sound", "profile"],
                    help="Phase 1 bit-width pruning mode (default: Phase 0 code)")
    ap.add_argument("--profile", help="range profile JSON (required for --prune profile)")
    a = ap.parse_args(argv)
    import json
    prof = json.load(open(a.profile)) if a.profile else None
    p = build(a.input, a.output, a.entry, a.asm, a.prune, prof)
    print(f"{a.output}: {len(p.ins)} Thumb instructions translated")


if __name__ == "__main__":
    sys.exit(main())
