/* SPDX-License-Identifier: MIT
 * Exercise the optional register device at nonsecure EL2, including faults.
 */
.section .text
.global _start
_start:
    ldr x0, =0x403ff000
    mov sp, x0
    msr sp_el2, x0
    ldr x0, =0x501
    msr scr_el3, x0
    ldr x0, =0x80000000
    msr hcr_el2, x0
    ldr x0, =0x30c50830
    msr sctlr_el2, x0
    adr x0, vectors
    msr vbar_el2, x0
    adr x0, test
    msr elr_el3, x0
    mov x0, #0x3c9
    msr spsr_el3, x0
    isb
    eret
.balign 2048
vectors:
.rept 16
    b fault
    .balign 128
.endr
test:
#ifdef ADDRESS
    ldr x8, =ADDRESS
#else
    ldr x8, =0x01fc8000
#endif
#if ACCESS == 0
    ldr w19, [x8]
#elif ACCESS == 1
    str wzr, [x8]
#elif ACCESS == 2
    add x8, x8, #4
    ldr w19, [x8]
#elif ACCESS == 3
    ldrb w19, [x8]
#elif ACCESS == 4
    ldr x19, [x8]
#elif ACCESS == 5
    ldrh w19, [x8]
#elif ACCESS == 6
    ldr w19, =0x12340000
    str w19, [x8]
    ldr w19, [x8]
#elif ACCESS == 7
    strb wzr, [x8]
#elif ACCESS == 8
    str xzr, [x8]
#elif ACCESS == 9
    mov w19, #8
    str w19, [x8]
    mov w19, #1
    str w19, [x8]
    ldr w19, [x8]
#elif ACCESS == 10
    mov w19, #8
    str w19, [x8]
    str wzr, [x8]
    mov w19, #1
    str w19, [x8]
    ldr w19, [x8]
#elif ACCESS == 11
    ldr x19, =0x123456789abcdef0
    str x19, [x8]
    ldr x19, [x8]
#endif
    adr x0, read_message
    bl puts
    mov x0, x19
    bl hex64
    b exit
fault:
    mrs x19, esr_el2
    mrs x20, far_el2
    adr x0, fault_message
    bl puts
    mov x0, x19
    bl hex64
    mov x0, x20
    bl hex64
    b exit
puts:
    ldr x2, =0x09000000
1:  ldrb w1, [x0], #1
    cbz w1, 2f
    str w1, [x2]
    b 1b
2:  ret
hex64:
    mov x4, x0
    mov x5, #60
    ldr x2, =0x09000000
1:  lsr x1, x4, x5
    and x1, x1, #15
    cmp x1, #10
    add x3, x1, #48
    add x1, x1, #87
    csel x1, x3, x1, lo
    str w1, [x2]
    subs x5, x5, #4
    b.ge 1b
    mov w1, #10
    str w1, [x2]
    ret
exit:
    mov x0, #0x20
    adr x1, exit_block
    hlt #0xf000
    b exit
read_message: .asciz "READ\n"
fault_message: .asciz "ABORT\n"
.balign 8
exit_block: .quad 0x20026, 0
