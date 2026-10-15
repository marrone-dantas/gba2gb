"""Memoization of map-pure functions (docs/homebrew_port.md, "Memoization").

A function is *map-pure* when its result depends only on its integer arguments,
ROM data and the GBA VRAM (BG maps / tiles): typical tile / flag queries such as
`tile_at(x, y)` or `tile_flag_at(x, y, w, h, flag)`. Static check (Thumb), with a
flow-insensitive value-source analysis: every register holds a set of abstract
values, each a set of sources {ARG, ROM, VRAM, SP, RAM, DATA}; a load is allowed only
if every abstract value of its base contains ROM, VRAM or SP (an index derived from
arguments may be added) and none contains RAM or is pure ARG / DATA (a pointer
argument or a loaded pointer); stores only to the stack; calls only to map-pure
functions or arithmetic helpers. Parameters come from the Itanium mangled name and
must be integers of 1-4 bytes (C names are not memoized: their arity is unknown).

Every call to such a function becomes `call NAT_memo_<id>`: a 64-entry direct-mapped
cache in the ARM IWRAM window ($C000 + MEMO_BASE) keyed by (id, argument bytes,
including stack arguments) holding r0; a miss calls the lifted function. Any GBA
VRAM store (HAL_VRAM_STORE16) marks the cache stale and the next lookup clears it.
"""
from __future__ import annotations
import re
import capstone as cs
from elftools.elf.elffile import ELFFile
from tools.audio.strip import NAME_RE  # noqa: F401  (same scanning conventions)

SIZES = {"h": 1, "a": 1, "c": 1, "b": 1, "s": 2, "t": 2, "i": 4, "j": 4, "l": 4, "m": 4}
ARITH = re.compile(r"_*aeabi_\w+|_*(?:u?div|u?mod)[sd]i3\w*|\w*_from_thumb")
MEMO_BASE = 0xC100          # 64 x 16 bytes, ARM 0x03000100-0x030004FF
NENT = 64


def params(name):
    m = re.fullmatch(r"_ZL?(\d+)(\w+)", name)
    if not m:
        return None
    n = int(m.group(1))
    rest = m.group(2)[n:]
    if rest == "v":
        return []
    if not rest or any(c not in SIZES for c in rest):
        return None
    return [SIZES[c] for c in rest]


def src_of(v):
    if 0x08000000 <= v < 0x0A000000:
        return "ROM"
    if 0x06000000 <= v < 0x06018000:
        return "VRAM"
    if 0x02000000 <= v < 0x04000000:
        return "RAM"
    if 0x04000000 <= v < 0x05000000:
        return "IO"
    return None


def _funcs(elf):
    with open(elf, "rb") as fh:
        e = ELFFile(fh)
        st = e.get_section_by_name(".symtab")
        text = e.get_section_by_name(".text")
        ta, td = text["sh_addr"], text.data()
        out, allf = {}, {}
        for s in st.iter_symbols():
            if s["st_info"]["type"] == "STT_FUNC":
                allf[s["st_value"] & ~1] = s.name
                if s["st_value"] & 1 and s["st_size"]:
                    lo = s["st_value"] & ~1
                    out[s.name] = (lo, td[lo - ta:lo - ta + s["st_size"]])
    return out, allf


