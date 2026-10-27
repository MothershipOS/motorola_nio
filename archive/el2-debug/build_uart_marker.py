#!/usr/bin/env python3
"""Build a marker-only hyp candidate: stock QHEE + a GENI poll-TX stub that prints a
short marker over uart12 (0xa90000) at QHEE entry. NO EL2/SPSR change — this only
proves whether hyp can drive the debug UART (the stock XBL log shows uart12 is already
configured before QHEE loads; see el2-debug/uart/README.md).

Mechanics mirror qcom_geni_serial_poll_put_char (kernel CONSOLE_POLL path), which works
on an already-set-up SE:
  clear M_CMD_DONE; TX_TRANS_LEN=1; M_CMD0=UART_START_TX<<27; TX_FIFOn=char; poll M_CMD_DONE.

Hook: the `nop` at 0x80040040 (right after the bl-chain, before vbar/stack setup) is
replaced with `bl <stub>` into the zero cave at 0x80094684. The stub runs with the MMU
off and NO stack, so it is a leaf that saves x30 in x15 and uses only x9-x15 — it must
NOT touch x0-x3 (TZ boot args, read into x19-x22 at 0x80040074). It bounds every poll so
a later CPU can't hang if the UART is reconfigured.

Integrity: both edits are inside the code segment; the ELF code SHA-384 at 0x1138 is
recomputed so the image stays integrity-consistent. The OEM signature is left stale
(ignored on this engineering unit — kernel/EL2-hypb-nonboot-cause.md). Writes outside
backups/ only.
"""
import sys, struct, hashlib, subprocess, tempfile, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/hyp_re'))
from qhee import QheeImage  # noqa

ROOT = Path(__file__).resolve().parents[1]
STOCK = ROOT/'backups/nio-firmware-20260927T163534Z/hyp_b.img'
HASH_OFFSET = 0x1138
HOOK_VA = 0x80040040        # the `nop`
RETURN_VA = 0x80040044      # where the stub returns
STUB_VA = 0x80094684        # zero cave (0x9c4 bytes, verified)

UART_BASE = 0x00a90000      # uart12 serial@a90000

STUB_ASM = f"""
    .arch armv8-a
    .text
    .global _stub
_stub:
    mov     x15, x30                 // save return (no stack: MMU off, sp not set)
{{BASE_LOAD}}
    // ONE-SHOT GUARD. QHEE's entry runs on EVERY CPU power-on (secondaries,
    // resume), not just cold boot. uart12's QUP clock is gated at runtime, so a
    // secondary CPU poking 0xa90000 would hang the bus -> SMP stall. Only the
    // first cold-boot CPU0 (UART still clocked from XBL) may touch it. Flag lives
    // in the image (DDR); MMU off => Device/uncached => the write is seen by all
    // CPUs with no cache-coherency games. Reset to 0 on each cold boot (reload).
    adr     x14, oneshot
    ldrb    w10, [x14]
    cbnz    w10, finish              // already done this cold boot -> never touch UART again
    mov     w10, #1
    strb    w10, [x14]

    // --- reset the serial engine (kernel __qcom_geni_serial_cancel_tx_cmd) ---
    // XBL may leave a TX command active; a new UART_START_TX is ignored until
    // the old one is cancelled/aborted. This was the gap that made v2 silent.
    mov     w10, #4                  // M_GENI_CMD_CANCEL (bit2)
    str     w10, [x9, #0x604]        // SE_GENI_M_CMD_CTRL_REG
    movz    w11, #0x40, lsl #16
cwait:
    ldr     w10, [x9, #0x610]        // SE_GENI_M_IRQ_STATUS
    tbnz    w10, #4, cdone           // M_CMD_CANCEL_EN (bit4)
    subs    w11, w11, #1
    b.ne    cwait
    mov     w10, #2                  // cancel stuck -> M_GENI_CMD_ABORT (bit1)
    str     w10, [x9, #0x604]
    movz    w11, #0x40, lsl #16
awake:
    ldr     w10, [x9, #0x610]
    tbnz    w10, #5, adone           // M_CMD_ABORT_EN (bit5)
    subs    w11, w11, #1
    b.ne    awake
adone:
    mov     w10, #0x20
    str     w10, [x9, #0x618]        // clear M_CMD_ABORT_EN
cdone:
    mov     w10, #0x10
    str     w10, [x9, #0x618]        // clear M_CMD_CANCEL_EN

    // --- re-assert FIFO mode + TX packing (standard UART: 8bpw, 4x8, lsb) ---
    ldr     w10, [x9, #0x258]        // SE_GENI_DMA_MODE_EN
    bic     w10, w10, #1             // clear GENI_DMA_MODE_EN -> FIFO mode
    str     w10, [x9, #0x258]
    str     wzr, [x9, #0x254]        // SE_GENI_BYTE_GRAN = 0
    movz    w10, #0x380e
    movk    w10, #0x4, lsl #16       // 0x0004380e
    str     w10, [x9, #0x260]        // SE_GENI_TX_PACKING_CFG0
    movz    w10, #0x3e0e
    movk    w10, #0xc, lsl #16       // 0x000c3e0e
    str     w10, [x9, #0x264]        // SE_GENI_TX_PACKING_CFG1

    // --- print loop ---
    adr     x12, msg
nextc:
    ldrb    w13, [x12], #1
    cbz     w13, finish
    mov     w10, #1
    str     w10, [x9, #0x618]        // clear M_CMD_DONE
    mov     w10, #1
    str     w10, [x9, #0x270]        // SE_UART_TX_TRANS_LEN = 1
    movz    w10, #0x0800, lsl #16    // UART_START_TX(1) << M_OPCODE_SHFT(27) = 0x08000000
    str     w10, [x9, #0x600]        // SE_GENI_M_CMD0
    str     w13, [x9, #0x700]        // SE_GENI_TX_FIFOn = char
    movz    w11, #0x40, lsl #16      // ~4M-iter timeout (bounded; never hang)
poll:
    ldr     w10, [x9, #0x610]        // SE_GENI_M_IRQ_STATUS
    tbnz    w10, #0, pdone           // M_CMD_DONE_EN
    subs    w11, w11, #1
    b.ne    poll
pdone:
    mov     w10, #1
    str     w10, [x9, #0x618]        // clear M_CMD_DONE
    b       nextc
finish:
    br      x15                      // return to {RETURN_VA:#x}
    .balign 4
oneshot:
    .byte   0
    .balign 4
msg:
    .asciz  "HYP3\\r\\n"
"""

