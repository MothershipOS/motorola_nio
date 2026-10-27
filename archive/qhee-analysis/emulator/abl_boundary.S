/* SPDX-License-Identifier: MIT
 * Isolated original ABL preparation/launch fixture; no QHEE or full UEFI boot.
 */
.section .text
.global _start
_start:
    msr daifset, #15
    ldr x0, =0x403ff000
    mov sp, x0
    adr x0, faults
    msr vbar_el3, x0
    msr vbar_el2, x0
    msr vbar_el1, x0
    mov x0, #0x501
    msr scr_el3, x0
    mov x0, #0x80000000
    msr hcr_el2, x0
    ldr x0, =0x30c50830
    msr sctlr_el2, x0
    msr sctlr_el1, x0
    ldr x0, =0x92000000
    msr sp_el2, x0
    msr sp_el1, x0
    mov x0, #3
    msr cnthctl_el2, x0
    msr cntvoff_el2, xzr
#ifdef INITIAL_MMU_ON
    adr x0, identity_l1
    msr ttbr0_el2, x0
    msr ttbr0_el1, x0
    ldr x0, =0x80823519
    msr tcr_el2, x0
    ldr x0, =0x200803519
    msr tcr_el1, x0
    mov x0, #0xff00
    msr mair_el2, x0
    msr mair_el1, x0
    dsb sy
    isb
    ldr x0, =0x30c51835
    msr sctlr_el2, x0
    msr sctlr_el1, x0
#endif
    adr x0, boundary_entry
    msr elr_el3, x0
#if ENTRY_EL == 2
#ifdef INITIAL_DAIF_MASKED
    mov x0, #0x3c9
#else
    mov x0, #9
#endif
#else
#ifdef INITIAL_DAIF_MASKED
    mov x0, #0x3c5
#else
    mov x0, #5
#endif
#endif
    msr spsr_el3, x0
    isb
    eret
.global boundary_entry
boundary_entry:
    ldr x8, =0x9005e2e0
    blr x8
.global after_prepare
after_prepare:
    ldr x23, =0x92010000
    adr x8, kernel_probe
    stur x8, [x23, #-0x70]
    ldr x0, =0x93000000         // synthetic DTB-pointer token, no Linux boot
    stur x0, [x23, #-0x58]
    mov x1, #0x1111
    mov x2, #0x2222
    mov x3, #0x3333
    ldr x8, =0x90061da0
    br x8                     // original launch block, not its caller/UEFI
.global kernel_probe
kernel_probe:
    ldr x9, =0x93000000
    cmp x0, x9
    b.ne fail
    orr x9, x1, x2
    orr x9, x9, x3
    cbnz x9, fail
    mrs x19, CurrentEL
    lsr x19, x19, #2
#if ENTRY_EL == 2
    mrs x9, sctlr_el2
#else
    mrs x9, sctlr_el1
#endif
    mov x10, #0x1005
    tst x9, x10
    b.ne fail
    adr x1, message
    add w2, w19, #48
    strb w2, [x1, #2]
    mov x0, #4
    hlt #0xf000
    mov x0, #0x20
    adr x1, exit_block
    hlt #0xf000
fail:
    mov x0, #0x20
    adr x1, fail_block
    hlt #0xf000
1:  wfe
    b 1b
message: .asciz "EL?\n"
.balign 8
exit_block: .quad 0x20026, 0
fail_block: .quad 0x20026, 1
.balign 2048
faults:
.rept 16
    b fail
    .balign 128
.endr
.balign 4096
identity_l1:
    .quad 0x401
    .quad 0x40000705
    .quad 0x80000705
    .fill 509,8,0
