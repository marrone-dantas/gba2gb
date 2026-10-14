"""Phase 4.3: DirectSound SFX -> DMG wave-channel chunks (docs/audio.md).

A GBA program plays 8-bit signed PCM through FIFO A (DMA1 + timer 0). The DMG has
no PCM channel, so each SFX is converted offline: resampled to 8192 Hz, quantised to
4 bits (unsigned, 8 = silence), packed two samples per byte (high nibble first, as in
both wave RAMs) into 32-sample / 16-byte chunks. At run time the HAL timer interrupt
(256 Hz = 8192 / 32) loads one chunk into wave RAM and retriggers channel 3.

Which data is an SFX is found like the affine baker finds sprites: a GBA reference
run (Unicorn) logs every DMA1SAD value and the TM0CNT_L reload; the length comes from
the ELF symbol that contains the address."""
from __future__ import annotations
import numpy as np
from elftools.elf.elffile import ELFFile

FS_GB = 8192
BANK0 = 16
GBA_CLOCK = 16777216


def stub_asm():
    return 'SECTION "sfx_stub", ROM0\nSfxCount:: db 0\nSfxTab::\n'


def symbol_at(elf, addr):
    with open(elf, "rb") as fh:
        e = ELFFile(fh)
        st = e.get_section_by_name(".symtab")
        for s in st.iter_symbols():
            if s["st_info"]["type"] == "STT_OBJECT" and s["st_value"] <= addr < s["st_value"] + s["st_size"]:
                return s.name, s["st_value"], s["st_size"]
        for seg in e.iter_segments():
            pass
    return None


def rom_bytes(elf, addr, size):
    with open(elf, "rb") as fh:
        e = ELFFile(fh)
        for seg in e.iter_segments():
            if seg["p_type"] == "PT_LOAD" and seg["p_paddr"] <= addr < seg["p_paddr"] + seg["p_filesz"]:
                o = addr - seg["p_paddr"]
                return seg.data()[o:o + size]
    raise ValueError(f"{addr:#x} not in a loadable segment")


def to_chunks(pcm8, fs):
    """int8 PCM at fs -> (bytes of 16-byte chunks, the 4-bit samples at 8192 Hz)."""
    x = np.asarray(pcm8, np.int8).astype(np.float64)
    n = int(round(len(x) * FS_GB / fs))
    t = np.arange(n) * fs / FS_GB
    y = np.interp(t, np.arange(len(x)), x)
    q = np.clip(np.round((y + 128) / 16.0 - 0.5), 0, 15).astype(np.uint8)   # 4-bit, 7.5 = silence
    q = np.concatenate([q, np.full((-len(q)) % 32, 8, np.uint8)])
    packed = bytes((q[0::2] << 4 | q[1::2]).astype(np.uint8))
    return packed, q


def convert_program(elf, writes):
    """writes: GBA reference log (frame, addr, size, value). -> (asm, report)."""
    srcs, reload = [], None
    for _, a, sz, v in writes:
        if a == 0x040000BC and sz == 4 and v not in srcs:
            srcs.append(v)
        if a == 0x04000100:
            reload = v
    if not srcs:
        return stub_asm(), {"sfx": []}
    fs = GBA_CLOCK / (65536 - reload) if reload else FS_GB
    L = ['SECTION "sfx_tab", ROM0', f"SfxCount:: db {len(srcs)}", "SfxTab::"]
    data, rep, bank, off = [], [], BANK0, 0
    for src in srcs:
        sym = symbol_at(elf, src)
        if not sym:
            raise ValueError(f"DMA1SAD {src:#x}: no ELF object symbol (length unknown)")
        name, base, size = sym
        pcm = rom_bytes(elf, src, base + size - src)
        packed, q = to_chunks(np.frombuffer(pcm, np.int8), fs)
        if off + len(packed) > 16384:
            bank, off = bank + 1, 0
        if len(packed) > 16384:
            raise ValueError(f"SFX {name} longer than one bank")
        L.append(f"    db {', '.join(f'${b:02X}' for b in src.to_bytes(4, 'little'))}, {bank}, "
                 f"LOW(${0x4000 + off:04X}), HIGH(${0x4000 + off:04X}), {len(packed) // 16 & 255}, {len(packed) // 16 >> 8}")
        data.append((bank, off, packed))
        rep.append({"symbol": name, "addr": f"{src:#x}", "bytes": len(pcm), "fs_in": round(fs, 1),
                    "chunks": len(packed) // 16, "bank": bank, "_q": q})
        off += len(packed)
    for b in sorted({d[0] for d in data}):
        L.append(f'SECTION "sfx_bank_{b}", ROMX[$4000], BANK[{b}]')
        blob = bytearray()
        for bb, o, p in data:
            if bb == b:
                blob += p
        L += ["    db " + ", ".join(f"${x:02X}" for x in blob[i:i + 32]) for i in range(0, len(blob), 32)]
    return "\n".join(L) + "\n", {"sfx": rep, "fs_out": FS_GB}