# Diagnostic stub: NO UART. One-shot guard, then a ~10s bounded busy-delay, then
# return. Used to prove whether cold-boot CPU0 actually executes the entry hook:
# if the boot visibly stalls ~10s at the QHEE stage, the stub runs (so a silent
# UART is the real problem); if boot is normal speed, the hook is not on the cold
# path. x9-x15 only; preserves x0-x3 (TZ boot args).
DELAY_ASM = """
    .arch armv8-a
    .text
    .global _stub
_stub:
    mov     x15, x30
    adr     x14, oneshot
    ldrb    w10, [x14]
    cbnz    w10, finish
    mov     w10, #1
    strb    w10, [x14]
    movz    x11, #0x3, lsl #32       // ~1.3e10 iters -> ~10s at ~1.5GHz
dloop:
    subs    x11, x11, #1
    b.ne    dloop
finish:
    br      x15
    .balign 4
oneshot:
    .byte   0
"""

# Probe stub: sends the marker to 0xa90000 exactly like 'uart' mode, but COUNTS how
# many bytes the TX engine reports complete (M_CMD_DONE) and makes the cold-boot
# busy-delay proportional to that count (count<<32 iters; 0 => no delay, never
# hang). Reads/writes only 0xa90000 (known clocked => safe). The UEFI-Start
# timestamp then reveals how many bytes actually transmitted:
#   normal speed  => 0 completed  => our TX sequence doesn't drive this SE
#   long stall    => N completed  => a90000 TX works; if FT232 still shows nothing
#                                    the adapter is on a different SE (e.g. 988000)
PROBE_ASM = f"""
    .arch armv8-a
    .text
    .global _stub
_stub:
    mov     x15, x30
{{BASE_LOAD}}
    adr     x14, oneshot
    ldrb    w10, [x14]
    cbnz    w10, finish
    mov     w10, #1
    strb    w10, [x14]
    // cancel/abort reset
    mov     w10, #4
    str     w10, [x9, #0x604]
    movz    w11, #0x40, lsl #16
cwait:
    ldr     w10, [x9, #0x610]
    tbnz    w10, #4, cdone
    subs    w11, w11, #1
    b.ne    cwait
    mov     w10, #2
    str     w10, [x9, #0x604]
    movz    w11, #0x40, lsl #16
awake:
    ldr     w10, [x9, #0x610]
    tbnz    w10, #5, adone
    subs    w11, w11, #1
    b.ne    awake
adone:
    mov     w10, #0x20
    str     w10, [x9, #0x618]
cdone:
    mov     w10, #0x10
    str     w10, [x9, #0x618]
    // fifo mode + packing
    ldr     w10, [x9, #0x258]
    bic     w10, w10, #1
    str     w10, [x9, #0x258]
    str     wzr, [x9, #0x254]
    movz    w10, #0x380e
    movk    w10, #0x4, lsl #16
    str     w10, [x9, #0x260]
    movz    w10, #0x3e0e
    movk    w10, #0xc, lsl #16
    str     w10, [x9, #0x264]
    // send loop, counting completions in x13
    mov     x13, #0
    adr     x12, msg
nextc:
    ldrb    w6, [x12], #1
    cbz     w6, afterloop
    mov     w10, #1
    str     w10, [x9, #0x618]
    mov     w10, #1
    str     w10, [x9, #0x270]
    movz    w10, #0x0800, lsl #16
    str     w10, [x9, #0x600]
    str     w6, [x9, #0x700]
    movz    w11, #0x40, lsl #16
poll:
    ldr     w10, [x9, #0x610]
    tbnz    w10, #0, pdone
    subs    w11, w11, #1
    b.ne    poll
    b       nextc                    // timed out: not counted
pdone:
    add     x13, x13, #1             // one byte completed
    mov     w10, #1
    str     w10, [x9, #0x618]
    b       nextc
afterloop:
    cbz     x13, finish              // nothing completed -> no delay
    lsl     x11, x13, #32            // delay ~ completions
dloop:
    subs    x11, x11, #1
    b.ne    dloop
finish:
    br      x15
    .balign 4
oneshot:
    .byte   0
    .balign 4
msg:
    .asciz  "HYP3\\r\\n"
"""

# Read-proto diagnostic: reads GENI_FW_REVISION_RO[15:8] (the SE's loaded protocol:
# 0=NONE,1=SPI,2=UART,3=I2C) from --base and makes the cold-boot delay = proto * ~10s.
# Safe only on a clocked base (a90000). The UEFI-Start timestamp then reveals proto:
# ~20s=>UART(base is a uart; sequence is the bug), ~30s=>I2C, normal=>unconfigured.
READPROTO_ASM = """
    .arch armv8-a
    .text
    .global _stub
_stub:
    mov     x15, x30
{BASE_LOAD}
    adr     x14, oneshot
    ldrb    w10, [x14]
    cbnz    w10, finish
    mov     w10, #1
    strb    w10, [x14]
    ldr     w10, [x9, #0x68]         // GENI_FW_REVISION_RO
    ubfx    w10, w10, #8, #8         // proto = bits[15:8]
    cbz     w10, finish              // proto 0 -> no delay
    mov     w11, w10                 // zero-extend proto into x11
    lsl     x11, x11, #31            // delay ~ proto * (2^31 iters ~10s)
dloop:
    subs    x11, x11, #1
    b.ne    dloop
finish:
    br      x15
    .balign 4
oneshot:
    .byte   0
"""

