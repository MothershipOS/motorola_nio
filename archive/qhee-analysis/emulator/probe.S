/* SPDX-License-Identifier: MIT
 * Record the actual CurrentEL after an emulated exception return.
 */
.section .text
.global _start
_start:
    mrs x19, CurrentEL
    ldr x0, =0x09000000
    mov w1, #69
    str w1, [x0]
    mov w1, #76
    str w1, [x0]
    lsr x19, x19, #2
    add w1, w19, #48
    str w1, [x0]
    mov w1, #10
    str w1, [x0]
    cmp x19, #2
    b.ne done
    mrs x4, sctlr_el2
    mov x5, #60
hex_loop:
    lsr x1, x4, x5
    and x1, x1, #15
    cmp x1, #10
    add x2, x1, #48
    add x1, x1, #87
    csel x1, x2, x1, lo
    str w1, [x0]
    subs x5, x5, #4
    b.ge hex_loop
    mov w1, #10
    str w1, [x0]
done:
    mov x0, #0x20
    adr x1, exit_block
    hlt #0xf000
1:  wfe
    b 1b

.balign 8
exit_block: .quad 0x20026, 0
