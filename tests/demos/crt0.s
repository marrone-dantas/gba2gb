@ Minimal GBA start-up (ARM mode): header, stack, .data copy, .bss clear, then the
@ Thumb main(). Not transpiled: the transpiler starts at `main` and the GB HAL does
@ the same initialisation (tools/hal, runtime/gb_hal_shims.asm).
    .section .crt0, "ax"
    .arm
    .global _start
_start:
    b   reset
    .fill 188, 1, 0          @ logo + header (not filled: emulators only)
reset:
    mov r0, #0x12            @ IRQ mode stack
    msr cpsr_c, r0
    ldr sp, =0x03007FA0
    mov r0, #0x1F            @ system mode
    msr cpsr_c, r0
    ldr sp, =0x03000F00      @ same initial SP as the transpiler (docs/memory_map.md)
    ldr r0, =__data_lma
    ldr r1, =__data_start
    ldr r2, =__data_end
1:  cmp r1, r2
    ldrlo r3, [r0], #4
    strlo r3, [r1], #4
    blo 1b
    ldr r1, =__bss_start
    ldr r2, =__bss_end
    mov r3, #0
2:  cmp r1, r2
    strlo r3, [r1], #4
    blo 2b
    ldr r0, =main
    bx  r0
