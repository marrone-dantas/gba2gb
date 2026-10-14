"""Reference model of runtime/gb_audio_shims.asm: GBA sound register writes ->
the sequence of DMG APU register writes made through SndOut (docs/audio.md has the
per-register table). Used by tests/test_audio.py against PyBoy."""

DIRECT = {0x60: (0x10, 0x7F), 0x62: (0x11, 0xFF), 0x63: (0x12, 0xFF), 0x64: (0x13, 0xFF), 0x65: (0x14, 0xC7),
          0x68: (0x16, 0xFF), 0x69: (0x17, 0xFF), 0x6C: (0x18, 0xFF), 0x6D: (0x19, 0xC7),
          0x78: (0x20, 0x3F), 0x79: (0x21, 0xFF), 0x7C: (0x22, 0xFF), 0x7D: (0x23, 0xC0), 0x84: (0x26, 0x80)}
CH3 = {0x72: 0x1B, 0x74: 0x1D, 0x75: 0x1E}


class PSGMap:
    def __init__(self):
        self.out = []
        self.s3 = 0
        self.L = self.R = self.H = self.H2 = 0
        self.dma = self.tm = self.sfx = False
        self.wave = bytearray(32)

    def _scale(self, v):
        r = self.H & 3
        v += 1
        if r == 0:
            v >>= 2
        elif r == 1:
            v >>= 1
        else:
            return v - 1
        return max(v - 1, 0)

    def nr50(self):
        self.out.append((0x24, self._scale(self.L & 7) | self._scale((self.L >> 4) & 7) << 4))

    def nr51(self):
        v = self.R
        if self.sfx:
            v &= 0xBB
            v |= (4 if self.H2 & 1 else 0) | (0x40 if self.H2 & 2 else 0)
        self.out.append((0x25, v))

    def byte(self, off, a):
        if off >= 0x90:
            bank = 0 if self.s3 & 0x40 else 1
            self.wave[16 * bank + off - 0x90] = a
        elif off in DIRECT:
            r, m = DIRECT[off]
            self.out.append((r, a & m))
        elif off == 0x70:
            ch = self.s3 ^ a
            self.s3 = a
            if not ch & 0x40 and not self.sfx:
                self.out.append((0x1A, a & 0x80))
        elif off == 0x73:
            v = 0x20 if a & 0x80 else a & 0x60
            if not self.sfx:
                self.out.append((0x1C, v))
        elif off in CH3:
            if not self.sfx:
                self.out.append((CH3[off], a & 0xC7 if off == 0x75 else a))
        elif off == 0x80:
            self.L = a
            self.nr50()
        elif off == 0x81:
            self.R = a
            self.nr51()
        elif off == 0x82:
            self.H = a
            self.nr50()
        elif off == 0x83:
            self.H2 = a
            self.nr51()

    def write(self, addr, size, value, known_sfx=True):
        off = addr - 0x04000000
        if 0x60 <= off < 0xA0:
            for i in range(size):
                self.byte(off + i, (value >> (8 * i)) & 0xFF)
        elif off in (0xC6, 0x102):
            if off == 0x102:
                self.tm = bool(value & 0x80)
            else:
                self.dma = bool(value & 0x8000)
            on = self.dma and self.tm
            if on and not self.sfx and known_sfx:
                self.sfx = True
                self.nr51()
            elif not on and self.sfx:
                self.sfx = False
                self.nr51()

    def sfx_end(self):
        """the stream ran out of chunks before the program stopped it"""
        if self.sfx:
            self.sfx = False
            self.nr51()