# EL2 fault-register dumper (run 04 -> fault capture). Triggered by overwriting QHEE's
# EL2 sync/current-EL vector (VBAR_EL2=0x80040330, +0x200=0x80040530) first instruction
# with `b dump_handler`. Paired with the SPSR EL1h->EL2h flip (@0x800401d8) so the HLOS
# target runs at EL2 and faults into this vector. Prints ESR/ELR/FAR/SPSR/HCR/SCTLR_EL2
# over uart12 (0x00A90000), then restores the original `stp` and chains to 0x80040534 so
# QHEE's own handler runs (it resets to EDL -> recover with unbrick/edl_usb.py). The UART
# output happens BEFORE that reset, so it survives (the DDR breadcrumb in run 03 did not).
# Runs at EL2 with SP_EL2 valid (QHEE's stack); preserves x0 and fault x30 for the chain.
FAULTDUMP_ASM = """
    .arch armv8-a
    .text
    .global _stub
// STACKLESS: at the handoff the EL2h target is ABL, which sets its own SP before
// faulting, so SP_EL2 is not usable for pushes. Uses NO stack and NO bl: putc returns
// via x16, puts/puthex via x17. Preserves x0 and x30 so the chain's original stp saves
// the real fault context. x9=uart base; x10/x11 scratch; x12 strptr; w13 char; x14 hexval;
// w15 nibble shift.
_stub:
dump_handler:
    movz    x9, #0xa9, lsl #16       // uart12 base 0x00A90000
    // --- GENI SE reset (cancel/abort) ---
    mov     w10, #4
    str     w10, [x9, #0x604]
    movz    w11, #0x40, lsl #16
hr1: ldr    w10, [x9, #0x610]
    tbnz    w10, #4, hr2
    subs    w11, w11, #1
    b.ne    hr1
    mov     w10, #2
    str     w10, [x9, #0x604]
    movz    w11, #0x40, lsl #16
hr3: ldr    w10, [x9, #0x610]
    tbnz    w10, #5, hr4
    subs    w11, w11, #1
    b.ne    hr3
hr4: mov    w10, #0x20
    str     w10, [x9, #0x618]
hr2: mov    w10, #0x10
    str     w10, [x9, #0x618]
    // --- fifo mode + TX packing ---
    ldr     w10, [x9, #0x258]
    bic     w10, w10, #1
    str     w10, [x9, #0x258]
    str     wzr, [x9, #0x254]
    movz    w10, #0x380e
    movk    w10, #0x4, lsl #16
    str     w10, [x9, #0x260]
    movz    w10, #0x3e0e
    movk    w10, #0xc, lsl #16
    str     w10, [x9, #0x264]
    // --- dump registers (adr x17,ret; b puts/puthex) ---
    adr     x12, m_hdr
    adr     x17, .+8
    b       puts
    adr     x12, m_esr
    adr     x17, .+8
    b       puts
    mrs     x14, esr_el2
    adr     x17, .+8
    b       puthex
    adr     x12, m_elr
    adr     x17, .+8
    b       puts
    mrs     x14, elr_el2
    adr     x17, .+8
    b       puthex
    adr     x12, m_far
    adr     x17, .+8
    b       puts
    mrs     x14, far_el2
    adr     x17, .+8
    b       puthex
    adr     x12, m_spsr
    adr     x17, .+8
    b       puts
    mrs     x14, spsr_el2
    adr     x17, .+8
    b       puthex
    adr     x12, m_hcr
    adr     x17, .+8
    b       puts
    mrs     x14, hcr_el2
    adr     x17, .+8
    b       puthex
    adr     x12, m_sctlr
    adr     x17, .+8
    b       puts
    mrs     x14, sctlr_el2
    adr     x17, .+8
    b       puthex
    adr     x12, m_end
    adr     x17, .+8
    b       puts
    // --- chain to QHEE's real sync-SPx handler (VBAR_EL2+0x200 was `b 0x8004126c`) ---
    movz    x16, #0x126c
    movk    x16, #0x8004, lsl #16    // 0x8004126c
    br      x16

// puts: x12=asciz ptr; returns via x17; calls putc via x16
puts:
ps1: ldrb   w13, [x12], #1
    cbz     w13, ps2
    adr     x16, .+8
    b       putc
    b       ps1
ps2: br     x17

// puthex: x14=value -> "0x"+16 hex; returns via x17; calls putc via x16
puthex:
    mov     w13, #0x30
    adr     x16, .+8
    b       putc                     // '0'
    mov     w13, #0x78
    adr     x16, .+8
    b       putc                     // 'x'
    mov     w15, #60
ph1: lsr    x13, x14, x15
    and     x13, x13, #0xf
    cmp     x13, #10
    b.lo    ph2
    add     w13, w13, #0x57
    b       ph3
ph2: add    w13, w13, #0x30
ph3: adr    x16, .+8
    b       putc
    subs    w15, w15, #4
    b.ge    ph1
    br      x17

// putc: w13=char; x9=uart base; returns via x16; leaf, no stack
putc:
    mov     w10, #1
    str     w10, [x9, #0x618]
    mov     w10, #1
    str     w10, [x9, #0x270]
    movz    w10, #0x0800, lsl #16
    str     w10, [x9, #0x600]
    str     w13, [x9, #0x700]
    movz    w11, #0x40, lsl #16
pc1: ldr    w10, [x9, #0x610]
    tbnz    w10, #0, pc2
    subs    w11, w11, #1
    b.ne    pc1
pc2: mov    w10, #1
    str     w10, [x9, #0x618]
    br      x16

    .balign 4
m_hdr:   .asciz "\\r\\n== EL2 FAULT ==\\r\\n"
m_esr:   .asciz "ESR_EL2 ="
m_elr:   .asciz "\\r\\nELR_EL2 ="
m_far:   .asciz "\\r\\nFAR_EL2 ="
m_spsr:  .asciz "\\r\\nSPSR_EL2="
m_hcr:   .asciz "\\r\\nHCR_EL2 ="
m_sctlr: .asciz "\\r\\nSCTLR_E2="
m_end:   .asciz "\\r\\n== END ==\\r\\n"
"""