def _pure(name, lo, code, pure, allf):
    md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB)
    ins = list(md.disasm(code, lo))
    lit, pool = {}, set()
    for x in ins:
        m = re.match(r"(r\d+), \[pc, #(0x[0-9a-f]+|\d+)\]", x.op_str)
        if x.mnemonic == "ldr" and m:
            t = ((x.address + 4) & ~3) + int(m.group(2), 0)
            if lo <= t <= lo + len(code) - 4:
                lit[x.address] = int.from_bytes(code[t - lo:t - lo + 4], "little")
                pool.update(range(t, t + 4))
    ins = [x for x in ins if x.address not in pool]
    A = frozenset
    idx = {x.address: k for k, x in enumerate(ins)}
    init = {f"r{i}": {A({"ARG"})} for i in range(4)}
    init["sp"] = {A({"SP"})}
    state_in = {0: (init, {})}
    work = [0]

    def ok_base(vals):
        return all(v & {"ROM", "VRAM", "SP"} and not v & {"RAM", "IO"} for v in vals)

    def combine(srcs, get):
        vals = {A({"CONST"})}
        for s in srcs:
            vals = {u | w for u in vals for w in get(s)}
        return {v - {"CONST"} or A({"CONST"}) for v in vals}

    steps = 0
    while work:
        steps += 1
        if steps > 20000:
            return False
        k = work.pop()
        regs0, slots0 = state_in[k]
        regs = {r: set(v) for r, v in regs0.items()}
        slots = {r: set(v) for r, v in slots0.items()}
        x = ins[k]
        get = lambda r: regs.get(r, {A({"DATA"})})
        mn, ops = x.mnemonic, [o.strip() for o in x.op_str.replace("{", "").replace("}", "").split(",")]
        succ = [k + 1]
        if mn in ("bl", "blx"):
            t = int(x.op_str[1:], 16) if x.op_str.startswith("#") else None
            if t is None or not (ARITH.fullmatch(allf.get(t, "")) or allf.get(t) in pure):
                return False
            for r in ("r0", "r1", "r2", "r3"):
                regs[r] = {A({"DATA"})}
        elif mn == "bx" or (mn == "pop" and "pc" in ops):
            succ = []
        elif mn.startswith("b") and x.op_str.startswith("#"):
            t = idx.get(int(x.op_str[1:], 16))
            if t is None:
                return False
            succ = [t] if mn == "b" else [t, k + 1]
        elif mn == "pop":
            for r in ops:
                regs[r] = {A({"DATA"})}
        elif mn in ("push", "nop", "cmp", "cmn", "tst"):
            pass
        elif mn.startswith(("str", "stm")):
            m = re.search(r"\[sp(?:, #(0x[0-9a-f]+|\d+))?\]", x.op_str)
            if not m:
                return False
            slots[int(m.group(1) or "0", 0)] = set(get(ops[0]))
        elif mn.startswith("ldr") or mn.startswith("ldm"):
            if x.address in lit:
                sv = src_of(lit[x.address])
                regs[ops[0]] = {A({sv})} if sv else {A({"CONST"})}
            else:
                m = re.search(r"\[(\w+)(?:, (#?[\w]+))?\]", x.op_str)
                if not m:
                    return False
                if m.group(1) == "sp" and (m.group(2) or "#0").startswith("#"):
                    kk = int(m.group(2)[1:] if m.group(2) else "0", 0)
                    regs[ops[0]] = set(slots.get(kk, {A({"ARG"})}))
                else:
                    bases = [b for b in (m.group(1), m.group(2)) if b and not b.startswith("#")]
                    if not ok_base(combine(bases, get)):
                        return False
                    regs[ops[0]] = {A({"DATA"})}
        elif mn == "add" and len(ops) == 3 and ops[1] == "sp":
            regs[ops[0]] = {A({"SP"})}
        else:
            srcs = [o for o in ops[1:] if re.fullmatch(r"r\d+|sp", o)]
            if mn in ("adds", "add", "subs", "sub", "orrs", "eors", "ands", "adcs", "sbcs", "bics", "muls") \
                    and len(ops) == 2:
                srcs = [ops[0]] + srcs
            regs[ops[0]] = combine(srcs, get)
        for s2 in succ:
            if s2 >= len(ins):
                continue
            if s2 not in state_in:
                state_in[s2] = (regs, slots)
                work.append(s2)
                continue
            r0, sl0 = state_in[s2]
            ch = False
            for r, v in regs.items():
                if not v <= r0.get(r, set()):
                    r0.setdefault(r, set()).update(v)
                    ch = True
            for r, v in slots.items():
                if not v <= sl0.get(r, set()):
                    sl0.setdefault(r, set()).update(v)
                    ch = True
            if ch:
                work.append(s2)
    return True


def _does_work(lo, code):
    """Worth caching: the body has a non-literal load or a call."""
    md = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB)
    for x in md.disasm(code, lo):
        if x.mnemonic in ("bl", "blx") or (x.mnemonic.startswith("ldr") and "pc" not in x.op_str
                                           and "sp" not in x.op_str):
            return True
    return False


def find(elf, entry="main"):
    """{function name: [param sizes]} of memoizable functions."""
    funcs, allf = _funcs(elf)
    pure = set()
    changed = True
    while changed:
        changed = False
        for n, (lo, code) in funcs.items():
            if n in pure or n == entry:
                continue
            if _pure(n, lo, code, pure, allf) and _does_work(lo, code):
                pure.add(n)
                changed = True
    out = {}
    for n in pure:
        p = params(n)
        if p and sum(p) <= 7 and len(p) <= 8:
            out[n] = p
    return out


