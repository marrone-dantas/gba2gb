"""Dynamic range tracer (Phase 1, part A1).

Runs a Thumb kernel on Unicorn for a list of seeds and records, using code and
memory hooks:
  * for each (PC, destination register): the value written by that instruction;
  * for each memory address: every value read or written there.
Each site accumulates min/max (unsigned and signed), bitmask_or and stride.
Output format: docs/profile_format.md.

Usage: python -m tools.profile.range_tracer KERNEL.elf [-n SEEDS] [-o out.json]
       python -m tools.profile.range_tracer --all [-n SEEDS]   (all 20 kernels)
"""
from __future__ import annotations
import argparse
import glob
import json
import math
import os
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn import arm_const as U
from tools.lift.lift import lift_file
from tools.lift.defuse import defs
from tools.profile.seeds import seeds

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SP0 = 0x03001F00
SENTINEL = 0x08F00000
FORMAT = "gba2gb-range-profile/1"
UREG = [getattr(U, f"UC_ARM_REG_R{i}") for i in range(13)] + [U.UC_ARM_REG_SP, U.UC_ARM_REG_LR, U.UC_ARM_REG_PC]


def s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


class Stat:
    """Running statistics of the values observed at one site."""
    __slots__ = ("count", "umin", "umax", "smin", "smax", "bor", "first", "stride", "sizes")

    def __init__(self):
        self.count, self.bor, self.stride, self.first = 0, 0, 0, None
        self.umin = self.smin = None
        self.umax = self.smax = None
        self.sizes = set()

    def add(self, v, size=None):
        if size:
            self.sizes.add(size)
        s = s32(v) if size in (None, 4) else v
        if self.count == 0:
            self.first, self.umin, self.umax, self.smin, self.smax = v, v, v, s, s
        else:
            self.umin, self.umax = min(self.umin, v), max(self.umax, v)
            self.smin, self.smax = min(self.smin, s), max(self.smax, s)
            # gcd of all deltas == gcd of (v - first) over all v
            self.stride = math.gcd(self.stride, abs(v - self.first))
        self.count += 1
        self.bor |= v

    def to_json(self):
        d = {"count": self.count, "umin": self.umin, "umax": self.umax, "smin": self.smin,
             "smax": self.smax, "bitmask_or": self.bor, "stride": self.stride}
        if self.sizes:
            d["sizes"] = sorted(self.sizes)
        return d


class Tracer:
    def __init__(self, elf):
        self.elf = elf
        self.prog = lift_file(elf)
        # for BL only LR is observable right after the instruction (the callee runs next)
        self.defmap = {a: ([14] if x.op == "bl" else [r for r in defs(x) if r != 15])
                       for a, x in self.prog.ins.items()}
        self.regs: dict[tuple, Stat] = {}
        self.mem: dict[int, Stat] = {}
        uc = self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        uc.mem_map(0x08000000, 0x01000000)
        uc.mem_map(0x03000000, 0x10000)
        img = self.prog.img
        uc.mem_write(img.base, img.data)
        self.pending = None
        uc.hook_add(UC_HOOK_CODE, self._code)
        uc.hook_add(UC_HOOK_MEM_READ, self._mread)
        uc.hook_add(UC_HOOK_MEM_WRITE, self._mwrite)
        self.in_text = (img.base, img.base + len(img.data))

    def _flush(self):
        if self.pending is not None:
            pc, rs = self.pending
            for r in rs:
                st = self.regs.get((pc, r))
                if st is None:
                    st = self.regs[(pc, r)] = Stat()
                st.add(self.uc.reg_read(UREG[r]) & 0xFFFFFFFF)
            self.pending = None

    def _code(self, uc, addr, size, _):
        self._flush()
        rs = self.defmap.get(addr)
        if rs:
            self.pending = (addr, rs)

    def _rec(self, addr, size, value):
        if self.in_text[0] <= addr < self.in_text[1]:
            return  # literal-pool reads are constants, not data
        st = self.mem.get(addr)
        if st is None:
            st = self.mem[addr] = Stat()
        st.add(value & ((1 << (8 * size)) - 1), size)

    def _mread(self, uc, access, addr, size, value, _):
        self._rec(addr, size, int.from_bytes(uc.mem_read(addr, size), "little"))

    def _mwrite(self, uc, access, addr, size, value, _):
        self._rec(addr, size, value)

    def run(self, regs):
        uc = self.uc
        for r, v in zip(UREG, regs):
            uc.reg_write(r, v)
        uc.reg_write(U.UC_ARM_REG_SP, SP0)
        uc.reg_write(U.UC_ARM_REG_LR, SENTINEL | 1)
        self.pending = None
        uc.emu_start(self.prog.entry | 1, SENTINEL, count=2_000_000)
        self._flush()

    def profile(self, name, nseeds):
        return {
            "format": FORMAT, "kernel": name, "elf": os.path.relpath(self.elf, ROOT),
            "entry": hex(self.prog.entry), "seeds": nseeds,
            "regs": {f"{pc:#010x}:r{r}": st.to_json() for (pc, r), st in sorted(self.regs.items())},
            "mem": {f"{a:#010x}": st.to_json() for a, st in sorted(self.mem.items())},
        }


def trace_kernel(elf, nseeds=1000, out=None):
    name = os.path.basename(elf)[:-4]
    t = Tracer(elf)
    for s in seeds(name, nseeds):
        t.run(s)
    prof = t.profile(name, nseeds)
    if out:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w") as fh:
            json.dump(prof, fh, indent=1)
    return prof


def _one(args):
    elf, n = args
    out = os.path.join(ROOT, "build", "profiles", os.path.basename(elf)[:-4] + ".json")
    p = trace_kernel(elf, n, out)
    return p["kernel"], len(p["regs"]), len(p["mem"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("elf", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("-n", "--seeds", type=int, default=1000)
    ap.add_argument("-o", "--output")
    a = ap.parse_args(argv)
    if a.all:
        import subprocess
        from multiprocessing import Pool
        subprocess.run(["make", "-s", "-C", os.path.join(ROOT, "tests", "kernels")], check=True)
        elfs = sorted(glob.glob(os.path.join(ROOT, "build", "kernels", "k*.elf")))
        with Pool() as pool:
            for k, nr, nm in pool.map(_one, [(e, a.seeds) for e in elfs]):
                print(f"{k}: {nr} register sites, {nm} memory addresses")
    else:
        p = trace_kernel(a.elf, a.seeds, a.output)
        print(f"{p['kernel']}: {len(p['regs'])} register sites, {len(p['mem'])} memory addresses")


if __name__ == "__main__":
    main()
