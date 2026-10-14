/* GBA link script for the Phase 2 demos: code + rodata in ROM, data/bss in IWRAM
   (0x03000000, the transpiler maps it to GB WRAM $C000). */
ENTRY(_start)
SECTIONS
{
    . = 0x08000000;
    .text : { *(.crt0) *(.text*) *(.rodata*) . = ALIGN(4); }
    __data_lma = .;
    .data 0x03000000 : AT(__data_lma) { __data_start = .; *(.data*) . = ALIGN(4); __data_end = .; }
    .bss : { __bss_start = .; *(.bss*) *(COMMON) . = ALIGN(4); __bss_end = .; }
    /DISCARD/ : { *(.ARM.attributes) *(.comment) }
}
