/* SPDX-License-Identifier: MIT
 * Pinned nio TZ-subsystem channel: 0x80ddc000/8 KiB, VMID 3 -> 21 + 42 RW.
 * Entry follows common exact SCM caller/buffer/source validation in smem_assign.S.
 * Synthetic ledger only. No real secure-channel contents or access enforcement.
 */
replay_tz_channel_21_42_assign:
    ldr x9, [x2, #8]
    cmp x9, #0x2000
    b.ne replay_unhandled
    ldr x9, [x5, #16]
    cmp x9, #48
    b.ne replay_unhandled
    adr x0, tz_channel_21_42_ledger
    ldr x9, [x0]
    cmp x9, #8
    b.ne replay_unhandled
    ldr x9, [x0, #8]
    cbnz x9, replay_unhandled
    ldr x0, =0x8020b000
    adr x1, tz_channel_21_42_destinations
    mov x2, #6
1:  ldr x9, [x0], #8
    ldr x10, [x1], #8
    cmp x9, x10
    b.ne replay_unhandled
    subs x2, x2, #1
    b.ne 1b
    adr x0, tz_channel_21_42_ledger
    ldr x9, =0x40000200000
    stp x9, x9, [x0]        // exact reader and writer sets; VMID 3 removed
    dsb sy
    adr x0, tz_channel_21_42_message
    bl puts
    ldp x2, x3, [sp, #16]
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    mov x0, #0              // explicit assumed transport/service acceptance
    mov x1, #0
    eret
.balign 8
tz_channel_21_42_ledger:
    .quad 8, 0             // assumed initial owner 3, permissions unknown
tz_channel_21_42_destinations:
    .long 21, 6
    .quad 0
    .long 0, 0
    .long 42, 6
    .quad 0
    .long 0, 0
tz_channel_21_42_message:
    .asciz "MODEL_TZ_CHANNEL_VMID21_42_ASSIGN\n"
tz_channel_21_42_ledger_message:
    .asciz "MODEL_TZ_CHANNEL_21_42_LEDGER_READERS_WRITERS:\n"
.balign 4
