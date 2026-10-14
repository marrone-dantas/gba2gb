"""Phase 5 B4: long bot run of the transpiled Snek on the DMG (PyBoy, cgb=False) and
state comparison against the original GBA build in Unicorn.

GB side: a greedy bot steers the snake toward the frog (reading g_state from the ARM
RAM window), restarts from DEATH / TITLE with START, and logs, in program order,
every value the GB build hands to the game for KEYINPUT, TM0D and TM1D, plus a
g_state snapshot at every KEYINPUT read. It also counts lag frames (GB frames in
which no compose ran), crashes (PC outside ROM/WRAM-free code, stack outside
$D800-$DFFF) and the native stack low-water mark.

Unicorn side: the real Thumb build runs with those exact KEYINPUT / timer values
replayed in the same order (the game has no other inputs), and g_state is compared
at every KEYINPUT read. Matching sequences mean the GB build computed the same game
state (positions, floats, score, rand-driven frog, pointers) as the GBA code.

python -m tools.slice.snek_bot [FRAMES]  (default 36000)"""
from __future__ import annotations
import hashlib
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ELF = os.path.join(ROOT, "build", "snek", "snek.elf")
GB = os.path.join(ROOT, "build", "snek", "snek_dmg.gb")
GSTATE, GSIZE = 0x03000328, 0x368
WIN = 0xC000 | (GSTATE & 0xFFF)          # HAL ARM RAM window on the GB
KEY = {"a": 0, "b": 1, "select": 2, "start": 3, "right": 4, "left": 5, "up": 6, "down": 7}
ROOM = {0x0200: "title", 0x0202: "game", 0x0301: "dead"}


PRUNE = "sound"   # narrowed backend: flag liveness + proven value ranges (docs/bitwidth_pruning.md)


def build_gb(out=GB, prune=PRUNE):
    from tools.slice import snek_ref
    from tools.backend.gba2gbc_core import build
    snek_ref.build()
    build(ELF, out, entry="main", hal=True, prune=prune)
    return out


def load_sym(path):
    sy = {}
    for ln in open(path):
        ln = ln.split(";")[0].strip()
        if ln:
            a, n = ln.split()
            b, o = a.split(":")
            sy[n] = (int(b, 16), int(o, 16))
    return sy


def u32(b, o):
    return int.from_bytes(b[o:o + 4], "little")


def s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def fbits(v):
    import struct
    return struct.unpack("<f", struct.pack("<I", v))[0]


def state_fields(g):
    """g_state bytes -> the fields the bot needs (see third_party/snek-gba/include/game.h)."""
    o = 4 + 8
    tx, ty = s32(u32(g, o)), s32(u32(g, o + 4))
    d = s32(u32(g, o + 20))
    nb = s32(u32(g, o + 24))
    bx0 = o + 32 + 4 * 64
    bodies = [(fbits(u32(g, bx0 + 4 * i)), fbits(u32(g, bx0 + 256 + 4 * i))) for i in range(1, nb + 1)]
    fo = bx0 + 512 + 4
    return {"tx": tx, "ty": ty, "dir": d, "nb": nb, "bodies": bodies,
            "fx": s32(u32(g, fo)), "fy": s32(u32(g, fo + 4)), "score": u32(g, fo + 12)}


class Bot:
    """Greedy: move toward the frog; never reverse; avoid walls and the body."""
    DIRS = {0: (8, 0, "right"), 1: (0, 8, "down"), 2: (-8, 0, "left"), 3: (0, -8, "up")}

    def __init__(self):
        self.hold, self.cool = 0, 0

    def choose(self, room, st, frame):
        if room in ("title", "dead"):
            # press START for 4 frames, then release for 40 (game waits for release)
            ph = frame % 44
            return ["start"] if ph < 4 else []
        if room != "game":
            return []
        occ = {(int(x), int(y)) for x, y in st["bodies"]}
        best = None
        for d, (dx, dy, name) in self.DIRS.items():
            if (d + 2) % 4 == st["dir"]:
                continue
            nx, ny = st["tx"] + dx, st["ty"] + dy
            if nx <= 0 or nx >= 232 or ny <= 0 or ny >= 152 or (nx, ny) in occ:
                continue
            dist = abs(st["fx"] - nx) + abs(st["fy"] - ny) + (0 if d == st["dir"] else 1)
            if best is None or dist < best[0]:
                best = (dist, name)
        return [best[1]] if best else []