# Handoff-state dumper. The SPSR->EL2h fault is caught at EL3 (no EL2 vector sees it),
# so instead we print the QHEE->HLOS handoff state just before the eret: ELR_EL2 (the ABL
# entry PA), SPSR/HCR/SCTLR_EL2, and the first 8 instruction words at the target. Hooked at
# 0x80040324 (`mov x30,xzr`, the last GPR-zero before the eret). NO SPSR flip -> boots
# normally. Stackless; preserves x0 (boot arg); re-zeros scratch regs; executes the original
# `mov x30,xzr` then branches to the eret at 0x80040328.
HANDOFFDUMP_ASM = """
    .arch armv8-a
    .text
    .global _stub
_stub:
ho:
    movz    x9, #0xa9, lsl #16
    mov     w10, #4
    str     w10, [x9, #0x604]
    movz    w11, #0x40, lsl #16
hr1: ldr    w10, [x9, #0x610]
    tbnz    w10, #4, hr2
    subs    w11, w11, #1
    b.ne    hr1
    mov     w10, #2
    str     w10, [x9, #0x604]
    movz    w11, #0x40, lsl #16
hr3: ldr    w10, [x9, #0x610]
    tbnz    w10, #5, hr4
    subs    w11, w11, #1
    b.ne    hr3
hr4: mov    w10, #0x20
    str     w10, [x9, #0x618]
hr2: mov    w10, #0x10
    str     w10, [x9, #0x618]
    ldr     w10, [x9, #0x258]
    bic     w10, w10, #1
    str     w10, [x9, #0x258]
    str     wzr, [x9, #0x254]
    movz    w10, #0x380e
    movk    w10, #0x4, lsl #16
    str     w10, [x9, #0x260]
    movz    w10, #0x3e0e
    movk    w10, #0xc, lsl #16
    str     w10, [x9, #0x264]
    adr     x12, h_elr
    adr     x17, .+8
    b       puts
    mrs     x14, elr_el2
    adr     x17, .+8
    b       puthex
    adr     x12, h_spsr
    adr     x17, .+8
    b       puts
    mrs     x14, spsr_el2
    adr     x17, .+8
    b       puthex
    adr     x12, h_hcr
    adr     x17, .+8
    b       puts
    mrs     x14, hcr_el2
    adr     x17, .+8
    b       puthex
    adr     x12, h_sctlr
    adr     x17, .+8
    b       puts
    mrs     x14, sctlr_el2
    adr     x17, .+8
    b       puthex
    adr     x12, h_ttbr0
    adr     x17, .+8
    b       puts
    mrs     x14, ttbr0_el2
    adr     x17, .+8
    b       puthex
    adr     x12, h_tcr
    adr     x17, .+8
    b       puts
    mrs     x14, tcr_el2
    adr     x17, .+8
    b       puthex
    adr     x12, h_mair
    adr     x17, .+8
    b       puts
    mrs     x14, mair_el2
    adr     x17, .+8
    b       puthex
    adr     x12, h_vttbr
    adr     x17, .+8
    b       puts
    mrs     x14, vttbr_el2
    adr     x17, .+8
    b       puthex
    adr     x12, h_vtcr
    adr     x17, .+8
    b       puts
    mrs     x14, vtcr_el2
    adr     x17, .+8
    b       puthex
    adr     x12, h_vbar
    adr     x17, .+8
    b       puts
    mrs     x14, vbar_el2
    adr     x17, .+8
    b       puthex
    adr     x12, h_tgt
    adr     x17, .+8
    b       puts
    mrs     x19, elr_el2             // target code ptr
    mov     w18, #8
htl: ldr    w14, [x19], #4
    adr     x17, .+8
    b       puthex
    adr     x12, h_sp
    adr     x17, .+8
    b       puts
    subs    w18, w18, #1
    b.ne    htl
    adr     x12, h_end
    adr     x17, .+8
    b       puts
    // re-zero scratch so the eret still hands off with x1-x30 = 0 (x0 preserved)
    mov     x9, xzr
    mov     x10, xzr
    mov     x11, xzr
    mov     x12, xzr
    mov     x13, xzr
    mov     x14, xzr
    mov     x15, xzr
    mov     x16, xzr
    mov     x17, xzr
    mov     x18, xzr
    mov     x19, xzr
    mov     x30, xzr                 // original overwritten instr
    movz    x16, #0x0328
    movk    x16, #0x8004, lsl #16    // 0x80040328 (eret)
    br      x16

puts:
ps1: ldrb   w13, [x12], #1
    cbz     w13, ps2
    adr     x16, .+8
    b       putc
    b       ps1
ps2: br     x17

puthex:
    mov     w13, #0x30
    adr     x16, .+8
    b       putc
    mov     w13, #0x78
    adr     x16, .+8
    b       putc
    mov     w15, #60
ph1: lsr    x13, x14, x15
    and     x13, x13, #0xf
    cmp     x13, #10
    b.lo    ph2
    add     w13, w13, #0x57
    b       ph3
ph2: add    w13, w13, #0x30
ph3: adr    x16, .+8
    b       putc
    subs    w15, w15, #4
    b.ge    ph1
    br      x17

putc:
    mov     w10, #1
    str     w10, [x9, #0x618]
    mov     w10, #1
    str     w10, [x9, #0x270]
    movz    w10, #0x0800, lsl #16
    str     w10, [x9, #0x600]
    str     w13, [x9, #0x700]
    movz    w11, #0x40, lsl #16
pc1: ldr    w10, [x9, #0x610]
    tbnz    w10, #0, pc2
    subs    w11, w11, #1
    b.ne    pc1
pc2: mov    w10, #1
    str     w10, [x9, #0x618]
    br      x16

    .balign 4
h_elr:   .asciz "\\r\\n== HANDOFF ==\\r\\nELR_EL2 ="
h_spsr:  .asciz "\\r\\nSPSR_EL2="
h_hcr:   .asciz "\\r\\nHCR_EL2 ="
h_sctlr: .asciz "\\r\\nSCTLR_E2="
h_ttbr0: .asciz "\\r\\nTTBR0_E2="
h_tcr:   .asciz "\\r\\nTCR_EL2 ="
h_mair:  .asciz "\\r\\nMAIR_E2 ="
h_vttbr: .asciz "\\r\\nVTTBR_E2="
h_vtcr:  .asciz "\\r\\nVTCR_EL2="
h_vbar:  .asciz "\\r\\nVBAR_EL2="
h_tgt:   .asciz "\\r\\nTGT[0..8]="
h_sp:    .asciz " "
h_end:   .asciz "\\r\\n== END ==\\r\\n"
"""