def asm(used):
    """used: {id: (label of the lifted function, [param sizes])}."""
    if not used:
        return ""
    L = []
    for fid, (lab, ps) in sorted(used.items()):
        L += [f'SECTION "memo_{fid}", ROM0', f"NAT_memo_{fid}::", "    ld a, [wMemoOk]", "    or a",
              "    call z, MemoClear", "    ld hl, wMemoKey", f"    ld [hl], {fid}", "    inc hl"]
        nb = 0
        for i, sz in enumerate(ps):
            if i < 4:
                for b in range(sz):
                    L += [f"    ldh a, [HR_R0 + {4 * i + b}]", "    ld [hl+], a"]
            else:
                off = 4 * (i - 4)
                L += ["    push hl", "    ldh a, [HR_SP]", f"    add a, {off & 0xFF}", "    ld e, a",
                      "    ldh a, [HR_SP + 1]", "    adc a, 0", "    and $0F", "    or $C0", "    ld d, a", "    pop hl"]
                for b in range(sz):
                    L += ["    ld a, [de]", "    inc de", "    ld [hl+], a"]
            nb += sz
        L += ["    xor a"] + ["    ld [hl+], a"] * (7 - nb)
        L += ["    call MemoLookup", f"    jr nz, .miss", "    jp MemoHit", ".miss:",
              "    ld hl, wMemoKey", "    ld a, [hl+]", "    ld e, a", "    ld a, [hl+]", "    ld d, a", "    push de",
              "    ld a, [hl+]", "    ld e, a", "    ld a, [hl+]", "    ld d, a", "    push de",
              "    ld a, [hl+]", "    ld e, a", "    ld a, [hl+]", "    ld d, a", "    push de",
              "    ld a, [hl+]", "    ld e, a", "    ld a, [hl]", "    ld d, a", "    push de",
              f"    ld a, BANK({lab})", f"    ld hl, {lab}", "    call FarCall", "    jp MemoStore"]
    L += ['SECTION "memo_core", ROM0',
          "; hl = entry of wMemoKey (hash of the 8 key bytes); z = hit",
          "MemoIndex:", "    ld hl, wMemoKey", "    ld b, 8", "    xor a", ".h:", "    rlca", "    xor [hl]", "    inc hl",
          "    dec b", "    jr nz, .h", f"    and {NENT - 1}", "    ld l, a", "    ld h, 0",
          "    add hl, hl", "    add hl, hl", "    add hl, hl", "    add hl, hl", f"    ld de, ${MEMO_BASE:04X}",
          "    add hl, de", "    ret",
          "MemoLookup:", "    call MemoIndex", "    push hl", "    ld de, wMemoKey", "    ld b, 8", ".c:", "    ld a, [de]",
          "    cp [hl]", "    jr nz, .x", "    inc de", "    inc hl", "    dec b", "    jr nz, .c", ".x:", "    pop hl", "    ret",
          "MemoHit:                    ; hl = entry", "    ld de, 8", "    add hl, de", "    ld a, [hl+]",
          "    ldh [HR_R0], a", "    ld a, [hl+]", "    ldh [HR_R0 + 1], a", "    ld a, [hl+]", "    ldh [HR_R0 + 2], a",
          "    ld a, [hl]", "    ldh [HR_R0 + 3], a", "    ret",
          "MemoStore:                  ; key on the GB stack (pushed before the call)",
          "    ld hl, wMemoKey + 7", "    pop de", "    ld a, d", "    ld [hl-], a", "    ld a, e", "    ld [hl-], a",
          "    pop de", "    ld a, d", "    ld [hl-], a", "    ld a, e", "    ld [hl-], a",
          "    pop de", "    ld a, d", "    ld [hl-], a", "    ld a, e", "    ld [hl-], a",
          "    pop de", "    ld a, d", "    ld [hl-], a", "    ld a, e", "    ld [hl], a",
          "    ld a, [wMemoOk]", "    or a", "    ret z               ; VRAM changed during the call: do not cache",
          "    call MemoIndex", "    ld de, wMemoKey", "    ld b, 8", ".s:", "    ld a, [de]", "    ld [hl+], a", "    inc de",
          "    dec b", "    jr nz, .s", "    ldh a, [HR_R0]", "    ld [hl+], a", "    ldh a, [HR_R0 + 1]", "    ld [hl+], a",
          "    ldh a, [HR_R0 + 2]", "    ld [hl+], a", "    ldh a, [HR_R0 + 3]", "    ld [hl], a", "    ret",
          "MemoClear:", f"    ld hl, ${MEMO_BASE:04X}", f"    ld b, {NENT}", "    ld de, 16", ".z:", "    ld [hl], 0",
          "    add hl, de", "    dec b", "    jr nz, .z", "    ld a, 1", "    ld [wMemoOk], a", "    ret"]
    return "\n".join(L) + "\n"
