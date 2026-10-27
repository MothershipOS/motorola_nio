/* SPDX-License-Identifier: MIT
 * Synthetic payload using QEMU semihosting; no guest MMIO permissions needed.
 * This is not a Linux payload or a phone firmware boot contract.
 */
.section .text
.global _start
_start:
    mrs x19, CurrentEL
    lsr x19, x19, #2
    adr x1, message
    add w2, w19, #48
    strb w2, [x1, #2]
    mov x0, #4                   // SYS_WRITE0
    hlt #0xf000
    mov x0, #0x20                // SYS_EXIT_EXTENDED
    adr x1, exit_block
    hlt #0xf000
1:  wfe
    b 1b
message: .asciz "EL?\n"
.balign 8
exit_block: .quad 0x20026, 0