# Page-table dumper. Hooked at the handoff (0x80040324, no SPSR flip -> boots). Briefly
# clears SCTLR_EL2.M (EL2 MMU off) so EL2 reads are flat-physical, then dumps QHEE's own
# stage-1 (TTBR0_EL2) and stage-2 (VTTBR_EL2) translation tables over UART: the top table
# (64 entries, 4KB granule / 36-bit VA per TCR_EL2=0x8081351c) and the L2 table under the
# 2-3GB L1 entry (index 2) where 0x9fc00000 / 0xa16cd1dc / QHEE(0x80040000) all live. Walk
# offline. Restores SCTLR_EL2 and continues. Stackless; register-link subroutines
# (putc<-x16, puts/puthex<-x17, dumprow/dumpnz<-x23); scratch x24-x28; preserves x0.
PTDUMP_ASM = """
    .arch armv8-a
    .text
    .global _stub
_stub:
pt:
    movz    x9, #0xa9, lsl #16
    mov     w10, #4
    str     w10, [x9, #0x604]
    movz    w11, #0x40, lsl #16
hr1: ldr    w10, [x9, #0x610]
    tbnz    w10, #4, hr2
    subs    w11, w11, #1
    b.ne    hr1
    mov     w10, #2
    str     w10, [x9, #0x604]
    movz    w11, #0x40, lsl #16
hr3: ldr    w10, [x9, #0x610]
    tbnz    w10, #5, hr4
    subs    w11, w11, #1
    b.ne    hr3
hr4: mov    w10, #0x20
    str     w10, [x9, #0x618]
hr2: mov    w10, #0x10
    str     w10, [x9, #0x618]
    ldr     w10, [x9, #0x258]
    bic     w10, w10, #1
    str     w10, [x9, #0x258]
    str     wzr, [x9, #0x254]
    movz    w10, #0x380e
    movk    w10, #0x4, lsl #16
    str     w10, [x9, #0x260]
    movz    w10, #0x3e0e
    movk    w10, #0xc, lsl #16
    str     w10, [x9, #0x264]
    // mask for bits[47:12]
    movz    x24, #0xf000
    movk    x24, #0xffff, lsl #16
    movk    x24, #0xffff, lsl #32
    // EL2 MMU off (flat-physical reads)
    mrs     x20, sctlr_el2
    bic     x10, x20, #1
    msr     sctlr_el2, x10
    isb
    // header + context
    adr     x12, p_hdr
    adr     x17, .+8
    b       puts
    mrs     x14, ttbr0_el2
    adr     x17, .+8
    b       puthex
    adr     x12, p_tcr
    adr     x17, .+8
    b       puts
    mrs     x14, tcr_el2
    adr     x17, .+8
    b       puthex
    // --- stage-1 L1 (64 entries) ---
    adr     x12, p_s1l1
    adr     x17, .+8
    b       puts
    mrs     x19, ttbr0_el2
    and     x19, x19, x24
    mov     w18, #64
    adr     x23, .+8
    b       dumprow
    // follow L1[2] -> stage-1 L2
    mrs     x19, ttbr0_el2
    and     x19, x19, x24
    ldr     x21, [x19, #16]
    and     x22, x21, x24
    adr     x12, p_s1l2
    adr     x17, .+8
    b       puts
    mov     x14, x22
    adr     x17, .+8
    b       puthex
    adr     x12, p_colon
    adr     x17, .+8
    b       puts
    mov     x19, x22
    movz    w18, #0x200
    adr     x23, .+8
    b       dumpnz
    // --- stage-2 ---
    adr     x12, p_vttbr
    adr     x17, .+8
    b       puts
    mrs     x14, vttbr_el2
    adr     x17, .+8
    b       puthex
    adr     x12, p_vtcr
    adr     x17, .+8
    b       puts
    mrs     x14, vtcr_el2
    adr     x17, .+8
    b       puthex
    adr     x12, p_s2l1
    adr     x17, .+8
    b       puts
    mrs     x19, vttbr_el2
    and     x19, x19, x24
    mov     w18, #64
    adr     x23, .+8
    b       dumprow
    mrs     x19, vttbr_el2
    and     x19, x19, x24
    ldr     x21, [x19, #16]
    and     x22, x21, x24
    adr     x12, p_s2l2
    adr     x17, .+8
    b       puts
    mov     x14, x22
    adr     x17, .+8
    b       puthex
    adr     x12, p_colon
    adr     x17, .+8
    b       puts
    mov     x19, x22
    movz    w18, #0x200
    adr     x23, .+8
    b       dumpnz
    adr     x12, p_end
    adr     x17, .+8
    b       puts
    // restore EL2 MMU + continue
    msr     sctlr_el2, x20
    isb
    mov     x30, xzr
    movz    x16, #0x0328
    movk    x16, #0x8004, lsl #16
    br      x16

// dumprow: x19 base, w18 count -> all entries "val " ; link x23
dumprow:
    mov     x25, x19
    mov     w26, w18
dr1: cbz    w26, dr2
    ldr     x14, [x25], #8
    adr     x17, .+8
    b       puthex
    mov     w13, #0x20
    adr     x16, .+8
    b       putc
    sub     w26, w26, #1
    b       dr1
dr2: br     x23

// dumpnz: x19 base, w18 count -> nonzero "idx=val " ; link x23
dumpnz:
    mov     x25, x19
    mov     w26, w18
    mov     w27, #0
dn1: cbz    w26, dn2
    ldr     x28, [x25], #8
    cbz     x28, dn3
    uxtw    x14, w27
    adr     x17, .+8
    b       puthex
    mov     w13, #0x3d
    adr     x16, .+8
    b       putc
    mov     x14, x28
    adr     x17, .+8
    b       puthex
    mov     w13, #0x20
    adr     x16, .+8
    b       putc
dn3: add    w27, w27, #1
    sub     w26, w26, #1
    b       dn1
dn2: br     x23

puts:
ps1: ldrb   w13, [x12], #1
    cbz     w13, ps2
    adr     x16, .+8
    b       putc
    b       ps1
ps2: br     x17

puthex:
    mov     w13, #0x30
    adr     x16, .+8
    b       putc
    mov     w13, #0x78
    adr     x16, .+8
    b       putc
    mov     w15, #60
ph1: lsr    x13, x14, x15
    and     x13, x13, #0xf
    cmp     x13, #10
    b.lo    ph2
    add     w13, w13, #0x57
    b       ph3
ph2: add    w13, w13, #0x30
ph3: adr    x16, .+8
    b       putc
    subs    w15, w15, #4
    b.ge    ph1
    br      x17

putc:
    mov     w10, #1
    str     w10, [x9, #0x618]
    mov     w10, #1
    str     w10, [x9, #0x270]
    movz    w10, #0x0800, lsl #16
    str     w10, [x9, #0x600]
    str     w13, [x9, #0x700]
    movz    w11, #0x40, lsl #16
pc1: ldr    w10, [x9, #0x610]
    tbnz    w10, #0, pc2
    subs    w11, w11, #1
    b.ne    pc1
pc2: mov    w10, #1
    str     w10, [x9, #0x618]
    br      x16

    .balign 4
p_hdr:   .asciz "\\r\\n== PTDUMP ==\\r\\nTTBR0_E2="
p_tcr:   .asciz "\\r\\nTCR_EL2 ="
p_s1l1:  .asciz "\\r\\nS1L1:"
p_s1l2:  .asciz "\\r\\nS1L2@"
p_vttbr: .asciz "\\r\\nVTTBR_E2="
p_vtcr:  .asciz "\\r\\nVTCR_EL2="
p_s2l1:  .asciz "\\r\\nS2L1:"
p_s2l2:  .asciz "\\r\\nS2L2@"
p_colon: .asciz ":"
p_end:   .asciz "\\r\\n== END ==\\r\\n"
"""