def run_gb(frames, gb=GB, gif_frames=(), shots=(), log=print):
    from pyboy import PyBoy
    sy = load_sym(os.path.splitext(gb)[0] + ".sym")
    pb = PyBoy(gb, window="null", cgb=False, sound_emulated=False)
    pb.set_emulation_speed(0)
    m = pb.memory
    rf = pb.register_file
    keys, timers, snaps = [], [], []
    tm_pending = []

    def on_key(_):
        snaps.append(bytes(m[WIN:WIN + GSIZE]))

    def on_key_end(_):
        keys.append(m[sy["wKeys"][1]] | (m[sy["wKeys"][1] + 1] << 8))

    def on_tm(_):
        timers.append(rf.D << 8 | rf.E)

    pb.hook_register(0, sy["HAL_KEYINPUT"][1], on_key, None)
    pb.hook_register(0, sy["HAL_KEYINPUT_END"][1], on_key_end, None)
    pb.hook_register(0, sy["TmOut"][1], on_tm, None)
    cn = lambda: m[sy["wComposeN"][1]] | (m[sy["wComposeN"][1] + 1] << 8)
    bot = Bot()
    held = set()
    stats = {"frames": 0, "lag": 0, "lag_by_room": {}, "frames_by_room": {}, "crashes": [],
             "sp_min": 0xE000, "deaths": 0, "max_score": 0, "games": 0}
    gif, shot_imgs = [], {}
    last_c, prev_room, booted = cn(), None, False
    t0 = time.time()
    for f in range(frames):
        bg1 = m[sy["wBg1Cnt"][1]] | (m[sy["wBg1Cnt"][1] + 1] << 8)
        room = ROOM.get(bg1, "title")
        st = state_fields(bytes(m[WIN:WIN + GSIZE]))
        want = set(bot.choose(room, st, f))
        for k in held - want:
            pb.button_release(k)
        for k in want - held:
            pb.button_press(k)
        held = want
        render = f in gif_frames or f in shots
        pb.tick(1, render)
        if render:
            im = pb.screen.image.convert("RGB")
            if f in gif_frames:
                gif.append(im)
            if f in shots:
                shot_imgs[f] = (im, len(keys))
        c = cn()
        lagged = c == last_c
        last_c = c
        stats["frames"] += 1
        stats["lag"] += lagged
        stats["frames_by_room"][room] = stats["frames_by_room"].get(room, 0) + 1
        stats["lag_by_room"][room] = stats["lag_by_room"].get(room, 0) + lagged
        sp, pc = rf.SP, rf.PC
        booted = booted or len(keys) > 0          # runtime init done (SP moved to $E000)
        if booted:
            stats["sp_min"] = min(stats["sp_min"], sp)
        if booted and not (0xD800 <= sp <= 0xE000) or pc >= 0x8000:   # stack overflow / code outside ROM
            stats["crashes"].append((f, pc, sp))
            if len(stats["crashes"]) > 5:
                log(f"aborting: crash at frame {f} PC={pc:04X} SP={sp:04X}")
                break
        if room == "dead" and prev_room == "game":
            stats["deaths"] += 1
        if room == "game" and prev_room != "game":
            stats["games"] += 1
        if room == "game":
            stats["max_score"] = max(stats["max_score"], st["score"])
        prev_room = room
        if f % 6000 == 0:
            log(f"  frame {f}: room={room} keyreads={len(keys)} timers={len(timers)} "
                f"score={st['score']} t={time.time() - t0:.0f}s")
    pb.stop()
    stats["keyreads"], stats["timer_reads"] = len(keys), len(timers)
    stats["wall_s"] = time.time() - t0
    return {"keys": keys, "timers": timers, "snaps": snaps, "stats": stats, "gif": gif, "shots": shot_imgs}


