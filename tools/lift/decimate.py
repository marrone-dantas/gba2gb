"""Step 10: logic/render split by render decimation (docs/homebrew_port.md).

Detection (static, on the lifted Program):
  * frame loop: the strongly connected part of the entry function's CFG that contains
    a VBlank wait (`swi 4/5`);
  * render calls: direct calls made from that loop whose callee reaches (through the
    call graph) one of the port's drawing / presenting calls (`draw_calls`,
    `present_calls` in the port manifest, matched on the plain or demangled name);
  * the split is used only if the loop also makes at least one non-render call
    (the game logic), so logic is never skipped.

Rewrite: every render call site becomes `call NAT_decim_<k>`. A stub runs its callee
only on frames where wDecimCnt == 0; the stub of the last render site in loop order
advances wDecimCnt modulo N, so logic runs every frame and render runs every N-th
frame. Skipping both the draw and the present call of the same frame keeps the
presented sprite list consistent (a frame is either drawn and presented, or left
on screen as it is).
"""
from __future__ import annotations
import networkx as nx
from tools.audio.strip import demangle_base


def _callees(prog, f):
    return {prog.ins[a].target for a in prog._body(f) if prog.ins[a].op == "bl"}


def detect(prog, render_names):
    names = {}
    for n, a in prog.img.entries.items():
        names.setdefault(a & ~1, set()).update({n, demangle_base(n)})
    hit = lambda t: bool(names.get(t, set()) & render_names)
    memo = {}

    def renders(f, seen=()):
        if f in memo:
            return memo[f]
        if hit(f):
            memo[f] = True
            return True
        if f in seen or f not in prog.funcs:
            return False
        r = any(renders(t, seen + (f,)) for t in _callees(prog, f))
        memo[f] = r
        return r

    body = prog._body(prog.entry)
    g = prog.cfg.subgraph([n for n in prog.cfg if n in body])
    for scc in nx.strongly_connected_components(g):
        ins = [x for n in scc for x in prog.cfg.nodes[n]["ins"]]
        if not any(x.op == "swi" and x.a in (4, 5) for x in ins):
            continue
        calls = sorted((x for x in ins if x.op == "bl"), key=lambda x: x.addr)
        rend = [x for x in calls if renders(x.target)]
        logic = [x for x in calls if not renders(x.target) and x.native is None]
        if rend and logic:
            return rend
    return []


def apply(prog, n, render_names):
    """Rewrite render call sites; returns [(k, label or native, is_last)]."""
    sites = detect(prog, render_names)
    out = []
    for k, x in enumerate(sites):
        tgt = f"NAT_{x.native}" if x.native else f"L_{x.target:08X}"
        x.native = f"decim_{k}"
        out.append((k, tgt, k == len(sites) - 1))
    return out


def asm(stubs, n):
    if not stubs:
        return ""
    L = ['SECTION "decim", ROM0']
    for k, tgt, last in stubs:
        far = not tgt.startswith("NAT_")
        L += [f"NAT_decim_{k}::", "    ld a, [wDecimCnt]", "    or a", f"    jr nz, .skip{k}"]
        L += ([f"    ld a, BANK({tgt})", f"    ld hl, {tgt}", "    call FarCall"] if far else [f"    call {tgt}"])
        if last:
            L += ["    ld hl, wDecimDrawn", "    inc [hl]", f"    jr nz, .skip{k}", "    inc hl", "    inc [hl]"]
        L += [f".skip{k}:"]
        if last:
            L += ["    ld hl, wDecimLogic", "    inc [hl]", f"    jr nz, .lo{k}", "    inc hl", "    inc [hl]",
                  f".lo{k}:", "    ld a, [wDecimCnt]", "    inc a", f"    cp {n}", f"    jr c, .st{k}", "    xor a",
                  f".st{k}:", "    ld [wDecimCnt], a"]
        L += ["    ret"]
    return "\n".join(L) + "\n"
