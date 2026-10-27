/* SPDX-License-Identifier: MIT
 * Finite scalar SCM 0xc2000c19 response experiment. Initial mappings unknown.
 * Records only VMID2 RW mapping additions; no ownership transfer/enforcement.
 * Common EL3 entry validates SMC #0 and EL2h and saves clobbered GPRs.
 */
replay_pmic_region_map:
    cmp x1, #5
    b.ne replay_unhandled
    mrs x9, elr_el3
    ldr x10, =0x80041aa4
    cmp x9, x10
    b.ne replay_unhandled
    cmp x4, #2
    b.ne replay_unhandled
    ldr x9, =0x801cc390
    cmp x5, x9
    b.ne replay_unhandled
    cbnz x6, replay_unhandled
    cbnz x7, replay_unhandled
    // Only the two actual extended arguments; trailing buffer bytes unused.
    ldr x9, [x5]
    cmp x9, #6
    b.ne replay_unhandled
    ldr x9, [x5, #8]
    cmp x9, #1
    b.ne replay_unhandled
    adr x0, pmic_region_map_count
    ldr x9, [x0]
    cmp x9, #PMIC_REGION_MAP_COUNT
    b.hs replay_unhandled
    adr x1, pmic_region_map_regions
    add x1, x1, x9, lsl #4
    ldr x10, [x1]
    cmp x2, x10
    b.ne replay_unhandled
    ldr x10, [x1, #8]
    cmp x3, x10
    b.ne replay_unhandled
    adr x1, pmic_region_map_ledger
    add x1, x1, x9, lsl #3
    ldr x10, [x1]
    cbnz x10, replay_unhandled
    mov x10, #6
    str x10, [x1]           // recorded VMID2 RW addition only
    add x9, x9, #1
    str x9, [x0]
    dsb sy
    adr x0, pmic_region_map_message
    bl puts
    ldp x2, x3, [sp, #16]
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    mov x0, #0              // explicit assumed transport and service success
    mov x1, #0
    eret
.balign 8
#include "pmic_region_map_table.S"
pmic_region_map_count: .quad 0
pmic_region_map_ledger: .fill PMIC_REGION_MAP_COUNT, 8, 0
pmic_region_map_message: .asciz "MODEL_PMIC_REGION_MAP_VMID2_RW\n"
pmic_region_map_ledger_message: .asciz "MODEL_PMIC_REGION_MAP_ACCEPTED_COUNT:\n"
.balign 4
