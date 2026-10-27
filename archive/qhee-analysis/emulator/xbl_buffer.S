/* SPDX-License-Identifier: MIT
 * Exact original-slice status/count with synthetic FIFO fixture bytes.
 * Ownership, setup, cache completion and monitor return remain assumptions.
 */
replay_xbl_buffer:
#ifdef XBL_CANARY_REPLY_MODEL
    adr x9, xbl_buffer_count
    ldr x9, [x9]
    cmp x9, #1
    b.eq replay_xbl_canary
#endif
    cmp x1, #0x22
    b.ne replay_unhandled
    ldr x9, =0x9fc356c0
    cmp x2, x9
    b.ne replay_unhandled
    cmp x3, #8
    b.ne replay_unhandled
    cbnz x4, replay_unhandled
    mrs x9, elr_el3
    cbnz x5, xbl_buffer_el2
    cbnz x6, replay_unhandled
    cmp x7, #3
    b.ne replay_unhandled
    ldr x10, =0x80041aa4
    cmp x9, x10
    b.ne replay_unhandled
    b xbl_buffer_ready
xbl_buffer_el2:
    cbnz x7, replay_unhandled
    cmp x5, #1
    b.ne replay_unhandled
    ldr x10, =0x801cba78
    cmp x6, x10
    b.ne replay_unhandled
    ldr x10, =0x9fc2846c
    cmp x9, x10
    b.ne replay_unhandled
xbl_buffer_ready:
    adr x9, bridge_prng_count
    ldr x9, [x9]
    cmp x9, #1
    b.ne replay_unhandled
    adr x9, xbl_query_count
    ldr x9, [x9]
    cmp x9, #1
    b.ne replay_unhandled
    adr x9, xbl_buffer_count
    ldr x10, [x9]
    cbnz x10, replay_unhandled
    ldr x10, [x2]
    cbnz x10, replay_unhandled
    ldr x10, [x2, #8]
    cmp x10, #0x10
    b.ne replay_unhandled
    ldr x10, =0x9fc3d710
    ldr x10, [x10]
    cbnz x10, replay_unhandled
    mov x10, #1
    str x10, [x9]
    ldr x10, =XBL_BUFFER_FIXTURE_WORD
    str x10, [x2]
    dsb sy
    adr x0, xbl_buffer_message
    bl puts
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    mov x0, #0
    mov x1, #8
    mov x2, #0
    mov x3, #0
    eret
.balign 8
xbl_buffer_count: .quad 0
xbl_buffer_message: .asciz "MODEL_XBL_BUFFER_ORIGINAL_SLICES_SYNTHETIC_FIFO_NOT_ENTROPY\n"
.balign 4
