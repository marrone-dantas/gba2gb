"""GBA reference for the Phase 2 demos: Unicorn runs the real GBA build (ARM crt0 +
Thumb main) with simulated KEYINPUT / VCOUNT / VBlankIntrWait, and a small renderer
(mode 0 BG0 4bpp regular + regular sprites) produces reference screenshots.

Frame model: frame k starts at the k-th vsync return (VCOUNT crossing 160, or the
k-th `swi 5`). At that moment OAM/VRAM/PAL/IO are snapshotted (state produced by
frame k-1); KEYINPUT reads during frame k return the keys of inputs[k]."""
from __future__ import annotations
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_MEM_READ, UC_HOOK_INTR
from unicorn import arm_const as U

GBA_KEYS = ["a", "b", "select", "start", "right", "left", "up", "down", "r", "l"]


def keymask(keys):
    return sum(1 << GBA_KEYS.index(k) for k in keys)


class GBARef:
    def __init__(self, elf):
        uc = self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for base, size in ((0x08000000, 0x40000), (0x02000000, 0x40000), (0x03000000, 0x8000),
                           (0x04000000, 0x1000), (0x05000000, 0x1000), (0x06000000, 0x18000),
                           (0x07000000, 0x1000)):
            uc.mem_map(base, size)
        with open(elf, "rb") as fh:
            e = ELFFile(fh)
            for seg in e.iter_segments():
                if seg["p_type"] == "PT_LOAD" and seg["p_filesz"]:
                    uc.mem_write(seg["p_paddr"], seg.data())
            self.entry = e.header["e_entry"]
        self.frame, self.vline, self.inputs, self.snaps = 0, 0, [], []
        uc.hook_add(UC_HOOK_MEM_READ, self._io_read, begin=0x04000000, end=0x040003FF)
        uc.hook_add(UC_HOOK_INTR, self._intr)

    def _boundary(self):
        self.frame += 1
        self.snaps.append(self.snapshot())
        if self.frame >= self.nframes:
            self.uc.emu_stop()

    def keys_now(self):
        k = self.inputs[self.frame] if self.frame < len(self.inputs) else 0
        return (~k) & 0x3FF

    def _io_read(self, uc, access, addr, size, value, ud):
        if addr in (0x04000130, 0x04000131):
            uc.mem_write(0x04000130, self.keys_now().to_bytes(2, "little"))
        if addr in (0x04000006, 0x04000007):
            prev = self.vline
            self.vline = (self.vline + 16) % 228
            if prev < 160 <= self.vline:
                self._boundary()
            uc.mem_write(0x04000006, self.vline.to_bytes(2, "little"))

    def _intr(self, uc, intno, ud):
        if intno == 2:  # SVC: only VBlankIntrWait is used by the demos
            self.vline = 160
            self._boundary()

    def snapshot(self):
        m = self.uc.mem_read
        return {"frame": self.frame, "oam": bytes(m(0x07000000, 0x400)), "pal": bytes(m(0x05000000, 0x400)),
                "vram": bytes(m(0x06000000, 0x18000)), "io": bytes(m(0x04000000, 0x400))}

    def run(self, inputs, nframes):
        """inputs[k] = GBA key mask (1 = pressed) during frame k. Returns snapshots
        of frames 1..nframes (index 0 = frame 1)."""
        self.inputs, self.nframes = inputs, nframes
        self.uc.reg_write(U.UC_ARM_REG_SP, 0x03000F00)
        self.uc.emu_start(self.entry, 0x0FFFFFFF, count=200_000_000)
        return self.snaps


# ---------------------------------------------------------------- renderer
OBJ_SIZES = {(0, 0): (8, 8), (0, 1): (16, 16), (0, 2): (32, 32), (0, 3): (64, 64),
             (1, 0): (16, 8), (1, 1): (32, 8), (1, 2): (32, 16), (1, 3): (64, 32),
             (2, 0): (8, 16), (2, 1): (8, 32), (2, 2): (16, 32), (2, 3): (32, 64)}


def u16(b, o):
    return b[o] | (b[o + 1] << 8)


