"""HRAM allocation per value group (Phase 1.5, item 4).

The register file keeps one 4-byte HRAM slot per ARM register ($FF80 + 4n). Instead of
giving every ARM register its own slot for the whole program, each *web* (SSA values
of one register connected through phi/pi, see bitwidth_pruning.webs) is assigned a
slot by liveness-based interference:

* liveness is computed per web at instruction level over each function's CFG
  (a web is a variable: used where one of its values is read, defined where one of
  its values is written). Registers live at a return are r0 plus, under AAPCS, the
  callee-saved r4-r11 and SP (entry function with `entry_abi="none"`: r0 and SP);
* a def interferes with every web live after the instruction, and with the webs read
  by the same instruction when they come from a different ARM register (no in-place
  overlap the Phase 0 sequences were not written for);
* webs are **pinned** to their home slot when the ABI or a multi-register instruction
  fixes their location: parameters / incoming values, SP/LR/PC, values defined or read
  by push/pop/ldm/stm/bl/ret, values live at a return, and every web of a function
  other than the program entry (callees keep their registers, so the caller only sees
  AAPCS-conformant slot usage across a call);
* other webs are colored greedily over slots 0-12, preferring slots that are already
  in use (the home slot first), so non-interfering values share slots.

The allocation is applied as a register renaming of the lifted IR (each instruction
reads/writes the slot number of the web involved); the whole Phase 1 pipeline (range
analysis, storage widths, flags, frame) then runs on the renamed program. Profiles
are translated with the returned (address, reg) -> slot map.
"""
from __future__ import annotations
from tools.lift.defuse import defs, uses
from tools.prune import range_analysis as ra
from tools.prune.bitwidth_pruning import webs

PINNED_OPS = ("push", "pop", "pop_ret", "ldm", "stm", "bl", "ret")
CALLEE_SAVED = tuple(range(4, 12))