class Replay:
    """Unicorn GBA reference fed with the GB-read KEYINPUT / TM0D / TM1D sequences."""

    def __init__(self, elf, keys, timers):
        from tools.hal.gba_ref import GBARef
        from unicorn import UC_HOOK_MEM_READ
        self.ref = GBARef(elf)
        self.uc = self.ref.uc
        self.keys, self.timers = keys, timers
        self.ki = self.ti = 0
        self.snaps, self.mismatch_timer = [], 0
        self.vis = {}
        self.uc.hook_add(UC_HOOK_MEM_READ, self._rd, begin=0x04000100, end=0x04000131)

    def want_visual(self, idxs):
        self.vis = {i: None for i in idxs}

    def _rd(self, uc, access, addr, size, value, ud):
        if addr == 0x04000130:
            if self.ki in self.vis:
                self.vis[self.ki] = self.ref.snapshot()
            self.snaps.append(bytes(uc.mem_read(GSTATE, GSIZE)))
            if self.ki >= len(self.keys):
                uc.emu_stop()
                return
            uc.mem_write(0x04000130, self.keys[self.ki].to_bytes(2, "little"))
            self.ki += 1
        elif addr in (0x04000100, 0x04000104):
            v = self.timers[self.ti] if self.ti < len(self.timers) else 0
            if self.ti >= len(self.timers):
                self.mismatch_timer += 1
            uc.mem_write(addr, v.to_bytes(2, "little"))
            self.ti += 1

    def run(self):
        from unicorn import arm_const as U
        self.ref.inputs, self.ref.nframes = [], 1 << 30
        self.uc.reg_write(U.UC_ARM_REG_SP, 0x03000F00)
        self.uc.emu_start(self.ref.entry, 0x0FFFFFFF, count=0)
        return self.snaps


def compare(gb_snaps, ref_snaps):
    n = min(len(gb_snaps), len(ref_snaps))
    first = None
    match = 0
    for i in range(n):
        if gb_snaps[i] == ref_snaps[i]:
            match += 1
        elif first is None:
            a, b = gb_snaps[i], ref_snaps[i]
            diff = [o for o in range(GSIZE) if a[o] != b[o]]
            first = (i, diff[:16])
    h = lambda ss: hashlib.sha256(b"".join(ss[:n])).hexdigest()[:16]
    return {"compared": n, "match": match, "first_mismatch": first,
            "gb_hash": h(gb_snaps), "ref_hash": h(ref_snaps)}


def main(frames=36000):
    from PIL import Image
    from tools.hal.gba_ref import render
    build_gb()
    gif_frames = set(range(400, 1600, 4))
    shots = {120: "title", 700: "game_a", 1500: "game_b"}
    r = run_gb(frames, gif_frames=gif_frames, shots=set(shots))
    st = r["stats"]
    print("GB run:", {k: v for k, v in st.items() if k != "crashes"}, "crashes:", st["crashes"][:5])
    rep = Replay(ELF, r["keys"], r["timers"])
    rep.want_visual([r["shots"][f][1] for f in shots if f in r["shots"]])
    t0 = time.time()
    ref = rep.run()
    cmp = compare(r["snaps"], ref)
    print(f"Unicorn replay ({time.time() - t0:.0f}s): keyreads={rep.ki} timer_reads={rep.ti} "
          f"timer_underflow={rep.mismatch_timer}", cmp)
    img = os.path.join(ROOT, "docs", "img")
    if r["gif"]:
        g = [im.resize((320, 288), Image.NEAREST) for im in r["gif"]]
        g[0].save(os.path.join(img, "snek_dmg.gif"), save_all=True, append_images=g[1:], duration=67, loop=0)
    # side-by-side: GBA (Unicorn, same KEYINPUT read index) | DMG
    rows = []
    for f, name in shots.items():
        if f not in r["shots"]:
            continue
        dmg, ki = r["shots"][f]
        snap = rep.vis.get(ki)
        gba = render(snap) if snap else Image.new("RGB", (240, 160))
        row = Image.new("RGB", (480 + 320, 320), (40, 40, 40))
        row.paste(gba.resize((480, 320), Image.NEAREST), (0, 0))
        row.paste(dmg.resize((320, 288), Image.NEAREST), (480, 16))
        rows.append(row)
    if rows:
        sbs = Image.new("RGB", (800, 320 * len(rows)))
        for i, rw in enumerate(rows):
            sbs.paste(rw, (0, 320 * i))
        sbs.save(os.path.join(img, "snek_side_by_side.png"))
    return st, cmp, rep


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 36000)
