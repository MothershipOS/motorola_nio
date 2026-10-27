/* SPDX-License-Identifier: MIT
 * Exact one-shot cold-entry SHM bridge response experiment. No physical TZ
 * reply, ownership enforcement, or bridge memory transactions are modeled.
 * Common entry requires EL2h and SMC #0 and saves clobbered registers.
 */
replay_shm_bridge:
    cmp x1, #4
    b.ne replay_unhandled
    mrs x9, elr_el3
    ldr x10, =0x80041aa4
    cmp x9, x10
    b.ne replay_unhandled
    ldr x9, =0x800ab000
    cmp x2, x9
    b.ne replay_unhandled
    add x9, x9, #4
    cmp x3, x9
    b.ne replay_unhandled
    ldr x9, =0x1001a
    cmp x4, x9
    b.ne replay_unhandled
    cbnz x5, replay_unhandled
    cbnz x6, replay_unhandled
    cbnz x7, replay_unhandled
    adr x0, shm_bridge_ledger
    ldr x9, [x0]
    cbnz x9, replay_unhandled
    mov x9, #1
    str x9, [x0]
    stp x2, x3, [x0, #8]
    stp x4, x5, [x0, #24]
    ldr x9, =SHM_BRIDGE_MODEL_HANDLE
    str x9, [x0, #40]
    dsb sy
    adr x0, shm_bridge_message
    bl puts
    ldr x3, [sp, #24]
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    mov x0, #0           // assumed transport success
    mov x1, #0           // assumed service success
    ldr x2, =SHM_BRIDGE_MODEL_HANDLE  // opaque synthetic token, not a pointer
    eret
.balign 8
shm_bridge_ledger: .fill 6, 8, 0
shm_bridge_message: .asciz "MODEL_SHM_BRIDGE_CREATE_ASSUMED_SUCCESS\n"
shm_bridge_ledger_message: .asciz "MODEL_SHM_BRIDGE_LEDGER_CREATED_INPUTS_HANDLE:\n"
.balign 4
