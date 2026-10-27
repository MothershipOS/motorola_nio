/* SPDX-License-Identifier: MIT
 * Synthetic EL3 fixture around unchanged original TZ monitor instructions.
 * Frame and system state are explicit offline inputs, not a phone capture.
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
    mov x0, #0x400           // secure AArch64 starting context
    msr scr_el3, x0
    ldr x0, =INITIAL_HCR
    msr hcr_el2, x0
    ldr x0, =0x30c50830
    msr sctlr_el2, x0
    msr sctlr_el1, x0
    ldr x0, =0x403ef000
    msr sp_el2, x0
    ldr x0, =0x403ee000
    msr sp_el1, x0
    mov x0, #0
    msr cptr_el3, x0
    ldr x8, =0x1c01e310
    blr x8                 // original context-layout initializer
.global after_layout_init
after_layout_init:
    ldr x0, =0x403d8000
    mov sp, x0             // synthetic saved SMC frame, preloaded
    ldr x8, =0x1c019200
    br x8                  // original SMC handler and final ERET
.global diagnostic_entry
diagnostic_entry:
    .inst 0xd503201f        // NOP: boundary is inspected before this executes
    b fail                 // tracer must terminate while paused
fail:
    mov x0, #0x20
    adr x1, fail_block
    hlt #0xf000
1:  wfe
    b 1b
.balign 8
fail_block: .quad 0x20026, 1
.balign 2048
.global faults
faults:
.rept 16
    b fail
    .balign 128
.endr
