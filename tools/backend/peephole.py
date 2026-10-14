"""Phase 5 A3: SM83 peephole optimizer on the emitted kernel assembly.

Works on the text produced by codegen.py / narrow.py (one instruction per line,
labels in column 0, comments `;`). Passes, iterated to a fixpoint:

1. Accumulator / HRAM value tracking inside straight-line code (reset at labels,
   calls, returns and unconditional jumps): drops `ld a, n` when A already holds n,
   `ldh a, [X]` when A already equals HRAM X, and `ldh [X], a` when X already equals
   A. Only HRAM $FF80-$FFFE is tracked (I/O registers are never touched); any other
   memory write ([hl], [bc], [de], absolute, `ldh [c]`) forgets all HRAM knowledge.
2. x2 in A: `ldh [T], a` + k x (`ld hl, T` / `sla [hl]`) + `ldh a, [T]` (the
   narrowed 8-bit `lsl #k`) becomes k x `add a, a` + `ldh [T], a` (same Z/N/C; H is
   never read). If hl is live afterwards, `ld hl, T` is kept once.
3. LDI/LDD fusion: `ld [hl], a` / `ld a, [hl]` followed by `inc hl` / `dec hl`
   becomes the post-increment / post-decrement form.
4. Jump threading: jumps to a label whose first instruction is `jp L2` go to L2;
   `jp L` right before `L:` is removed; `jp cc, L1 / jp L2 / L1:` becomes
   `jp !cc, L2 / L1:`.
5. `ld a, 0` -> `xor a` when the flags are provably dead (overwritten by a full
   flag writer before any reader, within the straight-line code).

The pass is on by default; GBA2GB_PEEPHOLE=0 disables it."""
from __future__ import annotations
import re

ALU_A = {"add", "adc", "sub", "sbc", "and", "or", "xor", "inc", "dec", "rla", "rlca", "rra", "rrca",
         "cpl", "daa", "swap", "sla", "sra", "srl", "rl", "rr", "rlc", "rrc", "res", "set", "pop"}
FLAG_READ = {"adc", "sbc", "rla", "rra", "rl", "rr", "ccf", "daa"}
FLAG_FULL = {"add", "sub", "and", "or", "xor", "cp"}       # write Z N H C without reading
INV = {"z": "nz", "nz": "z", "c": "nc", "nc": "c"}
HRAM_RE = re.compile(r"^ldh \[\$(FF[89A-F][0-9A-F])\], a$")
HRAM_LD = re.compile(r"^ldh a, \[\$(FF[89A-F][0-9A-F])\]$")
LD_IMM = re.compile(r"^ld a, (\$[0-9A-Fa-f]+|\d+)$")


def is_label(l):
    return bool(l) and not l[0].isspace() and l.rstrip().endswith(":") and not l.startswith(";")


def ins(l):
    """Instruction text without indentation / comment, or None."""
    if not l or not l[0].isspace():
        return None
    s = l.split(";", 1)[0].strip()
    return s or None


def mnem(s):
    return s.split()[0]


def barrier(s):
    m = mnem(s)
    return m in ("call", "rst", "ret", "reti", "jp", "jr", "halt", "stop", "ei", "di") or s.startswith("INCLUDE") \
        or s.startswith("SECTION") or m in ("db", "dw", "ds")


def writes_a(s):
    m = mnem(s)
    if s.startswith("ld a,") or s.startswith("ldh a,"):
        return True
    if m == "pop":
        return s == "pop af"
    if m in ("inc", "dec", "swap", "sla", "sra", "srl", "rl", "rr", "rlc", "rrc", "res", "set"):
        return s.split(None, 1)[1].split(",")[-1].strip() == "a"
    return m in ("add", "adc", "sub", "sbc", "and", "or", "xor", "rla", "rlca", "rra", "rrca", "cpl", "daa") and \
        not s.startswith("add hl") and not s.startswith("add sp")


def writes_mem(s):
    m = mnem(s)
    if m in ("ld", "ldh"):
        dst = s.split(None, 1)[1].split(",")[0].strip()
        return dst.startswith("[")
    if m in ("inc", "dec", "sla", "sra", "srl", "rl", "rr", "rlc", "rrc", "swap", "res", "set"):
        return "[hl]" in s
    return m in ("push", "call", "rst")


def imm(v):
    return int(v[1:], 16) if v.startswith("$") else int(v)


def pass_values(L):
    out, aval, mem, n = [], None, set(), 0
    for l in L:
        if is_label(l):
            aval, mem = None, set()
            out.append(l)
            continue
        s = ins(l)
        if s is None:
            out.append(l)
            continue
        m = LD_IMM.match(s)
        if m:
            v = imm(m.group(1)) & 0xFF
            if aval == v:
                n += 1
                continue
            out.append(l)
            aval, mem = v, set()
            continue
        m = HRAM_LD.match(s)
        if m:
            x = m.group(1)
            if x in mem:
                n += 1
                continue
            out.append(l)
            aval, mem = None, {x}
            continue
        m = HRAM_RE.match(s)
        if m:
            x = m.group(1)
            if x in mem:
                n += 1
                continue
            out.append(l)
            mem.add(x)
            continue
        out.append(l)
        if barrier(s):
            aval, mem = None, set()
            continue
        if writes_a(s):
            aval, mem = None, set()
        if writes_mem(s):
            mem = set()
    return out, n


