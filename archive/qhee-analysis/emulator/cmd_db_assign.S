/* SPDX-License-Identifier: MIT
 * Pinned nio command-database region: 0x80860000/128 KiB, eight readers.
 * Entry follows common exact SCM caller/buffer/source validation in smem_assign.S.
 * Synthetic ledger only. No command-database contents or access enforcement.
 */
replay_cmd_db_assign:
    ldr x9, [x2, #8]
    cmp x9, #0x20000
    b.ne replay_unhandled
    ldr x9, [x5, #16]
    cmp x9, #192
    b.ne replay_unhandled
    adr x0, cmd_db_assign_ledger
    ldr x9, [x0]
    cmp x9, #8
    b.ne replay_unhandled
    ldr x9, [x0, #8]
    cbnz x9, replay_unhandled
    ldr x0, =0x8020b000
    adr x1, cmd_db_assign_destinations
    mov x2, #24
1:  ldr x9, [x0], #8
    ldr x10, [x1], #8
    cmp x9, x10
    b.ne replay_unhandled
    subs x2, x2, #1
    b.ne 1b
    adr x0, cmd_db_assign_ledger
    ldr x9, =0x4440006e
    stp x9, xzr, [x0]       // exact readers, no writers; VMID 3 retained read-only
    dsb sy
    adr x0, cmd_db_assign_message
    bl puts
    ldp x2, x3, [sp, #16]
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    mov x0, #0              // explicit assumed transport/service acceptance
    mov x1, #0
    eret
.balign 8
cmd_db_assign_ledger:
    .quad 8, 0             // assumed initial owner 3, permissions unknown
cmd_db_assign_destinations:
    .long 1, 4
    .quad 0
    .long 0, 0
    .long 2, 4
    .quad 0
    .long 0, 0
    .long 5, 4
    .quad 0
    .long 0, 0
    .long 3, 4
    .quad 0
    .long 0, 0
    .long 6, 4
    .quad 0
    .long 0, 0
    .long 26, 4
    .quad 0
    .long 0, 0
    .long 30, 4
    .quad 0
    .long 0, 0
    .long 22, 4
    .quad 0
    .long 0, 0
cmd_db_assign_message:
    .asciz "MODEL_CMD_DB_ASSIGN_READ_ONLY\n"
cmd_db_assign_ledger_message:
    .asciz "MODEL_CMD_DB_ASSIGN_LEDGER_READERS_WRITERS:\n"
.balign 4
