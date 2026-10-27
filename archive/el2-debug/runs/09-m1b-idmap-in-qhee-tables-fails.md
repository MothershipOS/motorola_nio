# Run 09 — M1b: patching QHEE's EL2 tables in place fails (2026-10-07)

Tried M1b: keep EL2 MMU on, clear `SCTLR_EL2.WXN`, and add identity 2 MB blocks to QHEE's
**existing** EL2 stage-1 L2 table (`0xbb801000`) for the HLOS region, then eret EL2h. Built in
C (`el2-debug/shim/shim.c` + `--mode shimdbg`, which also installs the EL2-vector fault capture
at the real `VBAR_EL2=0x80093000`). Added `dc cvac` over the L2 page + `dsb/tlbi alle2/dsb/isb`.

## Result: two faults, approach rejected
- **A — eret target still unmapped:** `ESR=0x8600000e` (iabort, IFSC 0x0e = stage-1 translation
  fault L2) at `ELR=FAR=0x9fc00000`; `SPSR=0x89` (EL2h), `SCTLR=0x3040180f` (WXN cleared, M=1).
  Identical to the no-idmap run 06 — i.e. my `L2[0xfe] = 0x9fc00000|0x705` write did **not** take
  effect for the table walker, even with `dc cvac`+`tlbi alle2`.
- **B — QHEE disturbed:** `ESR=0x96000145` (EC 0x25 data abort, **write**, DFSC L1) at
  `ELR=0x80057338` (QHEE code) writing `FAR=0x42445000` (1–2 GB, `L1[1]` unmapped). QHEE's own
  fault path faults when it runs at EL2h against the minimal EL2 map.

## Why in-place patching is the wrong move
1. **Coherency/visibility:** writing QHEE's live L2 and invalidating isn't landing for the walker
   (cache-clean didn't help) — likely because QHEE's tables are set up with attributes/walk
   assumptions we're not matching, and poking a live table mid-regime is fragile.
2. **It disturbs QHEE:** QHEE's resident code/handlers assume *its* map; changing it (and clearing
   WXN) breaks QHEE paths (fault B).

## Decision — shim should install its OWN EL2 tables (next: M1c)
Instead of editing QHEE's tables, the shim should build a **fresh, self-contained EL2 stage-1
identity map** in a scratch DRAM region (full DRAM, 2 MB blocks, Normal cacheable, RWX) and point
`TTBR0_EL2` at it before the eret (with a matching `TCR_EL2`/`MAIR_EL2`, WXN clear). This is what a
real pass-through hyp does — set up its own EL2 MMU — and it removes both failure modes:
- no dependence on QHEE's table layout or walk-attribute assumptions (we control the whole map);
- QHEE is untouched (we only repoint TTBR0_EL2 at the eret, QHEE never runs again on this path).

Scratch for the new tables: a few pages of free DRAM (e.g. an unused slice of QHEE's carveout, or
a fixed reserved address we pick and that isn't otherwise used before Linux). L1 (64×1GB) + a
handful of L2 tables (one per GB touched) cover 0–4 GB identity; ~tens of KB.

Keep MMU-off (run 08, which reached `UEFI Start`) as the fallback data point: it got *further*
than in-place idmap, so whatever we do must at least match that.

## Status
Shim(dbg) on slot B; boots fault→auto-EDL. Phone currently in EDL. Recover by restoring stock
`hyp_b` or just flash the next (M1c) candidate over it. FT232 needed a physical replug mid-run to
resume logging (heavy USB cycling).