# Read instruction words at a fixed address and print them, then do the STOCK eret (no SPSR
# flip -> boots normally to Android). Used to grab the UEFI instruction at 0x9fc02068 that is
# undefined at EL2 (run 10). MMU off for the read (flat-physical; the HLOS image is loaded at
# handoff time). Stackless register-link subroutines. Reads 32x u32 from 0x9fc02040.
MEMREAD_ASM = """
    .arch armv8-a
    .text
    .global _stub
_stub:
    movz    x9, #0xa9, lsl #16
    mov     w10, #4
    str     w10, [x9, #0x604]
    movz    w11, #0x40, lsl #16
hr1: ldr    w10, [x9, #0x610]
    tbnz    w10, #4, hr2
    subs    w11, w11, #1
    b.ne    hr1
    mov     w10, #2
    str     w10, [x9, #0x604]
    movz    w11, #0x40, lsl #16
hr3: ldr    w10, [x9, #0x610]
    tbnz    w10, #5, hr4
    subs    w11, w11, #1
    b.ne    hr3
hr4: mov    w10, #0x20
    str     w10, [x9, #0x618]
hr2: mov    w10, #0x10
    str     w10, [x9, #0x618]
    ldr     w10, [x9, #0x258]
    bic     w10, w10, #1
    str     w10, [x9, #0x258]
    str     wzr, [x9, #0x254]
    movz    w10, #0x380e
    movk    w10, #0x4, lsl #16
    str     w10, [x9, #0x260]
    movz    w10, #0x3e0e
    movk    w10, #0xc, lsl #16
    str     w10, [x9, #0x264]
    // MMU off for flat-physical read of the HLOS image
    mrs     x20, sctlr_el2
    bic     x10, x20, #1
    msr     sctlr_el2, x10
    isb
    adr     x12, mr_hdr
    adr     x17, .+8
    b       puts
    movz    x19, #0x2040
    movk    x19, #0x9fc0, lsl #16       // read ptr = 0x9fc02040
    mov     w18, #32
ml: cbz     w18, mdone
    ldr     w14, [x19], #4              // next 32-bit word (instruction)
    adr     x17, .+8
    b       puthex
    mov     w13, #0x20
    adr     x16, .+8
    b       putc
    sub     w18, w18, #1
    b       ml
mdone:
    adr     x12, mr_end
    adr     x17, .+8
    b       puts
    msr     sctlr_el2, x20             // restore MMU
    isb
    mov     x30, xzr                   // original overwritten instr
    movz    x16, #0x0328
    movk    x16, #0x8004, lsl #16      // 0x80040328 (stock eret, EL1h -> normal boot)
    br      x16

puts:
ps1: ldrb   w13, [x12], #1
    cbz     w13, ps2
    adr     x16, .+8
    b       putc
    b       ps1
ps2: br     x17

puthex:
    mov     w13, #0x30
    adr     x16, .+8
    b       putc
    mov     w13, #0x78
    adr     x16, .+8
    b       putc
    mov     w15, #60
ph1: lsr    x13, x14, x15
    and     x13, x13, #0xf
    cmp     x13, #10
    b.lo    ph2
    add     w13, w13, #0x57
    b       ph3
ph2: add    w13, w13, #0x30
ph3: adr    x16, .+8
    b       putc
    subs    w15, w15, #4
    b.ge    ph1
    br      x17

putc:
    mov     w10, #1
    str     w10, [x9, #0x618]
    mov     w10, #1
    str     w10, [x9, #0x270]
    movz    w10, #0x0800, lsl #16
    str     w10, [x9, #0x600]
    str     w13, [x9, #0x700]
    movz    w11, #0x40, lsl #16
pc1: ldr    w10, [x9, #0x610]
    tbnz    w10, #0, pc2
    subs    w11, w11, #1
    b.ne    pc1
pc2: mov    w10, #1
    str     w10, [x9, #0x618]
    br      x16

    .balign 4
mr_hdr: .asciz "\\r\\n== MEM 0x9fc02040 ==\\r\\n"
mr_end: .asciz "\\r\\n== END ==\\r\\n"
"""

