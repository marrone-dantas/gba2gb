"""CLI gba2gbc-core: ELF/bin Thumb -> ROM .gbc (MBC5) via RGBDS.

Uso: python -m tools.backend.gba2gbc_core kernel.elf -o kernel.gbc [--asm saida.asm]"""
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


def build(src, out, entry="f", asm_out=None):
    prog = lift_file(src, entry)
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
    a = ap.parse_args(argv)
    p = build(a.input, a.output, a.entry, a.asm)
    print(f"{a.output}: {len(p.ins)} instruções Thumb traduzidas")


if __name__ == "__main__":
    sys.exit(main())
