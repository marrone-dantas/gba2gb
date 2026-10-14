"""Phase 5 A3: measure the peephole pass (tools/backend/peephole.py).

Kernels: average SM83 M-cycles per run (runtime timer, same seeds as the lockstep
test) and size of the "kernel" section, for the phase0 and sound backends, with and
without the pass; R0 must match the ARM reference in both builds.
Demos (HAL programs): kernel section size and average active M-cycles per frame:
the gap between the last wait-shim call (HAL_VCOUNT / HAL_VBLANKINTRWAIT) of a frame
and the next one, in which Compose runs (= the game code of the frame plus one shim
call)
over the first FRAMES frames without input.

Usage: python -m tools.backend.peephole_bench [--seeds N] [--json out.json]"""
import argparse
import glob
import json
import os
import re
import subprocess
from tools.backend.gba2gbc_core import build
from tools.harness import RefARM, GB
from tools.profile.seeds import seeds
from tools.hal.demos import DEMOS, elf as demo_elf, make as make_demos
from tools.hal.gb_run import GBRun

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "build", "peephole")
FRAMES = 120


def ksize(rom):
    m = re.search(r"\(\$([0-9a-f]+) bytes\) \[\"kernel\"\]", open(rom + ".map").read())
    return int(m.group(1), 16)


def kernel_row(name, mode, nseeds, pp):
    elf = os.path.join(ROOT, "build", "kernels", name + ".elf")
    rom = os.path.join(OUT, f"{name}.{mode}.{'pp' if pp else 'base'}.gbc")
    build(elf, rom, asm_out=rom[:-4] + ".asm", prune=None if mode == "phase0" else "sound", peephole=pp)
    ref, gb = RefARM(elf), GB(rom)
    tot, ok = 0, True
    try:
        for s in seeds(name, nseeds):
            got, cyc = gb.run(s)
            ok &= got == ref.run(s)
            tot += cyc
    finally:
        gb.stop()
    return {"cycles": tot / nseeds, "size": ksize(rom), "ok": ok}


def demo_row(name, pp):
    rom = os.path.join(OUT, f"{name}.{'pp' if pp else 'base'}.gbc")
    prog = build(demo_elf(name), rom, entry="main", asm_out=rom[:-4] + ".asm", prune="sound", hal=True,
                 peephole=pp)
    g = GBRun(rom, check_access=False)
    st = {"prev": None, "gap": 0}
    act = []

    def at_wait(_):
        now = g.pb._cycles()
        if st["prev"] is not None:
            st["gap"] = now - st["prev"]
        st["prev"] = now

    def at_fin(_):
        # Compose runs in the first wait call after a vsync: the gap before that call
        # is the frame's work (game code between two wait calls + one shim call)
        act.append(st["gap"])
    for sym, f in (("Compose.fin", at_fin), ("HAL_VBLANKINTRWAIT", at_wait), ("HAL_VCOUNT", at_wait)):
        if sym not in g.sym:
            continue
        b, a = g.sym[sym]
        g.pb.hook_register(b, a, f, None)
    while len(act) < FRAMES and g.frame() < FRAMES * 3:
        g.tick()
    g.stop()
    act = act[1:] or [0]                 # frame 1 includes the init work
    return {"cycles": sum(act) / len(act) / 4, "size": ksize(rom), "stats": prog.peephole}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=100)
    ap.add_argument("--demos-only", action="store_true")
    ap.add_argument("--json", default=os.path.join(OUT, "peephole_bench.json"))
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    subprocess.run(["make", "-s", "-C", os.path.join(ROOT, "tests", "kernels")], check=True)
    make_demos()
    kernels = sorted(os.path.basename(p)[:-2] for p in glob.glob(os.path.join(ROOT, "tests", "kernels", "k*.c")))
    res = {"kernels": {}, "demos": {}}
    for k in (kernels if not a.demos_only else []):
        for mode in ("phase0", "sound"):
            res["kernels"][f"{k}/{mode}"] = {"base": kernel_row(k, mode, a.seeds, False),
                                             "pp": kernel_row(k, mode, a.seeds, True)}
            r = res["kernels"][f"{k}/{mode}"]
            print(f"{k:22s} {mode:6s} cyc {r['base']['cycles']:9.0f} -> {r['pp']['cycles']:9.0f}  "
                  f"size {r['base']['size']:5d} -> {r['pp']['size']:5d}  ok={r['base']['ok'] and r['pp']['ok']}")
    for d in DEMOS:
        res["demos"][d] = {"base": demo_row(d, False), "pp": demo_row(d, True)}
        r = res["demos"][d]
        print(f"{d:22s} active/frame {r['base']['cycles']:9.0f} -> {r['pp']['cycles']:9.0f}  "
              f"size {r['base']['size']:5d} -> {r['pp']['size']:5d}  {r['pp']['stats']}")
    json.dump(res, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