def assemble(base_va, asm=None):
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d/'s.s').write_text(asm if asm is not None else STUB_ASM)
        subprocess.run(['aarch64-linux-gnu-as','-o',str(d/'s.o'),str(d/'s.s')],check=True)
        # link at the stub's runtime VA so adr/branches resolve correctly
        subprocess.run(['aarch64-linux-gnu-ld','-Ttext',hex(base_va),'-o',str(d/'s.elf'),str(d/'s.o')],check=True)
        subprocess.run(['aarch64-linux-gnu-objcopy','-O','binary','--only-section=.text',
                        str(d/'s.elf'),str(d/'s.bin')],check=True)
        return (d/'s.bin').read_bytes()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--mode', choices=['uart', 'delay', 'probe', 'readproto', 'faultdump', 'handoffdump', 'ptdump', 'shim', 'shimdbg', 'memread'], default='uart')
    ap.add_argument('--base', default='0xa90000', help='UART SE MMIO base')
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists() or 'backups' in out.resolve().parts:
        raise SystemExit('refusing to write to an existing path or under backups/')

    img = QheeImage(STOCK); seg = img.code
    data = bytearray(img.data)

    if a.mode in ('shim', 'shimdbg'):
        # Compile the C pass-through shim and link it at the cave VA, _stub first.
        HOOK = 0x80040324
        fo = seg.file_off + (HOOK - seg.vaddr)
        if bytes(data[fo:fo+4]) != bytes.fromhex('fe031faa'):
            raise SystemExit('handoff hook site mismatch (expected mov x30,xzr)')
        shim_dir = Path(__file__).with_name('shim')
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            subprocess.run(['aarch64-linux-gnu-gcc', '-ffreestanding', '-nostdlib',
                            '-fno-stack-protector', '-fomit-frame-pointer', '-fno-pic',
                            '-Os', '-Wall', '-c', str(shim_dir/'shim.c'), '-o', str(d/'shim.o')],
                           check=True)
            subprocess.run(['aarch64-linux-gnu-gcc', '-c', str(shim_dir/'shim_entry.S'),
                            '-o', str(d/'entry.o')], check=True)
            # entry.o first so _stub (.text.stub) lands at the cave base
            subprocess.run(['aarch64-linux-gnu-ld', '-T', str(shim_dir/'shim.ld'),
                            '-Ttext', hex(STUB_VA), '-o', str(d/'shim.elf'),
                            str(d/'entry.o'), str(d/'shim.o')], check=True)
            subprocess.run(['aarch64-linux-gnu-objcopy', '-O', 'binary', '--only-section=.text',
                            str(d/'shim.elf'), str(d/'shim.bin')], check=True)
            blob = (d/'shim.bin').read_bytes()
        cave_fo = seg.file_off + (STUB_VA - seg.vaddr)
        if bytes(data[cave_fo:cave_fo+len(blob)]) != b'\x00'*len(blob):
            raise SystemExit('cave not free')
        if len(blob) > 0x9c4:
            raise SystemExit(f'shim {len(blob)} > cave 0x9c4')
        data[cave_fo:cave_fo+len(blob)] = blob
        data[fo:fo+4] = struct.pack('<I', 0x14000000 | (((STUB_VA - HOOK) >> 2) & 0x03ffffff))

        if a.mode == 'shimdbg':
            # Also install the fault-dump handler in a SECOND cave (0x80092a14, below the
            # EL2 vectors) and point the real EL2 vectors at it, so whatever faults after the
            # shim erets to EL2 (the HLOS fetch, or the shim itself) prints ESR/ELR/FAR.
            DBG_VA = 0x80092a14
            dbg = assemble(DBG_VA, FAULTDUMP_ASM)
            dbg_fo = seg.file_off + (DBG_VA - seg.vaddr)
            if bytes(data[dbg_fo:dbg_fo+len(dbg)]) != b'\x00'*len(dbg):
                raise SystemExit('dbg cave not free')
            if len(dbg) > 0x5ed:
                raise SystemExit(f'dbg handler {len(dbg)} > cave 0x5ed')
            data[dbg_fo:dbg_fo+len(dbg)] = dbg
            VBAR = 0x80093000
            for voff in (0x000, 0x180, 0x200, 0x380, 0x400, 0x580):
                va = VBAR + voff
                vfo = seg.file_off + (va - seg.vaddr)
                data[vfo:vfo+4] = struct.pack('<I', 0x14000000 | (((DBG_VA - va) >> 2) & 0x03ffffff))

        code = bytes(data[seg.file_off:seg.file_off+seg.filesz])
        data[HASH_OFFSET:HASH_OFFSET+48] = hashlib.sha384(code).digest()
        out.write_bytes(data)
        extra = " + EL2 fault-capture at vectors(0x80093000)" if a.mode == 'shimdbg' else ""
        print(f"{a.mode}(C): shim {len(blob)}B @ {STUB_VA:#x}; hook 0x80040324 -> _stub; EL1h HLOS -> EL2+idmap{extra}")
        print(f"wrote {out} ({len(data)} bytes) sha256={hashlib.sha256(data).hexdigest()}")
        return

    if a.mode in ('handoffdump', 'ptdump', 'memread'):
        HOOK = 0x80040324   # mov x30,xzr (fe031faa), last GPR-zero before eret
        fo = seg.file_off + (HOOK - seg.vaddr)
        if bytes(data[fo:fo+4]) != bytes.fromhex('fe031faa'):
            raise SystemExit('handoff hook site mismatch')
        handler = assemble(STUB_VA, {'ptdump':PTDUMP_ASM,'memread':MEMREAD_ASM}.get(a.mode, HANDOFFDUMP_ASM))
        cave_fo = seg.file_off + (STUB_VA - seg.vaddr)
        if bytes(data[cave_fo:cave_fo+len(handler)]) != b'\x00'*len(handler):
            raise SystemExit('cave not free')
        if len(handler) > 0x9c4:
            raise SystemExit(f'handler {len(handler)} > cave')
        data[cave_fo:cave_fo+len(handler)] = handler
        data[fo:fo+4] = struct.pack('<I', 0x14000000 | (((STUB_VA - HOOK) >> 2) & 0x03ffffff))
        code = bytes(data[seg.file_off:seg.file_off+seg.filesz])
        data[HASH_OFFSET:HASH_OFFSET+48] = hashlib.sha384(code).digest()
        out.write_bytes(data)
        print(f"handoffdump: handler {len(handler)}B @ {STUB_VA:#x}; hook 0x80040324 -> b ho (no SPSR flip)")
        print(f"wrote {out} ({len(data)} bytes) sha256={hashlib.sha256(data).hexdigest()}")
        return

    if a.mode == 'faultdump':
        VBAR = 0x80093000   # REAL VBAR_EL2 (literal @0x80040330 = 0x80093000), confirmed on HW
        SPSR_FO = seg.file_off + (0x800401d8 - seg.vaddr)   # movz x5,#0x85 -> #0x3c9
        if bytes(data[SPSR_FO:SPSR_FO+4]) != bytes.fromhex('a51080d2'):
            raise SystemExit('SPSR site mismatch')
        handler = assemble(STUB_VA, FAULTDUMP_ASM)
        cave_fo = seg.file_off + (STUB_VA - seg.vaddr)
        if bytes(data[cave_fo:cave_fo+len(handler)]) != b'\x00'*len(handler):
            raise SystemExit('cave not free')
        if len(handler) > 0x9c4:
            raise SystemExit(f'handler {len(handler)} > cave 0x9c4')
        data[cave_fo:cave_fo+len(handler)] = handler
        data[SPSR_FO:SPSR_FO+4] = bytes.fromhex('257980d2')          # SPSR -> EL2h (0x3c9)
        # Patch the first instruction of the current-EL + lower-EL sync and SError vector
        # entries at the REAL VBAR to `b dump`. The EL2h fault (sync or SError, SP0 or SPx)
        # lands in one of these; ESR_EL2 in the dump identifies it. Handler chains to
        # QHEE's real sync-SPx handler 0x8004126c (-> reset to EDL, recoverable).
        VEC_OFFS = [0x000, 0x180, 0x200, 0x380, 0x400, 0x580]
        for voff in VEC_OFFS:
            va = VBAR + voff
            fo = seg.file_off + (va - seg.vaddr)
            b = 0x14000000 | (((STUB_VA - va) >> 2) & 0x03ffffff)
            data[fo:fo+4] = struct.pack('<I', b)
        code = bytes(data[seg.file_off:seg.file_off+seg.filesz])
        data[HASH_OFFSET:HASH_OFFSET+48] = hashlib.sha384(code).digest()
        out.write_bytes(data)
        print(f"faultdump: handler {len(handler)}B @ {STUB_VA:#x}; SPSR->EL2h; vectors @VBAR={VBAR:#x} offs={[hex(o) for o in VEC_OFFS]}")
        print(f"wrote {out} ({len(data)} bytes) sha256={hashlib.sha256(data).hexdigest()}")
        return

    base = int(a.base, 0)
    hi, lo = (base >> 16) & 0xffff, base & 0xffff
    base_load = f"    movz    x9, #{hi:#x}, lsl #16    // UART base {base:#x}"
    if lo:
        base_load += f"\n    movk    x9, #{lo:#x}"
    tmpl = {'delay': DELAY_ASM, 'probe': PROBE_ASM, 'readproto': READPROTO_ASM}.get(a.mode)
    if tmpl is not None and '{BASE_LOAD}' in tmpl:
        tmpl = tmpl.replace('{BASE_LOAD}', base_load)
    elif a.mode == 'uart':
        globals()['STUB_ASM'] = STUB_ASM.replace('{BASE_LOAD}', base_load)
        tmpl = None if False else STUB_ASM.replace('{BASE_LOAD}', base_load)
    stub = assemble(STUB_VA, tmpl)
    cave_fo = seg.file_off + (STUB_VA - seg.vaddr)
    if bytes(data[cave_fo:cave_fo+len(stub)]) != b'\x00'*len(stub):
        raise SystemExit('cave is not free')
    if cave_fo + len(stub) > seg.file_off + 0x9c4 + (STUB_VA-0x80094684):
        pass
    data[cave_fo:cave_fo+len(stub)] = stub

    # bl HOOK_VA -> STUB_VA, replacing the nop
    hook_fo = seg.file_off + (HOOK_VA - seg.vaddr)
    if bytes(data[hook_fo:hook_fo+4]) != bytes.fromhex('1f2003d5'):
        raise SystemExit('hook site is not the expected nop')
    off = (STUB_VA - HOOK_VA) >> 2
    bl = 0x94000000 | (off & 0x03ffffff)
    data[hook_fo:hook_fo+4] = struct.pack('<I', bl)

    # recompute code SHA-384
    code = bytes(data[seg.file_off:seg.file_off+seg.filesz])
    data[HASH_OFFSET:HASH_OFFSET+48] = hashlib.sha384(code).digest()

    out.write_bytes(data)
    print(f"stub {len(stub)} bytes @ {STUB_VA:#x}; bl={bl:#010x} @ {HOOK_VA:#x}")
    print(f"wrote {out} ({len(data)} bytes) sha256={hashlib.sha256(data).hexdigest()}")

if __name__ == '__main__':
    main()
