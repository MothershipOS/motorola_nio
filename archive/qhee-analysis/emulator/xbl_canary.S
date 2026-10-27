/* SPDX-License-Identifier: MIT
 * Second original XBL buffer request only. Repeated synthetic FIFO bytes;
 * not entropy, production canary randomness or physical secure acceptance.
 */
replay_xbl_canary:
    cmp x1, #0x22
    b.ne replay_unhandled
    ldr x9, =0x9fc356c0
    cmp x2, x9
    b.ne replay_unhandled
    cmp x3, #8
    b.ne replay_unhandled
    cmp x4, #7
    b.ne replay_unhandled
    cmp x5, #0x1d
    b.ne replay_unhandled
    mrs x9, elr_el3
    ldr x10, =0x80041aa4
    cmp x9, x10
    b.eq xbl_canary_stock
    ldr x10, =0x9fc2846c
    cmp x9, x10
    b.ne replay_unhandled
    ldr x10, =0x82000023
    cmp x6, x10
    b.ne replay_unhandled
    cmn x7, #1
    b.ne replay_unhandled
    mrs x9, sp_el2
    ldr x10, =0x9ffcfce0
    cmp x9, x10
    b.ne replay_unhandled
    mrs x9, sctlr_el2
    b xbl_canary_cache
xbl_canary_stock:
    cbnz x6, replay_unhandled
    cmp x7, #3
    b.ne replay_unhandled
    mrs x9, sp_el2
    ldr x10, =0x80208db0
    cmp x9, x10
    b.ne replay_unhandled
    mrs x9, sctlr_el1
xbl_canary_cache:
    ldr x10, =0x1005
    and x9, x9, x10
    mov x10, #0x1004
    cmp x9, x10
    b.ne replay_unhandled
    adr x9, bridge_prng_count
    ldr x9, [x9]
    cmp x9, #1
    b.ne replay_unhandled
    adr x9, xbl_query_count
    ldr x9, [x9]
    cmp x9, #1
    b.ne replay_unhandled
    adr x9, xbl_buffer_count
    ldr x9, [x9]
    cmp x9, #1
    b.ne replay_unhandled
    adr x9, xbl_canary_count
    ldr x10, [x9]
    cbnz x10, replay_unhandled
    ldr x10, [x2]
    cbnz x10, replay_unhandled
    ldr x10, [x2, #8]
    cmp x10, #0x10
    b.ne replay_unhandled
    ldr x10, =0x9fc3d710
    ldr x10, [x10]
    ldr x9, =XBL_CANARY_FIRST_SHIFTED_CACHE
    cmp x10, x9
    b.ne replay_unhandled
    ldr x9, =0x9fc350a8
    ldr x9, [x9]
    ldr x10, =0xc0c0c0c0
    cmp x9, x10
    b.ne replay_unhandled
    adr x9, xbl_canary_count
    mov x10, #1
    str x10, [x9]
    ldr x10, =XBL_CANARY_FIXTURE_WORD
    str x10, [x2]
    dsb sy
    adr x0, xbl_canary_message
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
xbl_canary_count: .quad 0
xbl_canary_message: .asciz "MODEL_XBL_CANARY_SECOND_BUFFER_SYNTHETIC_FIFO_NOT_ENTROPY\n"
.balign 4
