"""Array caps: iterate only over the first K elements of a global array (e.g. a
particle pool), a generic quality/speed knob (docs/homebrew_port.md, "Array caps").

`cap_elf(elf, out, {"particles": 8})` writes a patched copy of the ELF. For every
Thumb function whose literal pool references the array, the loop bounds are found
and lowered:
  * pointer loops: a literal equal to the array end (base + size) whose loaded value
    is only compared (or spilled to the stack and compared after reloading) becomes
    base + K * elem;
  * index loops: `cmp rN, #count` becomes `cmp rN, #K`.
The element size is the most common pointer stride (`adds rP, #elem`) dividing the
array size in those functions, or `{"name": (K, elem)}`. Every patch is reported;
a use that is not provably a bound (e.g. the end address used as a pointer) is left
alone and reported as skipped.
"""
from __future__ import annotations
import collections
import re
import shutil
import capstone as cs
from elftools.elf.elffile import ELFFile


def _load(elf):
    with open(elf, "rb") as fh:
        e = ELFFile(fh)
        syms = {s.name: s for s in e.get_section_by_name(".symtab").iter_symbols()}
        text = e.get_section_by_name(".text")
        funcs = [(s["st_value"] & ~1, s["st_size"], s.name) for s in syms.values()
                 if s["st_info"]["type"] == "STT_FUNC" and s["st_value"] & 1 and s["st_size"]]
        return ({n: (s["st_value"], s["st_size"]) for n, s in syms.items()}, funcs,
                text["sh_addr"], text["sh_offset"], bytearray(text.data()))


def _analyse(code, lo, base, size):
    md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB)
    ins = list(md.disasm(bytes(code), lo))
    lits = {}
    for x in ins:
        m = re.match(r"(r\d+), \[pc, #(0x[0-9a-f]+|\d+)\]", x.op_str)
        if x.mnemonic == "ldr" and m:
            t = ((x.address + 4) & ~3) + int(m.group(2), 0)
            if lo <= t < lo + len(code) - 3:
                lits[x.address] = (m.group(1), t, int.from_bytes(code[t - lo:t - lo + 4], "little"))
    refs = any(base <= v < base + size for _, _, v in lits.values())
    strides = collections.Counter(int(m.group(1), 0) for x in ins if x.mnemonic == "adds"
                                  for m in [re.fullmatch(r"r\d+, #(0x[0-9a-f]+|\d+)", x.op_str)] if m)
    return ins, lits, refs, strides


def _only_compared(ins, start, reg):
    """True if, after `start`, reg (and stack spills of it) is only used by cmp."""
    live, slots = {reg}, set()
    for x in ins:
        if x.address <= start:
            continue
        ops = [o.strip() for o in x.op_str.replace("[", "").replace("]", "").split(",")]
        m = re.fullmatch(r"(r\d+), \[sp, #(0x[0-9a-f]+|\d+)\]", x.op_str)
        if x.mnemonic == "str" and m and m.group(1) in live:
            slots.add(int(m.group(2), 0))
            continue
        if x.mnemonic == "ldr" and m and int(m.group(2), 0) in slots:
            live.add(m.group(1))
            continue
        if x.mnemonic in ("pop", "bx") or (x.mnemonic == "b" and not x.op_str.startswith("#")):
            return True
        used = [r for r in ops if r in live]
        if not used:
            continue
        if x.mnemonic == "cmp":
            return True                   # the loop bound (latch compare)
        if ops and ops[0] in live and x.mnemonic not in ("str", "strh", "strb", "cmp") and \
                not any(r in live for r in ops[1:]):
            live.discard(ops[0])          # redefined
            continue
        return False
    return True


def cap_elf(elf, out, caps):
    syms, funcs, taddr, toff, text = _load(elf)
    report = []
    for name, spec in caps.items():
        keep, elem = spec if isinstance(spec, tuple) else (spec, None)
        base, size = syms[name]
        per = []
        for lo, fsz, fn in funcs:
            o = lo - taddr
            code = text[o:o + fsz]
            ins, lits, refs, strides = _analyse(code, lo, base, size)
            if refs:
                per.append((lo, fsz, fn, ins, lits, strides))
        if elem is None:
            st = collections.Counter()
            for p in per:
                st.update({k: v for k, v in p[5].items() if k > 1 and size % k == 0 and size // k > 1})
            if not st:
                raise ValueError(f"array cap {name}: element size not found; pass (keep, elem)")
            elem = st.most_common(1)[0][0]
        count = size // elem
        if keep >= count:
            continue
        end, new_end = base + size, base + keep * elem
        for lo, fsz, fn, ins, lits, _ in per:
            for a, (reg, t, v) in lits.items():
                if v != end:
                    continue
                if _only_compared(ins, a, reg):
                    text[t - taddr:t - taddr + 4] = new_end.to_bytes(4, "little")
                    report.append((name, fn, f"end literal {end:#x} -> {new_end:#x} at {t:#x}"))
                else:
                    report.append((name, fn, f"skipped: end address {end:#x} used as a value at {a:#x}"))
            # end = base + size built as `movs rE, rB; adds rE, #size` (rB = base literal)
            if size < 256 and keep * elem < 256:
                based = {reg for a, (reg, t, v) in lits.items() if v == base}
                for k, x in enumerate(ins):
                    m = re.fullmatch(r"(r\d+), (r\d+)", x.op_str)
                    if x.mnemonic == "movs" and m and m.group(2) in based and k + 2 < len(ins):
                        for y in ins[k + 1:k + 3]:
                            if y.mnemonic == "adds" and re.fullmatch(rf"{m.group(1)}, #(?:{size}|{size:#x})", y.op_str):
                                text[y.address - taddr] = keep * elem
                                report.append((name, fn, f"end adds #{size} -> #{keep * elem} at {y.address:#x}"))
            if count < 256:
                for x in ins:
                    if x.mnemonic == "cmp" and re.fullmatch(rf"r\d+, #(?:{count}|{count:#x})", x.op_str):
                        o = x.address - taddr
                        text[o] = keep
                        report.append((name, fn, f"cmp #{count} -> #{keep} at {x.address:#x}"))
    shutil.copyfile(elf, out)
    with open(out, "r+b") as fh:
        fh.seek(toff)
        fh.write(text)
    return report
