"""Phase 5 A2: placement of MBC5 SRAM bank switches for EWRAM accesses
(docs/sram_paging.md).

Every EWRAM access has a compile-time bank (acc["bank"], from its proven address
range) or None (range spans banks / provenance only: the bank is selected at run
time from the address, HAL_EW_SETBANK). Bank switches are placed by:

1. Loop hoisting: for every natural loop (outermost first) whose EWRAM accesses
   all use the same compile-time bank b and that contains no clobber (run-time
   bank selection, `dyn` access, call to a function that touches EWRAM), the switch
   to b is emitted once on the loop entry edges: codegen puts it right after the
   header label and redirects the back edges (and an in-loop fall-through) to a
   second label after it.
2. A forward must-analysis of the current bank (unknown at function entry and
   after clobbers, b at hoisted headers): an access emits `ld [$4000], b` only if
   the bank is not already known to be b.

Result: acc[a]["switch"] (bool) for every compile-time-bank access and the hoist
table {header: {"bank": b, "body": set of block addresses}}."""
from __future__ import annotations
import networkx as nx


def _vsh():
    from tools.hal.intercept import CONFIG
    return CONFIG["vram_shadow"]


def touches(ssa, acc):
    """Functions that (transitively) access EWRAM or dynamic memory."""
    prog = ssa.prog
    direct, calls = {}, {}
    for fa, fn in ssa.funcs.items():
        d, c = False, set()
        for n in fn.g:
            for x in fn.g.nodes[n]["ins"]:
                r = acc.get(x.addr, {}).get("region")
                if r in ("ewram", "dyn", "vsh") or (r == "vram" and _vsh()):
                    d = True
                if x.op == "bl":
                    c.add(x.target)
        direct[fa], calls[fa] = d, c
    t = {f for f, d in direct.items() if d}
    ch = True
    while ch:
        ch = False
        for f, c in calls.items():
            if f not in t and c & (t | {x for x in c if x not in ssa.funcs}):
                t.add(f)
                ch = True
    return t


def plan(ssa, acc, hoist=True):
    tch = touches(ssa, acc)
    hoists, nswitch = {}, 0
    for fa, fn in ssa.funcs.items():
        g = fn.g
        blk = lambda n: g.nodes[n]["ins"]

        def event(x):
            d = acc.get(x.addr)
            if d is not None and d["region"] == "ewram":
                return ("use", d["bank"]) if d["bank"] is not None else ("clob", None)
            if d is not None and (d["region"] in ("dyn", "vsh") or (d["region"] == "vram" and _vsh())):
                return ("clob", None)       # VRAM stores / shadow reads select SRAM banks 8-11
            if x.op == "bl" and (x.target in tch or x.target not in ssa.funcs):
                return ("clob", None)
            return None

        # ---- 1. loops
        local = {}
        if hoist:
            idom = nx.immediate_dominators(g, fa)

            def dom(a, b):          # a dominates b
                while True:
                    if a == b:
                        return True
                    if idom.get(b, b) == b:
                        return False
                    b = idom[b]
            loops = {}
            for u, h in g.edges:
                if dom(h, u):
                    # natural loop: h + the nodes reaching u without passing h
                    body, work = {h, u}, [u]
                    while work:
                        n = work.pop()
                        if n == h:
                            continue
                        for p in g.predecessors(n):
                            if p not in body:
                                body.add(p)
                                work.append(p)
                    loops.setdefault(h, set()).update(body)
            for h, body in sorted(loops.items(), key=lambda kv: -len(kv[1])):
                if any(h in b2["body"] for b2 in local.values()):
                    continue
                evs = [e for n in body for x in blk(n) if (e := event(x))]
                banks = {e[1] for e in evs}
                if evs and all(e[0] == "use" for e in evs) and len(banks) == 1:
                    local[h] = {"bank": banks.pop(), "body": body}
        hoists.update(local)

        # ---- 2. must-analysis of the current bank
        UNDEF = object()
        IN = {n: UNDEF for n in g}
        OUT = {n: UNDEF for n in g}
        order = list(nx.dfs_preorder_nodes(g, fa))

        def run(n, state, emit=False):
            nonlocal nswitch
            for x in blk(n):
                e = event(x)
                if e is None:
                    continue
                if e[0] == "use":
                    if emit:
                        acc[x.addr]["switch"] = state != e[1]
                        nswitch += state != e[1]
                    state = e[1]
                else:
                    state = None
            return state

        ch = True
        while ch:
            ch = False
            for n in order:
                if n == fa:
                    s = None
                elif n in local:
                    s = local[n]["bank"]
                else:
                    ps = [OUT[p] for p in g.predecessors(n) if OUT[p] is not UNDEF]
                    s = ps[0] if ps and all(p == ps[0] for p in ps) else (None if ps else UNDEF)
                if s is UNDEF:
                    continue
                o = run(n, s)
                if IN[n] != s or OUT[n] != o:
                    IN[n], OUT[n] = s, o
                    ch = True
        for n in g:
            run(n, None if IN[n] is UNDEF else IN[n], emit=True)
    for a, d in acc.items():
        if d["region"] == "ewram" and d["bank"] is not None:
            d.setdefault("switch", True)
    return hoists, {"static_switches": nswitch + len(hoists), "hoisted_loops": len(hoists)}
