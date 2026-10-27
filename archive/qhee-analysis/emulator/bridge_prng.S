/* SPDX-License-Identifier: MIT
 * Exact one-shot PRNG write for the allocator in the modeled SHM bridge.
 * Deterministic non-entropy input; requires the bridge already created.
 */
replay_bridge_prng:
    cmp x3, #8
    b.ne replay_unhandled
    mrs x9, elr_el3
    ldr x10, =0x80041aa4
    cmp x9, x10
    b.ne replay_unhandled
    cbnz x4, replay_unhandled
    cbnz x5, replay_unhandled
    cbnz x6, replay_unhandled
    cbnz x7, replay_unhandled
    adr x0, shm_bridge_ledger
    ldr x9, [x0]
    cmp x9, #1
    b.ne replay_unhandled
    adr x0, bridge_prng_count
    ldr x9, [x0]
    cbnz x9, replay_unhandled
    ldr x9, =BRIDGE_PRNG_MODEL_WORD
    str x9, [x2]
    mov x9, #1
    str x9, [x0]
    dsb sy
    adr x0, bridge_prng_message
    bl puts
    ldr x1, [sp, #8]
    ldp x2, x3, [sp, #16]
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    mov x0, #0
    eret
.balign 8
bridge_prng_count: .quad 0
bridge_prng_message: .asciz "MODEL_BRIDGE_PRNG_FIXED_WORD_NOT_ENTROPY\n"
.balign 4
