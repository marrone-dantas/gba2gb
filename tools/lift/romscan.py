"""Static code discovery for a raw GBA ROM (no ELF, no symbols).

Starts at the ARM entry branch in the cartridge header, follows ARM and Thumb code
recursively (direct B/BL, BX to constant pool values loaded with LDR =, mode switches
via the low address bit) and reports what an AOT lift would face: instruction counts
per mode, indirect branches, SWIs, copies to IWRAM/EWRAM and undecodable targets.
Usage: python -m tools.lift.romscan game.gba [--json out.json]"""
from __future__ import annotations
import argparse, json, struct
from collections import Counter
import capstone as cs

BASE = 0x08000000


def header(rom: bytes):
    w = struct.unpack_from("<I", rom, 0)[0]
    if (w >> 24) & 0x0F != 0x0A:
        raise ValueError("ROM word 0 is not an ARM branch")
    off = ((w & 0xFFFFFF) ^ 0x800000) - 0x800000
    return {"title": rom[0xA0:0xAC].decode("ascii", "replace").strip("\0"),
            "code": rom[0xAC:0xB0].decode("ascii", "replace"),
            "entry": BASE + 8 + off * 4}



def scan(rom: bytes, limit=2_000_000):
    mds = {m: cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_ARM if m == "arm" else cs.CS_MODE_THUMB)
           for m in ("arm", "thumb")}
    for md in mds.values():
        md.detail = True
    h = header(rom)
    seen: dict[int, str] = {}
    work = [(h["entry"], "arm")]
    st = Counter(); swis = Counter(); indirect = []; ram_targets = set(); bad = []
    end = BASE + len(rom)

    def lit(addr):
        if BASE <= addr <= end - 4:
            return struct.unpack_from("<I", rom, addr - BASE)[0]

    while work and len(seen) < limit:
        a, mode = work.pop()
        md = mds[mode]
        last = {}  # register -> constant from a literal-pool load in this run
        while a not in seen:
            if not BASE <= a < end:
                ram_targets.add((a, mode)); break
            i = next(md.disasm(rom[a - BASE:a - BASE + 4], a, 1), None)
            if i is None:
                bad.append(a); break
            seen[a] = mode; st[mode] += 1
            mn = i.mnemonic.split(".")[0]
            ops = i.operands
            if mn.startswith("svc") or mn.startswith("swi"):
                swis[ops[0].imm & 0xFF if mode == "thumb" else (ops[0].imm >> 16) & 0xFF] += 1
            if mn.startswith("ldr") and len(ops) == 2 and ops[1].type == cs.arm.ARM_OP_MEM \
                    and ops[1].mem.base == cs.arm.ARM_REG_PC and not ops[1].mem.index:
                pc = (a + (8 if mode == "arm" else 4)) & ~3
                v = lit(pc + ops[1].mem.disp)
                if v is not None:
                    last[ops[0].reg] = v
            uncond = i.cc in (cs.arm.ARM_CC_AL, cs.arm.ARM_CC_INVALID)
            if mn in ("b", "bl") or (mn.startswith("b") and mn[1:3] in
                                     ("eq", "ne", "hs", "lo", "cs", "cc", "mi", "pl", "vs", "vc",
                                      "hi", "ls", "ge", "lt", "gt", "le") and len(mn) <= 3):
                if ops and ops[0].type == cs.arm.ARM_OP_IMM:
                    work.append((ops[0].imm, mode))
                    if mn == "b" and uncond:
                        break
            elif mn == "blx" and ops[0].type == cs.arm.ARM_OP_IMM:
                work.append((ops[0].imm, "thumb" if mode == "arm" else "arm"))
            elif mn in ("bx", "blx"):
                r = ops[0].reg
                if r in last:
                    v = last[r]
                    work.append((v & ~1, "thumb" if v & 1 else "arm"))
                elif r != cs.arm.ARM_REG_LR:
                    indirect.append(a)
                if mn == "bx" and uncond:
                    break
            elif mn == "pop" and any(o.reg == cs.arm.ARM_REG_PC for o in ops):
                if uncond:
                    break
            elif (mn.startswith("ldm") or mn.startswith("pop")) and any(
                    o.type == cs.arm.ARM_OP_REG and o.reg == cs.arm.ARM_REG_PC for o in ops):
                if uncond:
                    break
            elif len(ops) >= 1 and ops[0].type == cs.arm.ARM_OP_REG and ops[0].reg == cs.arm.ARM_REG_PC:
                if mn.startswith("ldr") and "pc" not in i.op_str.split(",", 1)[1]:
                    indirect.append(a)
                elif mn.startswith("mov") or mn.startswith("add"):
                    indirect.append(a)  # jump tables / computed gotos
                if uncond:
                    break
            a += i.size
    rammap = Counter((t >> 24) for t, _ in ram_targets)
    return {**h, "entry": hex(h["entry"]), "insns": dict(st), "bytes_code": sum(4 if m == "arm" else 2 for m in seen.values()),
            "swi": {f"{k:#04x}": v for k, v in sorted(swis.items())},
            "indirect_branches": len(indirect), "ram_branch_targets": len(ram_targets),
            "ram_regions": {f"{k:#04x}": v for k, v in rammap.items()},
            "decode_failures": len(bad), "first_arm": [hex(a) for a, m in sorted(seen.items()) if m == "arm"][:8]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("rom"); ap.add_argument("--json")
    a = ap.parse_args(argv)
    r = scan(open(a.rom, "rb").read())
    print(json.dumps(r, indent=1))
    if a.json:
        json.dump(r, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
