"""CLI gba2gbc-core: ELF/bin Thumb -> ROM .gbc (MBC5) via RGBDS.

Usage: python -m tools.backend.gba2gbc_core kernel.elf -o kernel.gbc [--asm out.asm]"""
import argparse
import os
import subprocess
import sys
import tempfile
from tools.lift.lift import lift_file
from tools.backend.codegen import generate_asm

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNTIME = os.path.join(ROOT, "runtime")


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{' '.join(cmd)}\n{r.stdout}{r.stderr}")


def build(src, out, entry="f", asm_out=None, prune=None, profile=None, opts=None, hal=False, affine=None,
          peephole=None, port=None, audio=None, late_vsync=None, snapshot=None):
    """port: homebrew port description (docs/homebrew_port.md), a dict with
    overrides {function: native}, asm [port runtime files], defines [rgbasm -D for the
    HAL], rom_sram, vram_shadow, display_bg, port_init. Implies hal=True.
    audio (HAL builds): False (default; GBA2GB_AUDIO=1 turns it on) removes the audio
    subsystem: the functions found by tools/audio/strip.py become empty natives and
    sound / FIFO-DMA register writes are dropped (docs/audio.md, "Audio off")."""
    if port:
        hal = True
    if audio is None:
        audio = os.environ.get("GBA2GB_AUDIO", "0") not in ("0", "")
    if late_vsync is None:
        late_vsync = bool(port)
    if snapshot is None:
        snapshot = bool(port) and os.environ.get("GBA2GB_SNAPSHOT", "1") not in ("0", "")
    if hal and (late_vsync or snapshot):
        port = dict(port or {})
        port["defines"] = list(port.get("defines", [])) + (["LATE_VSYNC"] if late_vsync else []) + \
            (["SNAPSHOT"] if snapshot else [])
    cos_rep = None
    if hal and port and (port.get("cosmetic") is not None or port.get("array_caps")):
        src, cos_rep = _cosmetic(src, out, port)
    if not hal:
        return _build(src, out, entry, asm_out, prune, profile, opts, False, affine, peephole, None)
    from tools.lift import lift as _lift
    from tools.hal import intercept as _ic
    saved = dict(_ic.CONFIG), dict(_lift.EXTRA_NATIVES)
    _lift.EXTRA_NATIVES.clear()
    _ic.CONFIG["audio"] = bool(audio)
    if not audio:
        from tools.audio.strip import detect
        found = detect(src, entry)
        _lift.EXTRA_NATIVES.update({n: "audio_nop" for n in found})
    for k in ("rom_sram", "vram_shadow", "display_bg", "port_init", "oam_drop"):
        if port and k in port:
            _ic.CONFIG[k] = port[k]
    _lift.EXTRA_NATIVES.update((port or {}).get("overrides", {}))
    saved_memo = dict(_lift.MEMO)
    saved_clone = dict(_lift.CLONE)
    saved_dec = dict(_lift.DECIMATE)
    if port and port.get("overrides") is not None:
        _lift.DECIMATE.update(n=int(port.get("render_every", 2)),
                              render=set(port.get("draw_calls", [])) | set(port.get("present_calls", [])))
    _lift.CLONE["enabled"] = bool(port and port.get("specialize", _lift.CLONE.get("default", False)) and port.get("overrides") is not None)
    _lift.MEMO.clear()
    if port and port.get("memo", True) and port.get("overrides") is not None:
        from tools.lift.memo import find as memo_find
        _lift.MEMO.update({n: (i + 1, ps) for i, (n, ps) in enumerate(sorted(memo_find(src, entry).items()))
                           if n not in _lift.EXTRA_NATIVES})
    try:
        prog = _build(src, out, entry, asm_out, prune, profile, opts, True, affine, peephole, port)
        prog.audio_stubs = {} if audio else found
        prog.cosmetic = cos_rep
        if snapshot:
            from tools.hal.snapshot import capture_and_patch
            try:
                prog.snapshot = capture_and_patch(out, force=snapshot == "force")
            except RuntimeError as e:      # no VBlankIntrWait during init: normal boot
                prog.snapshot = {"skipped": str(e)}
        return prog
    finally:
        _ic.CONFIG.clear()
        _ic.CONFIG.update(saved[0])
        _lift.EXTRA_NATIVES.clear()
        _lift.EXTRA_NATIVES.update(saved[1])
        _lift.MEMO.clear()
        _lift.MEMO.update(saved_memo)
        _lift.DECIMATE.clear()
        _lift.DECIMATE.update(saved_dec)
        _lift.CLONE.clear()
        _lift.CLONE.update(saved_clone)


