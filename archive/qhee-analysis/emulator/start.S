/* SPDX-License-Identifier: MIT
 * Synthetic EL3 environment for offline QHEE experiments on QEMU virt.
 * Not a replacement for Motorola/Qualcomm TZ; unknown EL3 exceptions stop.
 */
#ifndef ENTRY_STATE_SCR_EL3
#define ENTRY_STATE_SCR_EL3 0x501
#define ENTRY_STATE_SPSR_EL3 0x3c9
#define ENTRY_STATE_SCTLR_EL2 0x30c50830
#define ENTRY_STATE_HCR_EL2 0x80000000
#endif
.section .text
.global _start
_start:
    msr daifset, #15
    ldr x0, =0x403ff000
    mov sp, x0
    adr x0, el3_vectors
    msr vbar_el3, x0
    ldr x0, =ENTRY_STATE_SCR_EL3 // Explicit model input, not measured bootstrap.
    msr scr_el3, x0
    ldr x0, =ENTRY_STATE_HCR_EL2
    msr hcr_el2, x0
    ldr x0, =ENTRY_STATE_SCTLR_EL2
    msr sctlr_el2, x0
    ldr x0, =0x803f0000
    msr sp_el2, x0
    mov x0, #3
    msr cnthctl_el2, x0
    msr cntvoff_el2, xzr
#ifdef SLICE_DISPATCH
#ifdef MMU_ON
    ldr x0, =el2_l1
    msr ttbr0_el2, x0
    ldr x0, =0x80823519
    msr tcr_el2, x0
    ldr x0, =0xff00
    msr mair_el2, x0
    dsb sy
    isb
    mrs x0, sctlr_el2
    orr x0, x0, #1
    orr x0, x0, #4
    msr sctlr_el2, x0
#endif
    ldr x0, =handoff_slice
#else
    ldr x0, =0x80040000
#endif
    msr elr_el3, x0
    mov x0, #ENTRY_STATE_SPSR_EL3
    msr spsr_el3, x0
#ifndef SYNTHETIC_PAYLOAD_ADDRESS
#define SYNTHETIC_PAYLOAD_ADDRESS 0x40400000
#endif
    ldr x0, =SYNTHETIC_PAYLOAD_ADDRESS // synthetic target, not actual XBL/TZ/ABL contract
    mov x1, #2                // AArch64 width
    mov x2, #0                // cold-boot argument: assumed
#ifdef SLICE_DISPATCH
    mov x21, x0
    mov x22, x1
    ldr x0, =0x40380000        // model a preserved payload argument
#endif
#ifdef ENTRY_STATE_DERIVED
    mov x3, #0                // original TZ frame's fourth argument
#endif
    isb
.global qhee_initial_eret
qhee_initial_eret:
    eret

.balign 2048
el3_vectors:
.rept 16
    b el3_fault
    .balign 128
