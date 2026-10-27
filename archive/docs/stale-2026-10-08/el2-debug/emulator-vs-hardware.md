# Is the offline emulator (tools/hyp_re) useful? — assessment vs hardware (2026-10-07)

After capturing real EL2 state/fault/page-tables over UART (runs 05–07), here's where the
QEMU harness (`tools/hyp_re/run_qemu.py`, custom nio devices + synthetic EL3) stands.

## What it got RIGHT (confirmed on hardware) — keep using it for this

- **Static/control-flow RE of QHEE.** The handoff disassembly it's built on is accurate: the
  SPSR-patch site `0x800401d8`, the `eret` at `0x80040328`, the x22 dispatch, the XBL UART
  selector (`0x988000` vs `0x00a90000`), PMIC/SMEM/TZ-channel/cmd-db/qfprom models. This is what
  bootstrapped the whole on-device investigation and it held up.
- **The virtualization model, structurally.** `analyze.py` already had HCR_EL2 = RW+VM(stage-2)+TSC,
  and `test_bridge_trace.py` pinned `HCR_EL2=0x80080005` ✓, `VTCR_EL2=0x8001355c` ✓, stage-2 PTE
  attribute shape `0x…004fd` ✓, VMID 3 ✓ — all match the hardware dumps (runs 05, 07).

## What it got WRONG / can't model (hardware contradicts) — don't trust it for runtime

- **The EL2-transition fault.** Emulator `--handoff-experiment spsr-el2h`
  (`kernel-work/out/qhee-full-spsr-el2/manifest.json`) predicted:
  `outcome=qhee_fatal_watchdog_request`, `ESR=0x5e000000` (EC 0x17 = **SMC**) at `ELR=0x80041aa4`
  (inside QHEE), x0=`0xc2000108`, via a synthetic DDR probe at `0x90000000`.
  Hardware (run 06) showed something completely different: `ESR=0x8600000e` (EC 0x21 =
  **instruction abort, same EL**, stage-1 translation fault L2) at `ELR=FAR=0x9fc00000` (the real
  HLOS entry). Different fault class, different PC, different cause.
- **Why:** the emulator uses *synthetic* RAM / MMU / EL3 ("not SM8250 emulation", per its own
  `scope`/`limitations`). It never had QHEE's real EL2 stage-1 tables (`TTBR0_EL2=0xbb800000`), so
  the target `0x9fc00000` was reachable in its model and didn't translation-fault; instead its flow
  reached an SMC the synthetic EL3 turned into a watchdog. Its SCTLR_EL2 model was also approximate
  (`0x8100f` in bridge-trace, and a stray "MMU-off/`0x8100a`" claim in `el2-entry-findings.md`) vs
  the real `0x3048180f`.
- The DDR breadcrumb at `0x90000000` it leaned on is the exfil path run 03 already proved dies on
  the reset-to-EDL.

## Verdict

Useful as a **static reverse-engineering + hypothesis-drafting** tool, and its high-level model of
QHEE-as-type-1-hypervisor was correct. **Not** reliable for predicting runtime EL2 behavior — its
synthetic state mispredicted the actual fault. The UART channels built this session
(`--mode handoffdump/faultdump/ptdump`) are now the authoritative source for any runtime claim;
use the emulator to plan/encode candidates and read QHEE's code, then validate on-device.

Concretely for the KVM work: the emulator can keep helping decode QHEE's EL2↔EL3 (SMC) interface
and draft a hyp-stub, but every "it will do X at runtime" must be checked against the phone.