def bgr(c):
    return ((c & 31) * 255 // 31, ((c >> 5) & 31) * 255 // 31, ((c >> 10) & 31) * 255 // 31)


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def obj_pixels(vram, tile, w, h, oned=True):
    """4bpp OBJ tiles -> rows of colour indices."""
    out = []
    for ty in range(h):
        row = []
        for tx in range(w):
            t = tile + (ty // 8) * ((w // 8) if oned else 32) + tx // 8
            b = vram[0x10000 + (t & 0x3FF) * 32 + (ty & 7) * 4 + (tx & 7) // 2]
            row.append((b >> (4 * (tx & 1))) & 15)
        out.append(row)
    return out


def affine_sample(src, w, h, P, xx, yy):
    """GBA affine OBJ sampling (non-double box): texture = P * (screen - centre) + centre."""
    pa, pb, pc, pd = P
    dx, dy = xx - w // 2, yy - h // 2
    tx = ((pa * dx + pb * dy) >> 8) + w // 2
    ty = ((pc * dx + pd * dy) >> 8) + h // 2
    if 0 <= tx < w and 0 <= ty < h:
        return src[ty][tx]
    return 0


def render(s):
    from PIL import Image
    io, pal, vram, oam = s["io"], s["pal"], s["vram"], s["oam"]
    img = Image.new("RGB", (240, 160), bgr(u16(pal, 0)))
    pix = img.load()
    dcnt = u16(io, 0)
    if dcnt & 0x100:
        cnt = u16(io, 8)
        cbb, sbb = (cnt >> 2) & 3, (cnt >> 8) & 31
        hofs, vofs = u16(io, 0x10) & 511, u16(io, 0x12) & 511
        for y in range(160):
            for x in range(240):
                mx, my = (x + hofs) & 255, (y + vofs) & 255
                se = u16(vram, sbb * 0x800 + 2 * ((my // 8) * 32 + mx // 8))
                t, px, py = se & 0x3FF, mx & 7, my & 7
                if se & 0x400:
                    px = 7 - px
                if se & 0x800:
                    py = 7 - py
                b = vram[cbb * 0x4000 + t * 32 + py * 4 + px // 2]
                ci = (b >> (4 * (px & 1))) & 15
                if ci:
                    pix[x, y] = bgr(u16(pal, 2 * (((se >> 12) << 4) | ci)))
    if dcnt & 0x1000:
        oned = bool(dcnt & 0x40)
        for i in reversed(range(128)):
            a0, a1, a2 = u16(oam, 8 * i), u16(oam, 8 * i + 2), u16(oam, 8 * i + 4)
            if (a0 & 0x300) == 0x200:
                continue
            w, h = OBJ_SIZES.get((a0 >> 14, a1 >> 14), (8, 8))
            y0, x0 = a0 & 255, a1 & 511
            tile, pb = a2 & 0x3FF, a2 >> 12
            if a0 & 0x100:          # affine (non-double-size box)
                g = (a1 >> 9) & 31
                P = [s16(u16(oam, 32 * g + 6 + 8 * j)) for j in range(4)]
                src = obj_pixels(vram, tile, w, h, oned)
                for yy in range(h):
                    for xx in range(w):
                        sx, sy = (x0 + xx) & 511, (y0 + yy) & 255
                        ci = affine_sample(src, w, h, P, xx, yy)
                        if ci and sx < 240 and sy < 160:
                            pix[sx, sy] = bgr(u16(pal, 0x200 + 2 * (pb * 16 + ci)))
                continue
            for yy in range(h):
                for xx in range(w):
                    sx, sy = (x0 + xx) & 511, (y0 + yy) & 255
                    if sx >= 240 or sy >= 160:
                        continue
                    tx, ty = (w - 1 - xx if a1 & 0x1000 else xx), (h - 1 - yy if a1 & 0x2000 else yy)
                    t = tile + (ty // 8) * ((w // 8) if oned else 32) + tx // 8
                    b = vram[0x10000 + (t & 0x3FF) * 32 + (ty & 7) * 4 + (tx & 7) // 2]
                    ci = (b >> (4 * (tx & 1))) & 15
                    if ci:
                        pix[sx, sy] = bgr(u16(pal, 0x200 + 2 * (pb * 16 + ci)))
    return img
