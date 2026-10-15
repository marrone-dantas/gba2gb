"""Per-build hotspot report (docs/profile_format.md, "Hotspot report").

Runs a PROFILE build in PyBoy (DMG) with a button plan and writes a Markdown report
and a JSON twin next to the ROM:
  * self time per function (lifted Thumb functions folded from their block labels,
    native / HAL routines by name);
  * inclusive-of-helpers time: native helpers (division, bank switches, ...) charged
    to the lifted function that called them (return address sampled by ProfISR);
  * for each focus function (default: the top 3 lifted ones): its time by source
    line (addr2line on the block addresses), by helper, and its direct callees
    (static BL targets) with their inclusive shares.
Contains no game content; works for any ELF built with debug line info.

    python -m tools.ports.hotspots ROM --elf game.elf --plan plan.json \\
        --frames 3000 --from 1100 [--focus _draw] [-o report.md]
"""
from __future__ import annotations
import argparse
import bisect
import collections
import json
import os
import re
import subprocess


def elf_funcs(elf):
    nm = subprocess.run(["arm-none-eabi-nm", "-n", "-S", "-C", elf], capture_output=True, text=True).stdout
    out = []
    for ln in nm.splitlines():
        p = ln.split(None, 3)
        if len(p) == 4 and p[2] in "tTwW":
            out.append((int(p[0], 16) & ~1, int(p[1], 16), p[3]))
    return sorted(out)


def addr2line(elf, addrs):
    if not addrs:
        return {}
    r = subprocess.run(["arm-none-eabi-addr2line", "-e", elf] + [f"{a:#x}" for a in addrs],
                       capture_output=True, text=True).stdout.splitlines()
    return {a: os.path.basename(l.split(" ")[0]) for a, l in zip(addrs, r)}


def bl_targets(elf, lo, size):
    d = subprocess.run(["arm-none-eabi-objdump", "-d", f"--start-address={lo:#x}",
                        f"--stop-address={lo + size:#x}", elf], capture_output=True, text=True).stdout
    return {int(m.group(1), 16) for m in re.finditer(r"\tbl\s+([0-9a-f]+)", d)}


def run(rom, plan, frames, start):
    from pyboy import PyBoy
    from tools.ports.profile import Profiler
    pb = PyBoy(rom, window="null", cgb=False, sound_emulated=False)
    pb.set_emulation_speed(0)
    pr = Profiler(pb, os.path.splitext(rom)[0] + ".sym")
    for f in range(frames):
        for s, b, d in plan:
            if f == s:
                pb.button_press(b)
            if f == s + d:
                pb.button_release(b)
        pb.tick(1, False)
        if f >= start:
            pr.poll()
        else:
            pr.last = pb.memory[pr.addr["wProfIdx"]]
    pb.stop(save=False)
    return pr


def analyse(pr, elf, focus=None, nfocus=3):
    fs = elf_funcs(elf)
    keys = [a for a, _, _ in fs]

    def func(label):
        m = re.fullmatch(r"L_([0-9A-F]{8})(?:_in)?", label)
        if not m:
            return None, None
        a = int(m.group(1), 16)
        i = bisect.bisect_right(keys, a) - 1
        return (fs[i][2] if i >= 0 else label), a

    T = max(1, pr.total)
    selft, incl = collections.Counter(), collections.Counter()
    for k, v in pr.hist.items():
        f, _ = func(k)
        selft[f"thumb:{f}" if f else k] += v
    for k, v in pr.blocks.items():
        f, _ = func(k)
        incl[f"thumb:{f}" if f else k] += v
    idle = sum(v for k, v in pr.hist.items() if "VBLANKINTRWAIT" in k)
    if focus is None:
        focus = [k[6:] for k, _ in incl.most_common() if k.startswith("thumb:")][:nfocus]
    rep = {"samples": pr.total, "idle": idle / T,
           "self": [(k, v / T) for k, v in selft.most_common(30)],
           "with_helpers": [(k, v / T) for k, v in incl.most_common(30)], "focus": {}}
    byname = {n: (a, s) for a, s, n in fs}
    for fn in focus:
        lines, helpers = collections.Counter(), collections.Counter()
        addrs = {}
        for k, v in pr.blocks.items():
            f, a = func(k)
            if f == fn:
                addrs[a] = addrs.get(a, 0) + v
        src = addr2line(elf, sorted(addrs))
        for a, v in addrs.items():
            lines[src.get(a, "?")] += v
        for (blk, h), v in pr.helpers.items():
            if func(blk)[0] == fn:
                helpers[h] += v
        callees = []
        if fn in byname:
            lo, size = byname[fn]
            for t in sorted(bl_targets(elf, lo, size)):
                i = bisect.bisect_right(keys, t) - 1
                if i >= 0 and fs[i][0] == t:
                    nm = fs[i][2]
                    callees.append((nm, incl.get(f"thumb:{nm}", 0) / T))
            callees.sort(key=lambda x: -x[1])
        tot = sum(addrs.values())
        rep["focus"][fn] = {"share": tot / T,
                            "lines": [(k, v / T) for k, v in lines.most_common(25)],
                            "helpers": [(k, v / T) for k, v in helpers.most_common(10)],
                            "callees": callees[:15]}
    return rep


def markdown(rep, title):
    pc = lambda x: f"{100 * x:.1f}%"
    L = [f"# Hotspots: {title}", "", f"{rep['samples']} samples, idle (VBlank wait) {pc(rep['idle'])}", "",
         "| function | self | with helpers |", "|---|---|---|"]
    inc = dict(rep["with_helpers"])
    for k, v in rep["self"][:25]:
        L.append(f"| `{k}` | {pc(v)} | {pc(inc.get(k, 0)) if k.startswith('thumb:') else ''} |")
    for fn, d in rep["focus"].items():
        L += ["", f"## `{fn}` ({pc(d['share'])} with helpers, excluding callees)", "",
              "| source line | share |", "|---|---|"] + [f"| {k} | {pc(v)} |" for k, v in d["lines"]]
        L += ["", "| helper called from it | share |", "|---|---|"] + [f"| `{k}` | {pc(v)} |" for k, v in d["helpers"]]
        L += ["", "| direct callee | share (with helpers) |", "|---|---|"] + [f"| `{k}` | {pc(v)} |" for k, v in d["callees"]]
    return "\n".join(L) + "\n"


def report(rom, elf, plan, frames=3000, start=0, focus=None, out=None):
    pr = run(rom, plan, frames, start)
    rep = analyse(pr, elf, focus)
    out = out or os.path.splitext(rom)[0] + ".hotspots.md"
    open(out, "w").write(markdown(rep, os.path.basename(rom)))
    json.dump(rep, open(os.path.splitext(out)[0] + ".json", "w"), indent=1)
    return rep, out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rom")
    ap.add_argument("--elf", required=True)
    ap.add_argument("--plan")
    ap.add_argument("--frames", type=int, default=3000)
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--focus", action="append")
    ap.add_argument("-o", "--out")
    a = ap.parse_args(argv)
    plan = json.load(open(a.plan)) if a.plan else []
    rep, out = report(a.rom, a.elf, plan, a.frames, a.start, a.focus, a.out)
    print(out)


if __name__ == "__main__":
    main()