def _cosmetic(src, out, port):
    """Port manifest keys (docs/homebrew_port.md, "Cosmetic loops"):
    cosmetic: {"cap": K, "caps": {array: K}} - detected cosmetic loops keep K elements
    (0 = removed); array_caps: {array: K} - explicit caps for any global array."""
    from tools.lift import cosmetic, array_cap
    cfg = port.get("cosmetic") or {}
    patched = os.path.splitext(out)[0] + ".patched.elf"
    rep = {"loops": [], "caps": []}
    caps = dict(port.get("array_caps") or {})
    if port.get("cosmetic") is not None:
        found = cosmetic.find(src, set(port.get("draw_calls", port.get("overrides", {}))))
        rm = []
        for lp in found:
            k = cfg.get("caps", {}).get(lp["array"], cfg.get("cap", 0))
            lp["cap"] = k
            rep["loops"].append(lp)
            if k == 0:
                rm.append(lp)
            elif k < lp["count"]:
                caps.setdefault(lp["array"], (k, lp["elem"]))
        cur = src
        if rm:
            cosmetic.remove(cur, patched, rm)
            cur = patched
    else:
        cur = src
    if caps:
        tmp = patched + ".tmp"
        rep["caps"] = array_cap.cap_elf(cur, tmp, caps)
        os.replace(tmp, patched)
        cur = patched
    return cur, rep


