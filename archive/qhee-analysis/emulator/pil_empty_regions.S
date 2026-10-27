/* SPDX-License-Identifier: MIT
 * Explicit PIL empty-region-list experiment. No physical reply captured.
 * Original QHEE accepts zero returned length and exits its region-clear loop.
 */
replay_pil_empty_regions:
    cmp x1, #1
    b.ne replay_unhandled
    mrs x9, elr_el3
    ldr x10, =0x80041aa4
    cmp x9, x10
    b.ne replay_unhandled
    cbnz x2, replay_unhandled
    cbnz x3, replay_unhandled
    cbnz x4, replay_unhandled
    cbnz x5, replay_unhandled
    cbnz x6, replay_unhandled
    cbnz x7, replay_unhandled
    adr x0, pil_empty_regions_count
    ldr x9, [x0]
    cbnz x9, replay_unhandled
    mov x9, #1
    str x9, [x0]
    dsb sy
    adr x0, pil_empty_regions_message
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
pil_empty_regions_count: .quad 0
pil_empty_regions_message: .asciz "MODEL_PIL_EMPTY_REGION_LIST_ASSUMPTION\n"
pil_empty_regions_count_message: .asciz "MODEL_PIL_EMPTY_REGION_LIST_COUNT:\n"
.balign 4
