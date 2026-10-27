# Run 08 — C pass-through shim: HLOS reaches EL2, UEFI faults early (2026-10-07)

First on-device test of the Option-A pass-through shim (`build_uart_marker.py --mode shim`,
C source `el2-debug/shim/shim.c`): keep stock QHEE intact, inject a 200-byte C shim into the
cave, redirect the handoff tail (`0x80040324`) to it. For the EL1h HLOS handoff the shim
rewrites `SPSR_EL2` EL1h→EL2h and clears `SCTLR_EL2.M` (EL2 MMU off), then erets — so the
boot chain runs at EL2 instead of as an EL1 stage-2 guest.

## Result: mechanically works; UEFI dies at EL2

Boot now proceeds **past QHEE's handoff into the HLOS at EL2** and reaches `UEFI Start` —
then **resets immediately** (no `Exit EBS`), looping: `QHEE Image Load → SBL1 End → UEFI
Start [~1300] → reboot → …` (5 cycles observed). Stock reaches `UEFI Start` then runs
hundreds of UEFI lines to `Exit EBS`; here it dies right after `UEFI Start`.

So ABL runs far enough at EL2 to print `UEFI Start`, then UEFI faults almost immediately.

## Interpretation

- **The shim is correct and the pass-through concept holds:** we did *not* brick pre-ABL;
  the HLOS entry executed at EL2 (the run-06 translation fault is gone because MMU-off makes
  the entry PA fetchable). That validates "reuse QHEE init, change only the eret."
- **Why UEFI dies:** strongest candidate is **MMU-off ⇒ Device-nGnRnE memory ⇒ alignment
  faults**. UEFI C code does unaligned accesses assuming Normal cacheable memory; at EL2 with
  the MMU off every data access is Device, which faults on unaligned access → crash right
  after entry. (Other candidates: an EL1-only instruction, or UEFI's own MMU/vector setup
  tripping over QHEE's leftover EL2 state.)

## Next step (clear)

Two things, in order:
1. **Capture the fault that kills UEFI.** Re-run the shim but also patch QHEE's real EL2
   vectors (VBAR_EL2=0x80093000, as in run 06 faultdump) to dump ESR/ELR/FAR_EL2 before the
   reset. ESR EC will say immediately: `0x25` data-abort + alignment IFSC ⇒ the Device-memory
   theory; some other EC ⇒ a different cause.
2. **Switch MMU-off → identity map.** Instead of clearing `SCTLR_EL2.M`, add identity 2 MB
   block entries to QHEE's EL2 stage-1 L2 table (at `0xbb801000`, covering the 2–3 GB window;
   fill the slots not already mapped) so the HLOS runs at EL2 with **Normal cacheable** memory.
   We can read/write those tables from the shim (run 07 proved MMU-off table access). UEFI
   likely needs much of the 2–3 GB window mapped, maybe more — extend ranges as the fault
   capture dictates. This is the real "pass-through hyp must provide an EL2 identity map" step.

## Status / recovery
Shim on slot B; UEFI boot-loops (resets before fastboot/EDL settle). Recover by forcing EDL
and restoring stock `hyp_b` (`unbrick/edl_usb.py --program 5 1184 2048 <stock hyp_b> --reset`).
Slot A is untouched stock. The C shim + build path are reusable for the identity-map variant.