def _build(src, out, entry, asm_out, prune, profile, opts, hal, affine, peephole, port):
    """prune: None (Phase 0), 'flags' (narrowed backend but all values 32-bit),
    'sound' (proven ranges) or 'profile' (observed ranges + guards; needs profile).
    hal: Phase 2 program mode (entry `main`, GB HAL runtime, intercepted I/O).
    peephole: Phase 5 A3 SM83 peephole pass (tools/backend/peephole.py); default on
    unless GBA2GB_PEEPHOLE=0."""
    prog = lift_file(src, entry)
    info = None
    if hal:
        from tools.hal import lower
    if prune:
        from tools.prune.bitwidth_pruning import build_plan
        from tools.backend.narrow import generate_narrow_asm
        from tools.backend.hram_usage import hram_reg_bytes
        mode = "profile" if prune == "profile" else "sound"

        def gen(o):
            p = lift_file(src, entry)
            plan = build_plan(p, profile, mode, o)
            if prune == "flags":
                plan.mode = "flags-only"
                plan.storage = {}
                plan.fused, plan.deleted = {}, set()
            acc, inf = lower.analyze(plan.ssa) if hal else ({}, None)
            plan.hal_info = inf
            return (p, plan) + generate_narrow_asm(plan, acc)
        o = dict(opts or {})
        prog, plan, asm, stats = gen(o)
        if plan.opts["hram_alloc"] and plan.rename:
            # item 4 is a heuristic: keep the allocation only if it does not increase
            # the referenced HRAM bytes (ties: smaller code)
            alt = gen({**o, "hram_alloc": False})
            key = lambda a: (hram_reg_bytes(a), a.count("\n"))
            if key(alt[2]) < key(asm):
                prog, plan, asm, stats = alt
                plan.rename_rejected = True
        prog.plan, prog.stats = plan, stats
        info = plan.hal_info
    else:
        acc = {}
        if hal:
            acc, info = lower.classify_phase0(prog)
        asm = generate_asm(prog, acc)
    if peephole is None:
        peephole = os.environ.get("GBA2GB_PEEPHOLE", "1") not in ("0", "")
    prog.peephole = None
    if peephole:
        from tools.backend.peephole import optimize
        asm, prog.peephole = optimize(asm)
    if hal:
        asm += lower.hal_sections(src, prog, info, affine)
        prog.hal_info = info
    from tools.backend.divconst import asm as divc_asm
    asm += divc_asm(getattr(prog, "divc", set()))
    from tools.lift.memo import asm as memo_asm
    asm += memo_asm(getattr(prog, "memo_used", {}))
    from tools.lift.decimate import asm as decim_asm
    from tools.lift import lift as _lft
    asm += decim_asm(getattr(prog, "decim", []), _lft.DECIMATE["n"])
    with tempfile.TemporaryDirectory() as td:
        k = asm_out or os.path.join(td, "kernel.asm")
        open(k, "w").write(asm)
        ko, ro = os.path.join(td, "kernel.o"), os.path.join(td, "runtime.o")
        run(["rgbasm", "-I", RUNTIME, "-o", ko, k])
        objs = [ro, ko]
        if hal:
            run(["rgbasm", "-DHAL", "-I", RUNTIME, "-o", ro, os.path.join(RUNTIME, "runtime.asm")])
            ho = os.path.join(td, "hal.o")
            defs = [f"-D{d}" for d in (port or {}).get("defines", [])]
            run(["rgbasm", *defs, "-I", RUNTIME, "-o", ho, os.path.join(RUNTIME, "gb_hal_shims.asm")])
            objs.append(ho)
            for i, pa in enumerate((port or {}).get("asm", [])):
                po = os.path.join(td, f"port{i}.o")
                inc = (port or {}).get("inc") or os.path.dirname(pa)
                run(["rgbasm", *defs, "-I", RUNTIME, "-I", inc, "-o", po, pa])
                objs.append(po)
        else:
            run(["rgbasm", "-I", RUNTIME, "-o", ro, os.path.join(RUNTIME, "runtime.asm")])
        so = os.path.join(td, "softfloat.o")
        run(["rgbasm", "-I", RUNTIME, "-o", so, os.path.join(RUNTIME, "gb_softfloat.asm")])
        bo = os.path.join(td, "bank.o")
        run(["rgbasm", "-I", RUNTIME, "-o", bo, os.path.join(RUNTIME, "gb_bank.asm")])
        objs.append(bo)
        objs.append(so)
        run(["rgblink", "-o", out, "-m", out + ".map", "-n", os.path.splitext(out)[0] + ".sym", *objs])
        run(["rgbfix", "-v", "-p", "0xFF", "-m", "0x1B", "-r", "0x04", "-t", "GBA2GB", out])
    return prog


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gba2gbc-core", description=__doc__)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--entry", default="f")
    ap.add_argument("--asm")
    ap.add_argument("--prune", choices=["flags", "sound", "profile"],
                    help="Phase 1 bit-width pruning mode (default: Phase 0 code)")
    ap.add_argument("--profile", help="range profile JSON (required for --prune profile)")
    ap.add_argument("--entry-abi", choices=["none", "aapcs"], default="none",
                    help="'none' (default): the entry function does not preserve r4-r11; the "
                         "caller must treat r1-r12 and LR as clobbered. 'aapcs': full AAPCS "
                         "callee-saved preservation (docs/frame_layout.md)")
    ap.add_argument("--keep-lr", action="store_true", help="keep saving LR on the emulated stack")
    ap.add_argument("--hal", action="store_true",
                    help="Phase 2 program mode: GB HAL runtime, statically intercepted GBA I/O "
                         "(use with --entry main; docs/hal.md)")
    a = ap.parse_args(argv)
    import json
    prof = json.load(open(a.profile)) if a.profile else None
    opts = {"entry_abi": a.entry_abi, "skip_lr": not a.keep_lr}
    p = build(a.input, a.output, a.entry, a.asm, a.prune, prof, opts, hal=a.hal)
    print(f"{a.output}: {len(p.ins)} Thumb instructions translated")


if __name__ == "__main__":
    sys.exit(main())
