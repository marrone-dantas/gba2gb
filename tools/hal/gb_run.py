"""PyBoy (DMG mode, cgb=False) runner for HAL programs: frame stepping with the
GB joypad, OAM/VRAM snapshots, a strict VRAM/OAM access checker and shim cycle
measurements. Symbols come from the rgblink .sym file written by build()."""
from __future__ import annotations
from pyboy import PyBoy

GB_BUTTONS = {"a": "a", "b": "b", "select": "select", "start": "start", "right": "right",
              "left": "left", "up": "up", "down": "down"}
WRITE_SITES = ("HAL_VRAM_STORE16.wrmap", "HAL_VRAM_STORE16.wrlo", "HAL_VRAM_STORE16.wrhi",
               "MemClear.clr", "VBlankISR.dma")


def read_sym(path):
    sym = {}
    for line in open(path):
        line = line.split(";")[0].strip()
        if not line:
            continue
        loc, name = line.split()
        bank, addr = loc.split(":")
        sym[name] = (int(bank, 16), int(addr, 16))
    return sym


class GBRun:
    def __init__(self, rom, check_access=True, measure=()):
        self.pb = PyBoy(rom, window="null", cgb=False, sound_emulated=False)
        self.pb.set_emulation_speed(0)
        self.m = self.pb.memory
        self.sym = read_sym(rom[:-4] + ".sym")
        self.violations, self.writes = [], {s: 0 for s in WRITE_SITES}
        self.pressed = set()
        if check_access:
            for s in WRITE_SITES:
                b, a = self.sym[s]
                self.pb.hook_register(b, a, self._check, s)
        self.cycles = {}
        for name in measure:  # (entry label, exit label of the final `ret`)
            entry, end = name
            b, a = self.sym[entry]
            self.pb.hook_register(b, a, self._t0, entry)
            b, a = self.sym[end]
            self.pb.hook_register(b, a - 1, self._t1, entry)  # the `ret` just before END
        self._start = {}

    def _check(self, site):
        lcdc, stat, ly = self.m[0xFF40], self.m[0xFF41], self.m[0xFF44]
        self.writes[site] += 1
        if not lcdc & 0x80:
            return
        mode = stat & 3
        ok = (ly >= 144) if site == "VBlankISR.dma" else mode in (0, 1)
        if not ok:
            self.violations.append((site, ly, mode, self.frame()))

    def _t0(self, name):
        self._start[name] = self.pb._cycles()

    def _t1(self, name):
        if name in self._start:
            self.cycles.setdefault(name, []).append(self.pb._cycles() - self._start.pop(name))

    def var16(self, name):
        a = self.sym[name][1]
        return self.m[a] | (self.m[a + 1] << 8)

    def frame(self):
        """GBA frame number = completed vsyncs (HAL wVsync)."""
        return self.var16("wVsync")

    def vblanks(self):
        return self.var16("wFrame")

    def keys(self):
        return self.var16("wKeys")

    def set_buttons(self, keys):
        keys = {k for k in keys if k in GB_BUTTONS}
        for k in self.pressed - keys:
            self.pb.button_release(GB_BUTTONS[k])
        for k in keys - self.pressed:
            self.pb.button_press(GB_BUTTONS[k])
        self.pressed = keys

    def tick(self, render=False):
        self.pb.tick(1, render)

    def oam(self):
        return bytes(self.m[0xFE00 + i] for i in range(160))

    def vram(self):
        return bytes(self.m[0x8000 + i] for i in range(0x2000))

    def screenshot(self, path):
        self.pb.tick(1, True)
        self.pb.screen.image.convert("RGB").save(path)

    def stop(self):
        self.pb.stop()
