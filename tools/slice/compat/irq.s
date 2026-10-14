@ Minimal GBA IRQ handler for the compat layer (ARM): acknowledges every pending
@ interrupt in IF and in the BIOS flags (0x03007FF8) so VBlankIntrWait (swi 5) returns.
@ Not transpiled: on the GB the HAL implements swi 5 itself and drops IE/IME writes.
    .section .text.compat_irq, "ax"
    .arm
    .global compat_irq_handler
compat_irq_handler:
    mov r0, #0x04000000
    add r0, r0, #0x200
    ldrh r1, [r0, #2]        @ IF
    strh r1, [r0, #2]        @ acknowledge
    ldr r2, =0x03007FF8
    ldrh r3, [r2]
    orr r3, r3, r1
    strh r3, [r2]
    bx lr
