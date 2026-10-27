# Why the modified hyp_b did not boot — 2026-10-06

**Corrected finding.** An earlier version of this note blamed XBL secure-boot
signature rejection. A direct on-device test disproved that. The real cause is
the **EL2 patch faulting at runtime**: the modified hyp code *was* loaded and
executed, and failed before completing the HLOS handoff.

## The test that settles it

This device is a Motorola **engineering unit**: `fastboot getvar secure = no`,
`cid = 0xDEAD`, and Android reports `ro.boot.secure_hardware = 0`. To find out
whether XBL actually verifies the hyp signature (rather than assume), we built a
single-variable probe: **stock hyp with only the 256-byte OEM signature corrupted**
(4 bytes flipped at `0x1200`), leaving code and both hash-table entries byte-identical
to stock.

- Flashed to slot B, set active B, cold-booted.
- **Result: it booted normally** (Android, adb up, slot `_b`).

An image whose *only* defect is an invalid RSA-PSS signature boots. Therefore
**this device does not verify the hyp signature** — secure boot is effectively off
for the pre-ABL firmware chain. (`verifiedbootstate=green` / `device_state=locked`
are the AVB/HLOS lock layer, a different mechanism, and do not gate hyp loading.)

Consequence: the modified `hyp_b` candidate's signature being stale was **not** why
it failed. Its code hash was repaired, so it is integrity-consistent, and the
unverified signature is ignored — so XBL loaded and ran the modified code. The
non-boot happened *inside* the patched hyp.

## What the signature analysis does and does not show

`tools/hyp_re/verify_hyp_signature.py` correctly shows the candidate's preserved
signature is invalid over its edited hash table (stock VALID, candidate INVALID).
That remains true and is useful if this were ever run on a secure-boot-enforcing
unit — but on THIS device it has no effect on boot.

## Actual cause: the EL2 transition patch

The candidate (`build_firmware_candidate.py`, `el2-xbl-masked-mmu-off`) changes two
code ranges in QHEE:

- `0x800401d8`: return SPSR EL1h → **EL2h** (0x3c9) — make the handoff ERET land at EL2.
- `0x800402b0..0x8004032c`: masked cache-clean + MMU/cache teardown, then the original ERET.

The offline QEMU/TCG modeling already flagged the likely failure mode: entering the
original downstream code at **EL2h** faults on **EL2 stage-1 execute permission** at
the target, with MMU/caches in the state QHEE left for an EL1 guest. In other words,
QHEE's page tables and system registers are built to run the next stage as an **EL1**
payload under stage-2; redirecting the same ERET to EL2h runs it against EL2's own
stage-1 regime (different translation/permissions, SCTLR_EL2, VBAR_EL2, stack), which
faults immediately. No ABL, so nothing recovers → black screen → EDL.

This is a **hypothesis consistent with the offline model**, not a captured hardware
fault: the device produces no pre-ABL log we can read, so the exact fault class
(stage-1 XN, translation fault, SP/VBAR, SError) is not directly measured.

## Reframed next steps

The blocker is the **EL2 entry contract**, not signing. To make a modified hyp hand
EL2 to the downstream path on this device:

1. The ERET target must be executable under **EL2 stage-1** (identity/exec mapping,
   SCTLR_EL2.M/C/I as intended), not merely under the EL1-guest stage-2 QHEE set up.
2. EL2 system state (VBAR_EL2, SP_EL2, HCR_EL2, MMU enable) must be established before
   or at the transition, which the current 124-byte teardown does not fully do.
3. Validate the complete transition in the harness against the *real* downstream entry
   (UEFI/ABL/Linux) register/MMU requirements — see [EL2-KVM-analysis.md](EL2-KVM-analysis.md)
   and [EL2-entry-contract.md](EL2-entry-contract.md).

Because signatures are not enforced here, iterating modified-hyp candidates is viable,
and each failed boot is now routinely recoverable via EDL (`unbrick/`). That makes a
controlled bisect of the patch (SPSR-only vs teardown-only vs combined) the fastest way
to localize the fault.

Evidence: `reports/nio-el2-firmware-20261006/` (candidate), `reports/nio-el2-slot-b-boot-20261006/`
(original boot attempt), and the on-device signature-corruption boot test recorded here.
