# EWRAM -> MBC5 SRAM paging (Phase 5 A2)

GBA EWRAM (256 KiB at 0x02000000) no longer shares the GB WRAM window with IWRAM.
It is mapped onto the cartridge SRAM of the MBC5 (header `-m 0x1B -r 0x04`,
16 banks x 8 KiB = 128 KiB):

    bank = (addr >> 13) & 15            (MBC5 RAM bank register $4000)
    GB address = $A000 | (addr & $1FFF)

`GbaDataInit` enables the SRAM (`$0A -> $0000`) and clears the banks used by the
`.ewram` section (EWRAM data is zero-initialised, NOLOAD). EWRAM beyond 128 KiB is
rejected at compile time.

## Allocator (`tools/sram/ewram_alloc.py`)

EWRAM objects are declared one per section (`__attribute__((section(".ewram.NAME")))`).
The mapping above is the identity on offsets, so the allocator works at link time:
it reads the section sizes of the object file and produces the link script
(`--base gba.ld`) with an explicit offset for every object:

* objects larger than 8 KiB start at a bank boundary and use consecutive banks;
* objects of at most 8 KiB never straddle a bank boundary (first-fit decreasing
  into the 16 banks), so every access to them has a compile-time bank;
* a JSON report lists offset / size / banks per object.

## Bank switches (`tools/sram/bank_switch.py`, codegen `ew_hl`)

* Compile-time bank (proven address range within one bank): `ld a, b; ld [$4000], a`
  before the access, unless a forward must-analysis proves that the bank is already
  current (bank unknown at function entry, after run-time bank selections, `dyn`
  accesses and calls to functions that touch EWRAM).
* Loop hoisting: a natural loop whose EWRAM accesses all use the same compile-time
  bank and that has no clobber gets the switch once after its header label; back
  edges (and an in-loop fall-through) jump to a second label `L_xxx_in` after it.
  `GBA2GB_NO_HOIST=1` disables it (used by the test to measure the saving).
* Run-time bank (range spans banks, or the pointer is only known to be EWRAM by
  provenance): `call HAL_EW_SETBANK` computes the bank from the address in T1.
* Unknown pointers (`dyn`, Phase 5 A1): `HAL_DYN_ADDR` / `HAL_DYN_STORE` now
  dispatch 0x02xxxxxx to the SRAM (with bank selection) and 0x03xxxxxx to WRAM.

## Test and numbers (`tests/test_sram_paging.py`, `tests/demos/ewram_demo.c`)

ewram_demo uses 25.4 KiB of EWRAM in five objects: `big` (12 KiB, banks 0-1),
`hist` + `lut` (bank 1), `buf_a` (bank 2), `buf_b` (bank 3). The GB build matches
the GBA reference exactly (init results and 50+ per-frame checksums).

| | static switches | run-time bank selections | dyn accesses | init M-cycles |
|---|---|---|---|---|
| hoisting on | 4 + 1 hoisted | 11 | 2 | 11,807,658 |
| hoisting off | 5 | 11 | 2 | 11,843,652 |

The hoisted `buf_a` fill loop saves 6 M per iteration (35,994 M over 6000
iterations). Limitation: loops that walk an EWRAM object with an incremented
pointer (GCC's usual form for `p[i]` with i counted down/up through a pointer) have
no proven range, so they use the run-time bank selection (~30 M per access) and
cannot be hoisted; this dominates the init time above. Tracking per-object
provenance for induction pointers would remove it.
