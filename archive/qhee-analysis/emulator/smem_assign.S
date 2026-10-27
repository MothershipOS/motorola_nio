/* SPDX-License-Identifier: MIT
 * Exact observed SMEM TOC ownership transition. Included by start.S.
 * Synthetic ledger only: no TZ enforcement, DMA or caller page-table edits.
 * x0..x3, x9, x10 and x30 are saved by el3_fault; other GPRs stay untouched.
 */
replay_smem_toc_assign:
    ldr x9, =0x1117
    cmp x1, x9
    b.ne replay_unhandled
    mrs x9, elr_el3
    ldr x10, =0x80041aa4       // pinned QHEE SMC #0 wrapper
    cmp x9, x10
    b.ne replay_unhandled
    ldr x9, =0x8020c000
    cmp x2, x9
    b.ne replay_unhandled
    cmp x3, #16
    b.ne replay_unhandled
    ldr x9, =0x8020d000
    cmp x4, x9
    b.ne replay_unhandled
    ldr x9, =0x801cc390
    cmp x5, x9
    b.ne replay_unhandled
    cbnz x6, replay_unhandled
    cbnz x7, replay_unhandled
    // Check fixed extended buffer before dereferencing either indirect buffer.
    ldr x9, [x5]
    cmp x9, #4
    b.ne replay_unhandled
    ldr x9, [x5, #8]
    ldr x10, =0x8020b000
    cmp x9, x10
    b.ne replay_unhandled
    ldr x9, [x5, #24]
    cbnz x9, replay_unhandled
#ifdef HYP_LOG_SHARE_MODEL
    ldr x9, [x2]
    ldr x10, =0x80209000
    cmp x9, x10
    b.eq replay_hyp_log_share
#endif
    ldr w9, [x4]
    cmp w9, #3
    b.ne replay_unhandled
    ldr x9, [x2]
#ifdef CMD_DB_ASSIGN_MODEL
    ldr x10, =0x80860000
    cmp x9, x10
    b.eq replay_cmd_db_assign
#endif
#ifdef TZ_CHANNEL_21_42_ASSIGN_MODEL
    ldr x10, =0x80ddc000
    cmp x9, x10
    b.eq replay_tz_channel_21_42_assign
#endif
#ifdef TZ_CHANNEL_ASSIGN_MODEL
    ldr x10, =0x80dc1000
    cmp x9, x10
    b.eq replay_tz_channel_assign
#endif
#ifdef SMEM_PARTITION_ASSIGN_MODEL
    ldr x10, =0x80aff000
    cmp x9, x10
    b.ne replay_smem_partition_assign
#endif
    ldr x9, [x5, #16]
    cmp x9, #192
    b.ne replay_unhandled
    ldr x9, [x2]
    ldr x10, =0x80aff000
    cmp x9, x10
    b.ne replay_unhandled
    ldr x9, [x2, #8]
    cmp x9, #0x1000
    b.ne replay_unhandled
    ldr w9, [x4]
    cmp w9, #3
    b.ne replay_unhandled
    adr x0, smem_toc_ledger
    ldr x9, [x0]
    cmp x9, #8              // current owner set must be exactly VMID 3
    b.ne replay_unhandled
    ldr x9, [x0, #8]
    cbnz x9, replay_unhandled // initial permissions unknown (sentinel zero)
    // Match every byte, including reserved/context fields, of eight records.
    ldr x0, =0x8020b000
    adr x1, smem_toc_destinations
    mov x2, #24
1:  ldr x9, [x0], #8
    ldr x10, [x1], #8
    cmp x9, x10
    b.ne replay_unhandled
    subs x2, x2, #1
    b.ne 1b
    // Commit only after all validation. A repeated stale-owner call is denied.
    adr x0, smem_toc_ledger
    ldr x9, =0x1004c000078
    mov x10, #4             // all eight owners have read permission only
    stp x9, x10, [x0]
    dsb sy
    adr x0, smem_assign_message
    bl puts
    ldp x2, x3, [sp, #16]
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    mov x0, #0              // SCM transport success, model assumption
    mov x1, #0              // service result success, model assumption
    eret

.balign 8
smem_toc_ledger:
    .quad 8, 0             // owner bitmap, uniform permission (0 = unknown)
smem_toc_destinations:
    .irp vmid, 3, 6, 5, 30, 27, 4, 40, 26
    .long \vmid, 4
    .quad 0
    .long 0, 0
    .endr
smem_assign_message:
    .asciz "MODEL_SMEM_TOC_ASSIGN_READ_ONLY_8_OWNERS\n"
smem_ledger_message:
    .asciz "MODEL_SMEM_TOC_LEDGER_OWNERS_PERMISSIONS:\n"

.balign 4

#ifdef SMEM_PARTITION_ASSIGN_MODEL
replay_smem_partition_assign:
    ldr x1, [x2]
    ldr x2, [x2, #8]
    adr x0, smem_partition_ledger
    mov x3, #10
1:  ldr x9, [x0]
    cmp x9, x1
    b.ne 2f
    ldr x9, [x0, #8]
    cmp x9, x2
    b.eq 3f
2:  add x0, x0, #64
    subs x3, x3, #1
    b.ne 1b
    b replay_unhandled
3:  ldr x9, [x0, #48]
    cmp x9, #8
    b.ne replay_unhandled
    ldr x9, [x0, #56]
    cbnz x9, replay_unhandled
    ldr x1, [x0, #40]
    ldr x9, [x5, #16]
    cmp x9, x1
    b.ne replay_unhandled
    lsr x1, x1, #3
    ldr x2, =0x8020b000
    ldr x3, [x0, #32]
4:  ldr x9, [x2], #8
    ldr x10, [x3], #8
    cmp x9, x10
    b.ne replay_unhandled
    subs x1, x1, #1
    b.ne 4b
    ldp x9, x10, [x0, #16]
    stp x9, x10, [x0, #48]
    dsb sy
    adr x0, smem_partition_assign_message
    bl puts
    ldp x2, x3, [sp, #16]
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    mov x0, #0
    mov x1, #0
    eret
.balign 8
// Exact captured partition layout and original-QHEE destination contracts.
// Record: start, size, readers, writers, destinations, bytes, current readers,
// current writers (zero initially means unknown, not measured read-only).
#include "smem_partitions.S"
smem_partition_ledger_message:
    .asciz "MODEL_SMEM_PARTITION_LEDGER_READERS_WRITERS:\n"
smem_partition_assign_message:
    .asciz "MODEL_SMEM_PARTITION_ASSIGN_EXACT\n"
.balign 4
#endif

#ifdef TZ_CHANNEL_ASSIGN_MODEL
#include "tz_channel_assign.S"
#endif

#ifdef TZ_CHANNEL_21_42_ASSIGN_MODEL
#include "tz_channel_21_42_assign.S"
#endif

#ifdef CMD_DB_ASSIGN_MODEL
#include "cmd_db_assign.S"
#endif

#ifdef HYP_LOG_SHARE_MODEL
#include "hyp_log_share.S"
#endif
