/* SPDX-License-Identifier: MIT
 * Emulator-only CPU0/AArch64 cold-path terminal replacement at 0x800402b0.
 * Entry: masked DAIF, or MASK_ENTRY variant masks it before maintenance.
 * Identity Normal-memory mappings are verified by the tracer.
 * No stack access. Cleans QHEE image/BSS and one finite payload range.
 * Does not clean every boot-chain allocation or implement a physical handoff.
 */
.section .text
.global _start
_start:
.if MASK_ENTRY
    msr daifset, #15
.endif
    mrs x0, ctr_el0
    ubfx x0, x0, #16, #4
    mov x3, #4
    lsl x0, x3, x0               // minimum D-cache line size, bytes
    mov x1, #0x80040000
 .if MASK_ENTRY
    add x2, x1, #0x24b, lsl #12 // saves one instruction for initial DAIF mask
.else
    mov x2, #0x80280000
    movk x2, #0xb000             // pinned QHEE memsz end, exclusive
.endif
1:  dc cvac, x1
    add x1, x1, x0
    cmp x1, x2
    b.lo 1b
.if XBL_PREFIX
    mov x1, #0x9fc00000
    add x2, x1, #0x300, lsl #12 // original pinned XBL FV, 3 MiB
.else
    mov x1, #0x90000000
    add x2, x1, #0x1000
.endif
2:  dc cvac, x1
    add x1, x1, x0
    cmp x1, x2
    b.lo 2b
    dsb sy
    ic iallu
    dsb sy
    isb
    mrs x4, sctlr_el2
    mov x3, #0x1005
    bic x4, x4, x3              // preserve other SCTLR bits; clear M/C/I
    msr sctlr_el2, x4
    isb
    mov x0, xzr                 // diagnostic has no DTB; not Linux entry
    mov x1, xzr
    mov x2, xzr
    mov x3, xzr
    eret                        // remains at original address 0x80040328