def allocate(prog, entry_abi="aapcs", skip_lr=True):
    """Rename registers of `prog` in place; returns {(addr, old_reg): new_reg} for defs."""
    from tools.prune.frame import Frame
    ssa = ra.SSAProgram(prog)
    ra.analyze(ssa)
    fr = Frame(ssa, entry_abi, skip_lr, trim=False)
    elided = {}  # push/pop address -> registers whose slot transfer is elided
    for d in (fr.skip_push, fr.skip_pop):
        for a, rs in d.items():
            elided.setdefault(a, set()).update(rs)
    ws = webs(ssa)
    wid = {v: i for i, w in enumerate(ws) for v in w}
    reg = [w[0].reg for w in ws]
    pinned = set()
    entry = prog.entry
    for i, w in enumerate(ws):
        for v in w:
            if v.kind == "param" or v.reg >= 13 or ssa.func_of[v] != entry or \
                    (v.ins is not None and v.ins.op in PINNED_OPS):
                pinned.add(i)
    used_at, def_at = {}, {}
    for a, env in ssa.envs.items():
        x = prog.ins[a]
        used_at[a] = {wid[v] for v in env.values()}
        if x.op in PINNED_OPS:
            pinned |= used_at[a]
        def_at[a] = {wid[ssa.defval[(a, r)]] for r in defs(x) if (a, r) in ssa.defval}
    ret_live = {}
    for a, renv in ssa.ret_envs.items():
        func = next(f for f, fn in ssa.funcs.items() if a in fn.envs)
        regs = (0, 13) if (func == entry and entry_abi == "none") else (0, 13) + CALLEE_SAVED
        ret_live[a] = {wid[renv[r]] for r in regs if r in renv}
        pinned |= ret_live[a]
    # instruction-level liveness per function
    edges = {i: set() for i in range(len(ws))}

    def add(p, q):
        if p != q:
            edges[p].add(q)
            edges[q].add(p)
    for fa, fn in ssa.funcs.items():
        g = fn.g
        blocks = {n: g.nodes[n]["ins"] for n in g}
        live_in = {n: set() for n in g}
        changed = True
        while changed:
            changed = False
            for n in reversed(list(g)):
                live = set()
                for s in g.successors(n):
                    live |= live_in[s]
                for x in reversed(blocks[n]):
                    if x.addr in ret_live:
                        live |= ret_live[x.addr]
                    live = (live - def_at.get(x.addr, set())) | used_at.get(x.addr, set())
                if live != live_in[n]:
                    live_in[n] = live
                    changed = True
        for n in g:
            live = set()
            for s in g.successors(n):
                live |= live_in[s]
            for x in reversed(blocks[n]):
                if x.addr in ret_live:
                    live |= ret_live[x.addr]
                d = def_at.get(x.addr, set())
                u = used_at.get(x.addr, set())
                for p in d:
                    for q in live:
                        add(p, q)
                    for q in u:
                        if reg[q] != reg[p]:
                            add(p, q)
                    for q in d:
                        add(p, q)
                live = (live - d) | u
    # byte width of each web (storage class of the join of its proven ranges)
    from tools.prune.bitwidth_pruning import STORAGE
    def width(i):
        if i in pinned:
            return 4
        r = None
        for v in ws[i]:
            r = ra.join(r, v.proven) if v.proven is not None else r
        return STORAGE[ra.width_class(r)][0] if r is not None else 4
    color = {i: reg[i] for i in pinned}
    # webs whose slot is actually read or written by the generated code (elided
    # push/pop transfers do not touch the slot)
    referenced = set()
    for a in set(used_at) | set(def_at):
        x = prog.ins[a]
        skip = elided.get(a, set())
        env = ssa.envs.get(a, {})
        referenced |= {wid[v] for r, v in env.items() if not (r in skip and x.op == "push")}
        referenced |= {wid[ssa.defval[(a, r)]] for r in defs(x)
                       if (a, r) in ssa.defval and not (r in skip and x.op != "push")}
    occ = {s: 0 for s in range(16)}  # bytes of each slot already referenced
    for s in (0, 1, 2, 3):
        occ[s] = 4                   # argument slots are written by the caller
    for i in pinned & referenced:
        occ[color[i]] = 4
    order = sorted((i for i in range(len(ws)) if i not in pinned and i in referenced),
                   key=lambda i: min((v.ins.addr for v in ws[i] if v.ins), default=0))
    for i in order:
        bad = {color[j] for j in edges[i] if j in color}
        n = width(i)
        # cost = new bytes this web adds to the referenced HRAM; ties: home slot, then lowest
        c = min((s for s in range(13) if s not in bad),
                key=lambda s: (max(0, n - occ[s]), s != reg[i], s))
        color[i] = c
        occ[c] = max(occ[c], n)
    for i in range(len(ws)):
        color.setdefault(i, reg[i])
    # rewrite the IR (maps computed first, applied simultaneously)
    rename = {}
    for a, x in prog.ins.items():
        env = ssa.envs.get(a, {})
        umap = {r: color[wid[v]] for r, v in env.items()}
        dmap = {r: color[wid[ssa.defval[(a, r)]]] for r in defs(x) if (a, r) in ssa.defval}
        if all(umap[r] == r for r in umap) and all(dmap[r] == r for r in dmap):
            continue
        if x.op in PINNED_OPS:
            raise AssertionError(f"pinned instruction renamed at {a:#x}")
        R = lambda o: f"r{umap.get(int(o[1:]), int(o[1:]))}" if isinstance(o, str) else o
        new_a, new_b = R(x.a), R(x.b)
        if x.mem is not None:
            base, idx, disp = x.mem
            x.mem = (umap.get(base, base), umap.get(idx, idx) if idx is not None else None, disp)
        if x.rd is not None:
            if x.op.startswith("str"):
                x.rd = umap.get(x.rd, x.rd)
            elif x.rd in dmap:
                rename[(a, x.rd)] = dmap[x.rd]
                x.rd = dmap[x.rd]
        x.a, x.b = new_a, new_b
    return rename


def translate_profile(profile, rename):
    if not profile or not rename:
        return profile
    regs = {}
    for k, st in profile["regs"].items():
        a, r = k.split(":r")
        n = rename.get((int(a, 16), int(r)), int(r))
        regs[f"{a}:r{n}"] = st
    return {**profile, "regs": regs}
