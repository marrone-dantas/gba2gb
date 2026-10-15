"""Scripted PyBoy runner for homebrew ports (DMG mode).

Replays a button plan, measures effective frame rate (distinct frames composed
per emulated second, read from a ROM counter symbol), records screenshots, a
GIF and optional watched memory values. Contains no game content.

    python -m tools.ports.play ROM --plan plan.json --frames 3000 \
        --counter wP8Flips --shot 300:title.png --gif out.gif:1000:1600 \
        --watch room=12:0xA03C:2

plan.json: [[start_frame, "a"|"b"|"left"|..., duration_frames], ...]
"""
import argparse
import json
import os
import sys


def load_sym(rom):
    sym = {}
    path = os.path.splitext(rom)[0] + ".sym"
    for ln in open(path):
        ln = ln.split(";")[0].split()
        if len(ln) == 2 and ":" in ln[0]:
            sym[ln[1]] = int(ln[0].split(":")[1], 16)
    return sym


class Runner:
    def __init__(self, rom, counter="wP8Flips"):
        from pyboy import PyBoy
        self.pb = PyBoy(rom, window="null", cgb=False, sound_emulated=False)
        self.pb.set_emulation_speed(0)
        self.sym = load_sym(rom)
        self.counter = self.sym.get(counter)
        self.frame = 0
        self.held = {}

    def count(self):
        m = self.pb.memory
        return m[self.counter] | m[self.counter + 1] << 8

    def read(self, bank, addr, size):
        m = self.pb.memory
        v = 0
        for i in range(size):
            v |= (m[bank, addr + i] if bank is not None else m[addr + i]) << (8 * i)
        return v

    def press(self, button, dur):
        self.pb.button_press(button)
        self.held[button] = self.frame + dur

    def tick(self):
        self.frame += 1
        for b, end in list(self.held.items()):
            if self.frame >= end:
                self.pb.button_release(b)
                del self.held[b]
        self.pb.tick()


def fps_windows(samples, lo):
    """samples: [(frame, counter)] every 60 frames -> list of per-second deltas after frame lo."""
    out = []
    for (f0, c0), (f1, c1) in zip(samples, samples[1:]):
        if f0 >= lo:
            out.append((c1 - c0) & 0xFFFF)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--plan")
    ap.add_argument("--frames", type=int, default=1200)
    ap.add_argument("--counter", default="wP8Flips")
    ap.add_argument("--fps-from", type=int, default=0, help="first frame of the fps measurement")
    ap.add_argument("--shot", action="append", default=[], help="FRAME:PATH")
    ap.add_argument("--gif", help="PATH:FROM:TO (every 2nd frame)")
    ap.add_argument("--watch", action="append", default=[], help="NAME=BANK:ADDR:SIZE (BANK '-' = none)")
    a = ap.parse_args(argv)
    plan = json.load(open(a.plan)) if a.plan else []
    starts = {}
    for f, b, d in plan:
        starts.setdefault(f, []).append((b, d))
    shots = {int(s.split(":", 1)[0]): s.split(":", 1)[1] for s in a.shot}
    gif = None
    if a.gif:
        p, g0, g1 = a.gif.rsplit(":", 2)
        gif = (p, int(g0), int(g1), [])
    watches = []
    for w in a.watch:
        n, spec = w.split("=")
        bk, ad, sz = spec.split(":")
        watches.append((n, None if bk == "-" else int(bk, 0), int(ad, 0), int(sz, 0)))
    r = Runner(a.rom, a.counter)
    samples, last = [], {}
    for _ in range(a.frames):
        for b, d in starts.get(r.frame, []):
            r.press(b, d)
        r.tick()
        f = r.frame
        if f % 60 == 0:
            samples.append((f, r.count()))
        for n, bk, ad, sz in watches:
            v = r.read(bk, ad, sz)
            if last.get(n) != v:
                print(f"frame {f}: {n} = {v:#x}")
                last[n] = v
        if f in shots:
            r.pb.screen.image.save(shots[f])
        if gif and gif[1] <= f <= gif[2] and f % 2 == 0:
            gif[3].append(r.pb.screen.image.convert("P"))
    if gif and gif[3]:
        gif[3][0].save(gif[0], save_all=True, append_images=gif[3][1:], duration=33, loop=0)
    w = fps_windows(samples, a.fps_from)
    if w:
        print(f"fps over {len(w)} 1-s windows: avg {sum(w) / len(w):.1f} min {min(w)} max {max(w)}")
    r.pb.stop(save=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
