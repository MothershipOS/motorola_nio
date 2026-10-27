/* SPDX-License-Identifier: MIT
 * One exact post-cold XBL query reply, derived from original TZ slices.
 * No entropy; no broad TZ service or policy implementation.
 */
replay_xbl_query:
    cmp x1, #1
    b.ne replay_unhandled
    ldr x9, =0x02000602
    cmp x2, x9
    b.ne replay_unhandled
    ldr x9, =0x9ffd0000
    cmp x3, x9
    b.ne replay_unhandled
    cbnz x4, replay_unhandled
    cbnz x7, replay_unhandled
    mrs x9, elr_el3
    cbnz x5, xbl_query_el2
    cbnz x6, replay_unhandled
    ldr x10, =0x80041cc0
    cmp x9, x10
    b.ne replay_unhandled
    b xbl_query_ready
xbl_query_el2:
    cmp x5, #1
    b.ne replay_unhandled
    ldr x10, =0x801cba78
    cmp x6, x10
    b.ne replay_unhandled
    ldr x10, =0x9fc284e0
    cmp x9, x10
    b.ne replay_unhandled
xbl_query_ready:
    adr x9, bridge_prng_count
    ldr x9, [x9]
    cmp x9, #1
    b.ne replay_unhandled
    adr x9, xbl_query_count
    ldr x10, [x9]
    cbnz x10, replay_unhandled
    mov x10, #1
    str x10, [x9]
    adr x0, xbl_query_message
    bl puts
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    mov x0, #0
    mov x1, #0
    mov x2, #0
    mov x3, #0
    eret
.balign 8
xbl_query_count: .quad 0
xbl_query_message: .asciz "MODEL_XBL_QUERY_ORIGINAL_TZ_SLICE_REPLY\n"
.balign 4
