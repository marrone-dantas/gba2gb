/* Link script for homebrew ports whose globals exceed the 4 KiB IWRAM window
   (docs/memory_map.md): code + rodata in ROM, .data in IWRAM (0x03000000, GB $C000),
   .bss in EWRAM (0x02000000, MBC5 SRAM bank 0..: docs/sram_paging.md; the HAL clears it
   like any NOLOAD .ewram section). Unwind tables are discarded (no exceptions). */
ENTRY(_start)
SECTIONS
{
    . = 0x08000000;
    .text : { *(.crt0) *(.text*) *(.rodata*) . = ALIGN(4); __init_array_start = .; *(.init_array*) __init_array_end = .; }
    __data_lma = .;
    .data 0x03000000 : AT(__data_lma) { __data_start = .; *(.data*) . = ALIGN(4); __data_end = .; }
    __bss_start = .;
    __bss_end = .;
    .ewram 0x02000000 (NOLOAD) : { __ewram_start = .; *(.bss*) *(COMMON) *(.ewram*) . = ALIGN(4); __ewram_end = .; }
    /DISCARD/ : { *(.ARM.attributes) *(.comment) *(.ARM.exidx*) *(.ARM.extab*) }
}
