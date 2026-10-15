"""Generic audio subsystem removal (docs/audio.md, "Audio off").

The DMG port of a GBA program can drop its sound work entirely: the mixer, the
music/SFX sequencer and the sound interrupt are pure overhead when the lifted code
runs 10-30x slower than the original CPU. `detect(elf)` finds the audio functions of
any GBA ELF (no game knowledge) so the build can replace every BL to them with an
empty native (`NAT_audio_nop`, runtime/gb_hal_shims.asm); the HAL then also ignores
sound / FIFO-DMA register writes and skips the DirectSound conversion.

Detection, each rule reporting why a function was selected:
  * name   - known sound libraries by symbol: maxmod (`mm*`, `mpp_*`, `mmVBlank`),
             m4a / Sappy (`m4a*`, `MPlay*`, `SoundMain`, `SoundVSync*`, `ply_*`,
             `CgbSound`, ...), Krawall (`kram*`, `krap*`), AAS (`AAS_*`), plus the
             usual game-level entry points (`sfx`, `music`, `play_sound`, ...).
  * regs   - signature: the function's literal pool references sound registers
             0x04000060-0x040000A8 (PSG, SOUNDCNT, wave RAM, FIFO A/B) and no display,
             keypad or system register (so a generic init that also clears the APU
             is kept);
  * wrapper - transitive: every BL of the function goes to audio functions, at least
             one of them, and the function stores nothing to memory except its own stack
             frame (e.g. `void psfx(n) { if (!timer) sfx(n); }`).
Stubbed functions are assumed to return nothing (an audio call's result, if any,
reads as the caller's r0)."""
from __future__ import annotations
import re
import capstone as cs
from elftools.elf.elffile import ELFFile

NAME_RES = [r"mm[A-Z]\w*", r"_?mm_\w+", r"mpp_\w+", r"mmVBlank", r"mmFrame",
            r"m4a\w+", r"MPlay\w+", r"SoundMain\w*", r"SoundVSync\w*", r"SoundInit\w*",
            r"ply_\w+", r"CgbSound\w*", r"CgbModVol", r"MidiKey2\w+", r"SampleFreqSet",
            r"TrackStop", r"FadeOutBody", r"TrkVolPitSet", r"ClearChain", r"MPlayJumpTable\w*",
            r"kra[mp]\w+", r"AAS_\w+",
            r"sfx", r"music", r"sound", r"play_(?:sound|sfx|music|song)", r"stop_(?:sound|sfx|music)"]
NAME_RE = re.compile("|".join(f"(?:{r})" for r in NAME_RES))
SND_LO, SND_HI = 0x04000060, 0x040000A8
# non-audio I/O: display (0x000-0x05F), keypad (0x130-0x132), waitstate / power (0x204, 0x300)
NON_AUDIO_IO = [(0x04000000, 0x04000060), (0x04000130, 0x04000134), (0x04000204, 0x04000206),
                (0x04000300, 0x04000302)]


def demangle_base(name):
    """`_Z3sfxh` -> `sfx`, `_ZL4psfxh` -> `psfx`; plain C names unchanged."""
    m = re.match(r"_ZL?(\d+)", name)
    if m:
        n = int(m.group(1))
        return name[m.end():m.end() + n]
    return name


def _funcs(elf_path):
    with open(elf_path, "rb") as fh:
        e = ELFFile(fh)
        st = e.get_section_by_name(".symtab")
        segs = [(s["p_vaddr"], s.data()) for s in e.iter_segments() if s["p_type"] == "PT_LOAD"]
        out = {}
        for s in st.iter_symbols():
            if s["st_info"]["type"] == "STT_FUNC" and s["st_size"] and s.name:
                a = s["st_value"]
                lo = a & ~1
                for base, d in segs:
                    if base <= lo < base + len(d):
                        out[s.name] = (lo, bool(a & 1), d[lo - base:lo - base + s["st_size"]])
                        break
    return out


def _scan(addr, thumb, code):
    """(literal words, BL targets, stores other than to sp) of one function."""
    md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB if thumb else cs.CS_MODE_ARM)
    ins = list(md.disasm(code, addr))
    lits = set()                    # literal pool words (decoded as data, not code)
    for x in ins:
        m = re.match(r"\w+, \[pc, #(-?0x[0-9a-f]+|-?\d+)\]", x.op_str)
        if x.mnemonic.startswith("ldr") and m:
            t = ((x.address + 4) & ~3 if thumb else x.address + 8) + int(m.group(1), 0)
            lits.update((t, t + 2))
    words = [int.from_bytes(code[t - addr:t - addr + 4], "little") for t in sorted(lits)
             if t % 4 == 0 and addr <= t <= addr + len(code) - 4]
    bls, stores = set(), 0
    for x in ins:
        if x.address in lits:
            continue
        if x.mnemonic in ("bl", "blx") and x.op_str.startswith("#"):
            bls.add(int(x.op_str[1:], 16))
        elif x.mnemonic.startswith("str") and not re.search(r"\[sp\b", x.op_str):
            stores += 1
        elif x.mnemonic.startswith("stm") and not x.op_str.startswith("sp"):
            stores += 1
    return words, bls, stores


def detect(elf_path, entry="main"):
    """{symbol name: reason} of the audio functions to stub."""
    funcs = _funcs(elf_path)
    by_addr = {lo: n for n, (lo, _, _) in funcs.items()}
    info = {n: _scan(lo, t, c) for n, (lo, t, c) in funcs.items()}
    out = {}
    for n in funcs:
        if n == entry:
            continue
        if NAME_RE.fullmatch(demangle_base(n)):
            out[n] = "name"
            continue
        words = info[n][0]
        if any(SND_LO <= w <= SND_HI + 3 for w in words) and \
                not any(lo <= w < hi for w in words for lo, hi in NON_AUDIO_IO):
            out[n] = "regs"
    changed = True
    while changed:
        changed = False
        for n, (words, bls, stores) in info.items():
            if n in out or n == entry or not bls or stores:
                continue
            tg = [by_addr.get(b) for b in bls]
            if all(t in out for t in tg):
                out[n] = "wrapper"
                changed = True
    return out


def overrides(elf_path, entry="main"):
    """EXTRA_NATIVES entries: every detected function -> the empty native."""
    return {n: "audio_nop" for n in detect(elf_path, entry)}