def hl_dead(L, i):
    """True if hl is overwritten before being read from line i on (straight line)."""
    for l in L[i:]:
        if is_label(l):
            return False
        s = ins(l)
        if s is None:
            continue
        if s.startswith("ld hl,"):
            return True
        if barrier(s) and mnem(s) in ("ret", "reti"):
            return True
        if barrier(s):
            return False
        if re.search(r"\bhl\b|\[hl[+-]?\]|\bh\b|\bl\b", s):
            return False
    return False


def pass_x2(L):
    out, i, n = [], 0, 0
    while i < len(L):
        s = ins(L[i])
        m = HRAM_RE.match(s) if s else None
        if m:
            t = m.group(1)
            j, k = i + 1, 0
            while j + 1 < len(L) and ins(L[j]) == f"ld hl, ${t}" and ins(L[j + 1]) == "sla [hl]":
                j += 2
                k += 1
            if k and j < len(L) and ins(L[j]) == f"ldh a, [${t}]":
                out += ["    add a, a"] * k + [f"    ldh [${t}], a"]
                if not hl_dead(L, j + 1):
                    out.append(f"    ld hl, ${t}")
                n += k
                i = j + 1
                continue
        out.append(L[i])
        i += 1
    return out, n


def pass_fuse(L):
    out, i, n = [], 0, 0
    while i < len(L):
        s, t = ins(L[i]), ins(L[i + 1]) if i + 1 < len(L) else None
        if s in ("ld [hl], a", "ld a, [hl]") and t in ("inc hl", "dec hl"):
            op = "+" if t == "inc hl" else "-"
            out.append("    " + s.replace("[hl]", f"[hl{op}]"))
            n += 1
            i += 2
            continue
        out.append(L[i])
        i += 1
    return out, n


JP = re.compile(r"^jp (?:(z|nz|c|nc), )?(\S+)$")


def pass_jumps(L):
    n = 0
    first = {}
    for i, l in enumerate(L):
        if is_label(l):
            name = l.rstrip().rstrip(":")
            for l2 in L[i + 1:]:
                if is_label(l2):
                    continue
                s = ins(l2)
                if s is None:
                    continue
                first[name] = s
                break

    def final(t, seen=()):
        s = first.get(t)
        m = JP.match(s) if s else None
        if m and not m.group(1) and m.group(2) != t and t not in seen:
            return final(m.group(2), seen + (t,))
        return t
    out = []
    for l in L:
        s = ins(l)
        m = JP.match(s) if s else None
        if m:
            t = final(m.group(2))
            if t != m.group(2):
                n += 1
                l = f"    jp {m.group(1) + ', ' if m.group(1) else ''}{t}"
        out.append(l)
    L, out = out, []
    i = 0
    while i < len(L):
        s = ins(L[i])
        m = JP.match(s) if s else None
        if m:
            # next real line(s)
            j = i + 1
            while j < len(L) and ins(L[j]) is None and not is_label(L[j]):
                j += 1
            labels, k = [], j
            while k < len(L) and (is_label(L[k]) or ins(L[k]) is None):
                if is_label(L[k]):
                    labels.append(L[k].rstrip().rstrip(":"))
                k += 1
            if m.group(2) in labels:
                n += 1
                i += 1
                continue
            if m.group(1) and j < len(L) and not is_label(L[j]):
                m2 = JP.match(ins(L[j]) or "")
                if m2 and not m2.group(1):
                    k = j + 1
                    labels = []
                    while k < len(L) and (is_label(L[k]) or ins(L[k]) is None):
                        if is_label(L[k]):
                            labels.append(L[k].rstrip().rstrip(":"))
                        k += 1
                    if m.group(2) in labels:
                        out.append(f"    jp {INV[m.group(1)]}, {m2.group(2)}")
                        n += 1
                        i = j + 1
                        continue
        out.append(L[i])
        i += 1
    return out, n


def flags_dead(L, i):
    for l in L[i:]:
        if is_label(l):
            return False
        s = ins(l)
        if s is None:
            continue
        m = mnem(s)
        if m in FLAG_FULL and not s.startswith("add hl") and not s.startswith("add sp"):
            return True
        if m in FLAG_READ or barrier(s) or m in ("push", "pop") or (m in ("jp", "jr") and "," in s):
            return False
        if m in ("rlca", "rrca", "scf", "ccf", "inc", "dec", "sla", "sra", "srl", "swap", "bit", "rlc", "rrc"):
            return False   # partial writers / readers: be conservative
    return False


def pass_xor(L):
    out, n = [], 0
    for i, l in enumerate(L):
        s = ins(l)
        if s in ("ld a, $00", "ld a, 0") and flags_dead(L, i + 1):
            out.append("    xor a")
            n += 1
            continue
        out.append(l)
    return out, n


def optimize(asm: str):
    """Returns (optimized asm, {pass: rewrites})."""
    L = asm.split("\n")
    stats = {"values": 0, "x2": 0, "fuse": 0, "jumps": 0, "xor": 0}
    for _ in range(8):
        tot = 0
        for name, f in (("x2", pass_x2), ("values", pass_values), ("fuse", pass_fuse),
                        ("jumps", pass_jumps), ("xor", pass_xor)):
            L, k = f(L)
            stats[name] += k
            tot += k
        if not tot:
            break
    return "\n".join(L), stats
