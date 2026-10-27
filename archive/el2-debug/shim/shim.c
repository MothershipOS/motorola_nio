/* nio QHEE pass-through shim — M1c table builder (C). See shim_entry.S for the EL2 regime
 * switch that calls this with the MMU OFF. Builds a fresh 64-entry EL2 stage-1 L1 identity
 * map (1GB blocks: 0-2GB Device-nGnRE for SoC MMIO, 2GB+ Normal cacheable RWX for DRAM) at
 * L1_BASE and points TTBR0_EL2 at it, leaving QHEE's own tables untouched. Compiled frameless
 * (leaf, register-only) so it uses no stack while the MMU is off (no cached-stack hazard). */

typedef unsigned long u64;

#define L1_BASE     0x800a5000UL             /* scratch: QHEE image zero-padding, 4KB aligned */
#define ATTR_NORMAL 0x705UL                  /* block: valid, AttrIdx1(Normal WB), AF, SH-inner, AP=RW, XN=0 */
#define ATTR_DEVICE 0x419UL                  /* block: valid, AttrIdx6(Device-nGnRE), AF, AP=RW */

void build_l1_idmap(void)
{
    volatile u64 *l1 = (volatile u64 *)L1_BASE;
    for (u64 i = 0; i < 64; i++) {
        u64 va   = i << 30;                               /* 1GB block, output == input (identity) */
        u64 attr = (i < 2) ? ATTR_DEVICE : ATTR_NORMAL;   /* 0-2GB MMIO, 2GB+ DRAM */
        l1[i] = va | attr;
    }
    __asm__ volatile("msr ttbr0_el2, %0" :: "r"(L1_BASE));
}