.endr
el3_fault:
#if defined(SECURE_STATE_R1) || defined(PSCI_MODEL_VERSION) || defined(PRNG_MODEL_WORD) || defined(NONSECURE_QUERY_UNSUPPORTED) || defined(SMEM_TOC_ASSIGN_MODEL) || defined(PMIC_REGION_MAP_MODEL) || defined(PIL_EMPTY_REGIONS_MODEL) || defined(SHM_BRIDGE_MODEL_HANDLE)
    // Explicit replay of the recorded EL1-visible INFO/GET_SECURE_STATE reply.
    // This is a model input, not an implementation of Qualcomm TZ.
    stp x0, x1, [sp, #-64]!
    stp x2, x3, [sp, #16]
    stp x9, x10, [sp, #32]
    str x30, [sp, #48]
    mrs x9, esr_el3
    ldr x10, =0x5e000000
    cmp x9, x10
    b.ne replay_unhandled
    mrs x9, spsr_el3
    and x9, x9, #15
    cmp x9, #9               // only AArch64 EL2h caller in this harness
    b.ne replay_unhandled
#ifdef SECURE_STATE_R1
    ldr x9, =0x42000604
    cmp x0, x9
    b.eq replay_secure_state
#endif
#ifdef PSCI_MODEL_VERSION
    ldr x9, =0x84000000
    cmp x0, x9
    b.eq replay_psci_version
#endif
#ifdef PRNG_MODEL_WORD
    ldr x9, =0xc2000a02
    cmp x0, x9
    b.eq replay_prng
#endif
#ifdef NONSECURE_QUERY_UNSUPPORTED
    ldr x9, =0xc2000310
    cmp x0, x9
    b.eq replay_nonsecure_unsupported
#endif
#ifdef SMEM_TOC_ASSIGN_MODEL
    ldr x9, =0xc2000c16
    cmp x0, x9
    b.eq replay_smem_toc_assign
#endif
#ifdef PMIC_REGION_MAP_MODEL
    ldr x9, =0xc2000c19
    cmp x0, x9
    b.eq replay_pmic_region_map
#endif
#ifdef PIL_EMPTY_REGIONS_MODEL
    ldr x9, =0x4200020e
    cmp x0, x9
    b.eq replay_pil_empty_regions
#endif
#ifdef SHM_BRIDGE_MODEL_HANDLE
    ldr x9, =0xc2000c1e
    cmp x0, x9
    b.eq replay_shm_bridge
#endif
#ifdef XBL_QUERY_REPLY_MODEL
    ldr x9, =0x02000601
    cmp x0, x9
    b.eq replay_xbl_query
#endif
#ifdef XBL_BUFFER_REPLY_MODEL
    ldr x9, =0x02000a01
    cmp x0, x9
    b.eq replay_xbl_buffer
#endif
    b replay_unhandled
#ifdef XBL_BUFFER_REPLY_MODEL
#include "xbl_buffer.S"
#ifdef XBL_CANARY_REPLY_MODEL
#include "xbl_canary.S"
#endif
#endif
#ifdef XBL_QUERY_REPLY_MODEL
#include "xbl_query.S"
#endif
#ifdef SHM_BRIDGE_MODEL_HANDLE
#include "shm_bridge.S"
#endif
#ifdef PIL_EMPTY_REGIONS_MODEL
#include "pil_empty_regions.S"
#endif
#ifdef PMIC_REGION_MAP_MODEL
#include "pmic_region_map.S"
#endif
#ifdef SMEM_TOC_ASSIGN_MODEL
#include "smem_assign.S"
#endif
#ifdef NONSECURE_QUERY_UNSUPPORTED
replay_nonsecure_unsupported:
    cbnz x1, replay_unhandled
    // Exercise QHEE's existing failure branch; no device-security answer.
    adr x0, nonsecure_message
    bl puts
    ldr x1, [sp, #8]
    ldp x2, x3, [sp, #16]
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    mov x0, #-1
    eret
#endif
#ifdef PRNG_MODEL_WORD
replay_prng:
    cmp x1, #0x22
    b.ne replay_unhandled
    ldr x9, =0x80095a28       // only the three observed heap-init requests
    cmp x2, x9
    b.ne replay_prng_handoff_check
    cmp x3, #4
    b.ne replay_unhandled
    ldr w9, =PRNG_MODEL_WORD
    str w9, [x2]
    b replay_prng_done
replay_prng_handoff_check:
#ifdef BRIDGE_PRNG_MODEL_WORD
    ldr x9, =0x800ab090
    cmp x2, x9
    b.eq replay_bridge_prng
#endif
#ifdef HANDOFF_PRNG_MODEL
    ldr x9, =0x80095a60
    cmp x2, x9
    b.eq replay_handoff_prng
    ldr x9, =0x801ccaa8
    cmp x2, x9
    b.eq replay_handoff_prng
    add x9, x9, #2
    cmp x2, x9
    b.ne replay_prng_halfword
replay_handoff_prng:
    mrs x9, elr_el3
    ldr x10, =0x80041aa4
    cmp x9, x10
    b.ne replay_unhandled
    cbnz x4, replay_unhandled
    cbnz x5, replay_unhandled
    cbnz x6, replay_unhandled
    cbnz x7, replay_unhandled
    adr x0, handoff_prng_count
    ldr x1, [x0]
    cmp x1, #3
    b.hs replay_unhandled
    adr x9, handoff_prng_buffers
    add x9, x9, x1, lsl #4
    ldr x10, [x9]
    cmp x2, x10
    b.ne replay_unhandled
    ldr x10, [x9, #8]
    cmp x3, x10
    b.ne replay_unhandled
    ldr w9, =PRNG_MODEL_WORD
    cbnz x1, handoff_prng_halfword
    str w9, [x2]
    b handoff_prng_committed
handoff_prng_halfword:
    cmp x1, #2
    b.ne handoff_prng_halfword_low
    lsr w9, w9, #16
handoff_prng_halfword_low:
    strh w9, [x2]
handoff_prng_committed:
    add x1, x1, #1
    str x1, [x0]
    dsb sy
    adr x0, handoff_prng_message
    bl puts
    ldr x1, [sp, #8]
    ldp x2, x3, [sp, #16]
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    mov x0, #0
    eret
.balign 8
handoff_prng_count: .quad 0
handoff_prng_buffers:
    .quad 0x80095a60, 4
    .quad 0x801ccaa8, 2
    .quad 0x801ccaaa, 2
handoff_prng_message: .asciz "MODEL_HANDOFF_PRNG_FIXED_WORD_NOT_ENTROPY\n"
.balign 4
#endif
    b replay_prng_halfword     // do not fall through into an optional handler
#ifdef BRIDGE_PRNG_MODEL_WORD
#include "bridge_prng.S"
#endif
replay_prng_halfword:
    ldr x9, =0x801cc5d0
    cmp x2, x9
    b.eq replay_prng_halfword_low
    add x9, x9, #2
    cmp x2, x9
    b.ne replay_unhandled
    cmp x3, #2
    b.ne replay_unhandled
    ldr w9, =PRNG_MODEL_WORD
    lsr w9, w9, #16
    strh w9, [x2]
    b replay_prng_done
replay_prng_halfword_low:
    cmp x3, #2
    b.ne replay_unhandled
    ldr w9, =PRNG_MODEL_WORD
    strh w9, [x2]
replay_prng_done:
    dsb sy
    adr x0, prng_message
    bl puts
    ldr x1, [sp, #8]
    ldp x2, x3, [sp, #16]
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    mov x0, #0
    eret
#endif
#ifdef SECURE_STATE_R1
replay_secure_state:
    cbnz x1, replay_unhandled // no arguments; reject a different call contract
    adr x0, replay_message
    bl puts
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    mov x0, #0
    ldr x1, =SECURE_STATE_R1
    ldr x2, =SECURE_STATE_R2
    ldr x3, =SECURE_STATE_R3
    eret
#endif
#ifdef PSCI_MODEL_VERSION
replay_psci_version:
    adr x0, psci_message
    bl puts
    ldr x1, [sp, #8]
    ldp x2, x3, [sp, #16]
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    add sp, sp, #64
    ldr x0, =PSCI_MODEL_VERSION
    eret
#endif
replay_unhandled:
    ldp x2, x3, [sp, #16]
    ldp x9, x10, [sp, #32]
    ldr x30, [sp, #48]
    ldp x0, x1, [sp], #64
#endif
    mov x23, x0
    mov x24, x1
    mov x25, x2
    mov x26, x3
    mrs x19, esr_el3
    mrs x20, elr_el3
    mrs x21, far_el3
    mrs x22, spsr_el3
    adr x0, fault_message
    bl puts
    mov x0, x19
    bl hex64
    mov x0, x20
    bl hex64
    mov x0, x21
    bl hex64
    mov x0, x22
    bl hex64
    mov x0, x23
    bl hex64
    mov x0, x24
    bl hex64
    mov x0, x25
    bl hex64
    mov x0, x26
    bl hex64
#ifdef DUMP_QHEE_LOG
    adr x0, log_begin
    bl puts
    ldr x0, =0x80209200
    mov x6, #0x1e00
    bl puts_bounded
    adr x0, log_end
    bl puts
#endif
#ifdef SMEM_TOC_ASSIGN_MODEL
    adr x0, smem_ledger_message
    bl puts
    adr x0, smem_toc_ledger
    ldr x0, [x0]
    bl hex64
    adr x0, smem_toc_ledger
    ldr x0, [x0, #8]
    bl hex64
#endif
#ifdef SMEM_PARTITION_ASSIGN_MODEL
    adr x0, smem_partition_ledger_message
    bl puts
    adr x19, smem_partition_ledger
    mov x20, #10
1:  ldr x0, [x19, #48]
    bl hex64
    ldr x0, [x19, #56]
    bl hex64
    add x19, x19, #64
    subs x20, x20, #1
    b.ne 1b
#endif
#ifdef TZ_CHANNEL_ASSIGN_MODEL
    adr x0, tz_channel_ledger_message
    bl puts
    adr x0, tz_channel_ledger
    ldr x0, [x0]
    bl hex64
    adr x0, tz_channel_ledger
    ldr x0, [x0, #8]
    bl hex64
#endif
#ifdef TZ_CHANNEL_21_42_ASSIGN_MODEL
    adr x0, tz_channel_21_42_ledger_message
    bl puts
    adr x0, tz_channel_21_42_ledger
    ldr x0, [x0]
    bl hex64
    adr x0, tz_channel_21_42_ledger
    ldr x0, [x0, #8]
    bl hex64
#endif
#ifdef CMD_DB_ASSIGN_MODEL
    adr x0, cmd_db_assign_ledger_message
    bl puts
    adr x0, cmd_db_assign_ledger
    ldr x0, [x0]
    bl hex64
    adr x0, cmd_db_assign_ledger
    ldr x0, [x0, #8]
    bl hex64
#endif
#ifdef HYP_LOG_SHARE_MODEL
    adr x0, hyp_log_share_ledger_message
    bl puts
    adr x0, hyp_log_share_ledger
    ldr x0, [x0]
    bl hex64
    adr x0, hyp_log_share_ledger
    ldr x0, [x0, #8]
    bl hex64
#endif
#ifdef PMIC_REGION_MAP_MODEL
    adr x0, pmic_region_map_ledger_message
    bl puts
    adr x0, pmic_region_map_count
    ldr x0, [x0]
    bl hex64
#endif
#ifdef PIL_EMPTY_REGIONS_MODEL
    adr x0, pil_empty_regions_count_message
    bl puts
    adr x0, pil_empty_regions_count
    ldr x0, [x0]
    bl hex64
#endif
#ifdef SHM_BRIDGE_MODEL_HANDLE
    adr x0, shm_bridge_ledger_message
    bl puts
    adr x19, shm_bridge_ledger
    mov x20, #6
shm_bridge_dump:
    ldr x0, [x19], #8
    bl hex64
    subs x20, x20, #1
    b.ne shm_bridge_dump
#endif
    b exit
puts_bounded:
    ldr x2, =0x09000000
1:  cbz x6, 2f
    ldrb w1, [x0], #1
    cbz w1, 2f
    str w1, [x2]
    sub x6, x6, #1
    b 1b
2:  ret
puts:
    ldr x2, =0x09000000
1:  ldrb w1, [x0], #1
    cbz w1, 2f
    str w1, [x2]
    b 1b
2:  ret
hex64:
    mov x4, x0
    mov x5, #60
    ldr x2, =0x09000000
1:  lsr x1, x4, x5
    and x1, x1, #15
    cmp x1, #10
    add x3, x1, #48
    add x1, x1, #87
    csel x1, x3, x1, lo
    str w1, [x2]
    subs x5, x5, #4
    b.ge 1b
    mov w1, #10
    str w1, [x2]
    ret
exit:
    mov x0, #0x20
    adr x1, exit_block
    hlt #0xf000
    b exit
fault_message: .asciz "EL3_STOP ESR ELR FAR SPSR X0 X1 X2 X3:\n"
log_begin: .asciz "QHEE_LOG_BEGIN\n"
log_end: .asciz "\nQHEE_LOG_END\n"
replay_message: .asciz "MODEL_SECURE_STATE_REPLAY\n"
psci_message: .asciz "MODEL_PSCI_VERSION\n"
nonsecure_message: .asciz "MODEL_NONSECURE_QUERY_UNSUPPORTED\n"
prng_message: .asciz "MODEL_PRNG_FIXED_WORD_NOT_ENTROPY\n"

#ifdef SLICE_DISPATCH
.balign 4
handoff_slice:
    .incbin SLICE_DISPATCH
    // Firmware setup between these slices is intentionally NOT modeled.
#ifdef CLEAR_MC
    mrs x6, sctlr_el2
    bic x6, x6, #1
    bic x6, x6, #4
    dsb sy
    msr sctlr_el2, x6
    isb
#endif
    .incbin SLICE_TAIL
.balign 4096
el2_l1:
    .quad 0x401
    .quad 0x40000705
    .quad 0x80000705
    .fill 509, 8, 0
#endif

.balign 8
exit_block: .quad 0x20026, 0
