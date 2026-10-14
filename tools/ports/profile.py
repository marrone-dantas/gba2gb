"""Statistical profiler for HAL builds (PROFILE define, runtime/gb_hal_shims.asm):
an LYC interrupt every 9 lines (~17 samples per frame) records PC + ROMX bank; samples
are attributed to the nearest preceding symbol of the .sym file.

Usage (library): samples = Profiler(pyboy, sym_path); call .poll() after every tick;
.report(n) -> [(symbol, share)]."""
from __future__ import annotations
import bisect
import collections


def load_sym(path):
    out = []
    for ln in open(path):
        ln = ln.split(";")[0].split()
        if len(ln) == 2 and ":" in ln[0]:
            b, o = ln[0].split(":")
            out.append((int(b, 16), int(o, 16), ln[1]))
    return out


class Profiler:
    def __init__(self, pb, sym_path, func_only=True):
        self.pb = pb
        self.syms = load_sym(sym_path)
        self.by = collections.defaultdict(list)
        for b, o, n in self.syms:
            if func_only and "." in n:
                continue
            self.by[b].append((o, n))
        for b in self.by:
            self.by[b].sort()
        self.addr = {n: o for b, o, n in self.syms}
        self.last = 0
        self.hist = collections.Counter()
        self.total = 0

    def name(self, pc, bank):
        b = 0 if pc < 0x4000 else bank
        lst = self.by.get(b, [])
        i = bisect.bisect_right(lst, (pc, "\uffff")) - 1
        return lst[i][1] if i >= 0 else f"?{b:02X}:{pc:04X}"

    def poll(self):
        m = self.pb.memory
        base = self.addr["wProfRing"]
        idx = m[self.addr["wProfIdx"]]
        i = self.last
        while i != idx:
            pc = m[base + i] | m[base + i + 1] << 8
            self.hist[self.name(pc, m[base + i + 2])] += 1
            self.total += 1
            i = (i + 4) % 252
        self.last = idx

    def report(self, n=30, elf=None):
        """[(name, share)]; with elf, block labels L_xxxxxxxx fold into their Thumb function."""
        h = self.hist
        if elf:
            import re
            import subprocess
            nm = subprocess.run(["arm-none-eabi-nm", "-n", "-C", elf], capture_output=True, text=True).stdout
            fs = sorted((int(l.split()[0], 16) & ~1, l.split(None, 2)[2]) for l in nm.splitlines()
                        if len(l.split()) >= 3 and l.split()[1] in "tTwW")
            keys = [a for a, _ in fs]
            h = collections.Counter()
            for k, v in self.hist.items():
                m = re.fullmatch(r"L_([0-9A-F]{8})(?:_in)?", k)
                if m:
                    i = bisect.bisect_right(keys, int(m.group(1), 16)) - 1
                    k = "thumb:" + (fs[i][1] if i >= 0 else k)
                h[k] += v
        return [(k, v / max(1, self.total)) for k, v in h.most_common(n)]
