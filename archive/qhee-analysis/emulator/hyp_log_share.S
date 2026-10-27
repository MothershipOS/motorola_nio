/* SPDX-License-Identifier: MIT
 * Pinned QHEE diagnostic log: 0x80209000/8 KiB, VMID 4 -> 3 R + 4 RW.
 * Entry follows common exact SCM caller/buffer/source validation in smem_assign.S.
 * Synthetic ledger only. No real TrustZone implementation or access enforcement.
 */
replay_hyp_log_share:
    ldr w9, [x4]
    cmp w9, #4
    b.ne replay_unhandled
    ldr x9, [x2, #8]
    cmp x9, #0x2000
    b.ne replay_unhandled
    ldr x9, [x5, #16]
    cmp x9, #48
    b.ne replay_unhandled
    adr x0, hyp_log_share_ledger
    ldr x9, [x0]
    cmp x9, #16
    b.ne replay_unhandled
    ldr x9, [x0, #8]
    cbnz x9, replay_unhandled
    ldr x0, =0x8020b000
    adr x1, hyp_log_share_destinations
    mov x2, #6
1:  ldr x9, [x0], #8
    ldr x10, [x1], #8
    cmp x9, x10
    b.ne replay_unhandled
    subs x2, x2, #1
    b.ne 1b
    adr x0, hyp_log_share_ledger
    mov x9, #0x18
    mov x10, #0x10
    stp x9, x10, [x0]       // readers 3/4, writer 4 only
    dsb sy
    adr x0, hyp_log_share_message
    bl puts
    ldp x2, x3, [sp, #16]
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    mov x0, #0              // explicit assumed transport/service acceptance
    mov x1, #0
    eret
.balign 8
hyp_log_share_ledger:
    .quad 16, 0            // assumed initial owner 4, permissions unknown
hyp_log_share_destinations:
    .long 3, 4
    .quad 0
    .long 0, 0
    .long 4, 6
    .quad 0
    .long 0, 0
hyp_log_share_message:
    .asciz "MODEL_HYP_LOG_SHARE\n"
hyp_log_share_ledger_message:
    .asciz "MODEL_HYP_LOG_LEDGER_READERS_WRITERS:\n"
.balign 4
