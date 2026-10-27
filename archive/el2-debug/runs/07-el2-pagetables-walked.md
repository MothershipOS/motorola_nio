# Run 07 — QHEE EL2 stage-1 + stage-2 page tables dumped & walked (2026-10-07)

Dumped QHEE's own EL2 translation tables over UART (`build_uart_marker.py --mode ptdump`,
hooked at the handoff, EL2 MMU briefly off for flat-physical reads, no SPSR flip → boots)
and walked them offline (`el2-debug/walk_ptdump.py`). Raw: `uart/ptdump-20261007.txt`.

Config: `TTBR0_EL2=0xbb800000 TCR_EL2=0x8081351c` (4KB granule, 36-bit VA, start level 1,
L1=64 entries of 1GB). `VTTBR_EL2=0x00030000bb808000 VTCR_EL2=0x8001355c` (stage-2, VMID 3).

## EL2 stage-1 (QHEE's private map) — what EL2 can address

```
S1L1 nonzero: [0]=table→0xbb806000  [2]=table→0xbb801000     (only 0-1GB and 2-3GB mapped)
S1L2 under L1[2] (2-3GB window):
    VA 0x80000000..0x80600000   (QHEE code/data, 4KB pages)
    VA 0xbb800000..0xbfa00000   (QHEE carveout: its own page tables + heap, 2MB blocks)
```

So **EL2 maps only QHEE itself** — its code (`0x80000000-0x80600000`) and its carveout
(`0xbb800000+`). The guest's DRAM is **not** in EL2's view.

## stage-2 (the HLOS guest's IPA→PA map) — identity over guest DRAM

`S2L2` under L1[2] identity-maps the guest's 2-3GB window (`0x…004fd` blocks: IPA==PA),
covering the whole HLOS, **excluding** QHEE's carveout (that's how QHEE hides from the guest).

## The three addresses (walk_ptdump.py)

| address | EL2 stage-1 | stage-2 (guest) |
|---|---|---|
| QHEE `0x80040000` | **mapped** (→0xbb802000) | unmapped (guest can't see QHEE ✓) |
| HLOS `0x9fc00000` | **UNMAPPED** | mapped identity → PA 0x9fc00000 |
| ABL  `0xa16cd1dc` | **UNMAPPED** | mapped identity → PA 0xa1600000 |

## Conclusion — the EL2-entry blocker, fully proven

The HLOS/ABL entry points are **guest addresses that live only in QHEE's stage-2 map**, not in
EL2's stage-1. At EL1 the guest reaches them via stage-2; at EL2 there is no stage-2 and EL2's
stage-1 doesn't map them — so eret-ing the handoff to EL2h instruction-aborts with a stage-1
translation fault. This is exactly run 06's `ESR_EL2=0x8600000e` (EC=0x21 iabort same-EL,
IFSC=0x0e translation fault L2) at `FAR=0x9fc00000`.

"Flip the handoff SPSR to EL2h" is therefore a dead end by construction: EL2 and the guest have
**separate address spaces**, and QHEE deliberately keeps the guest's RAM out of EL2's stage-1.

## Implication for KVM

To run Linux at EL2 you cannot reuse this handoff. Two real options:
1. **Displace/stub QHEE** so TZ hands EL2 to Linux, and Linux installs its own EL2 stage-1
   (and, for guests, stage-2). This is the genuine KVM path (earlier notes: XBL/TZ reject a
   blanked hyp → needs the right stub, not a blank).
2. If one insisted on entering code at EL2 via QHEE, that code's pages would have to be added to
   QHEE's EL2 stage-1 (`TTBR0_EL2=0xbb800000` tables) first — i.e. patch QHEE's own map. Possible
   as an experiment (we can now read/modify those tables from the ptdump hook) but it does not get
   to KVM; it only lets a chosen page execute at EL2 under QHEE.

Net: the diagnostic goal is met — we have, on real hardware, QHEE's complete EL2 addressing model
and the exact reason the EL2 transition faults. Next real step is option 1 (the hyp-stub route),
which is the pre-existing hard problem, now with a working on-device EL2 inspection channel to
validate against.

## Tooling
- `--mode ptdump` reads tables with EL2 MMU off (flat-physical); boots normally; prints S1/S2 L1
  (64 entries) + the L2 under L1[2]. Extend the followed L1 index / add more levels as needed.
- Walk offline with `el2-debug/walk_ptdump.py`.
- Recovered to stock hyp both slots, slot A active.
