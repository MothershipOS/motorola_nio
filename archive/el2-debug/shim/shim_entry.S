/* nio QHEE pass-through shim — M1c entry trampoline (pure asm; gcc ignores `naked` on this
 * target, so the EL2 regime switch lives here, not in C). Branched to from QHEE's handoff tail
 * (the `mov x30,xzr` at 0x80040324, before the `eret` at 0x80040328).
 *
 * For the EL1h HLOS handoff: turn the EL2 MMU off (so build_l1_idmap's writes are flat-physical
 * and we don't depend on QHEE's perms), build our own EL2 identity map + repoint TTBR0_EL2,
 * invalidate TLB, turn the MMU back on (now using OUR table, WXN cleared for RWX), flip SPSR
 * EL1h->EL2h, then reproduce QHEE's GPR sanitise and eret. x0 (HLOS boot arg) is kept in x19
 * across the whole thing (no stack). build_l1_idmap is a frameless C leaf, so it uses no stack
 * while the MMU is off. Any other handoff falls through to a stock eret.
 */
    .arch armv8-a
    .section .text.stub,"ax"
    .global _stub
_stub:
    mov     x19, x0                 /* save HLOS boot arg (register, not stack) */
    mrs     x0, spsr_el2
    and     x1, x0, #0xf
    cmp     x1, #5                  /* EL1h? (QHEE demoting the HLOS) */
    b.ne    9f                      /* no -> stock eret */

    mrs     x20, sctlr_el2          /* save SCTLR */
    bic     x1, x20, #1
    msr     sctlr_el2, x1           /* EL2 MMU OFF (flat-physical) */
    isb
    bl      build_l1_idmap          /* C (frameless): write L1 @0x800a5000, set TTBR0_EL2 */
    dsb     sy
    tlbi    alle2
    dsb     sy
    orr     x1, x20, #1             /* M=1 */
    bic     x1, x1, #0x80000        /* WXN=0 -> identity RWX executes */
    msr     sctlr_el2, x1           /* EL2 MMU ON with OUR table */
    isb
    mrs     x0, spsr_el2            /* SPSR EL1h -> EL2h */
    and     x0, x0, #0xfffffffffffffff0
    movz    x1, #9
    orr     x0, x0, x1
    msr     spsr_el2, x0

9:  mov     x0, x19                 /* restore boot arg; GPR sanitise x1..x30 */
    mov     x1,  xzr
    mov     x2,  xzr
    mov     x3,  xzr
    mov     x4,  xzr
    mov     x5,  xzr
    mov     x6,  xzr
    mov     x7,  xzr
    mov     x8,  xzr
    mov     x9,  xzr
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
    mov     x20, xzr
    mov     x21, xzr
    mov     x22, xzr
    mov     x23, xzr
    mov     x24, xzr
    mov     x25, xzr
    mov     x26, xzr
    mov     x27, xzr
    mov     x28, xzr
    mov     x29, xzr
    mov     x30, xzr
    eret
