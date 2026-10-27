# Run 06 — EL2 fault registers CAPTURED over UART (2026-10-07)

The SPSR→EL2h candidate's fault is finally captured, live over UART, from QHEE's **real**
EL2 vector. This is the fault that bricked every modified-hyp attempt since the start.

```
== EL2 FAULT ==
ESR_EL2  = 0x8600000e
ELR_EL2  = 0x9fc00000
FAR_EL2  = 0x9fc00000
SPSR_EL2 = 0x3c9
HCR_EL2  = 0x80080007
SCTLR_E2 = 0x3048180f
== END ==
```

## Decode

- **ESR_EL2 = 0x8600000e** → `EC=0x21` (Instruction Abort, **taken at the same EL = EL2**),
  `IL=1`, `IFSC=0x0e` = **stage-1 translation fault, level 2**.
- **ELR_EL2 = FAR_EL2 = 0x9fc00000** → the faulting instruction fetch is at the HLOS entry
  `0x9fc00000` (the cold HLOS handoff target; the x22==2 path we flipped).
- **SPSR_EL2 = 0x3c9** → EL2h: the eret really did land the target at EL2 (our flip worked).

**Cause, definitively:** flipping the handoff SPSR to EL2h makes the core fetch the HLOS entry
`0x9fc00000` at EL2. QHEE's EL2 **stage-1** MMU is ON (`SCTLR_EL2.M=1`) with `TTBR0_EL2=0xbb800000`
(run 05), and that translation does **not** map `0x9fc00000` executable → instruction-abort,
translation fault level 2. The HLOS target lives in the guest's address space (stage-1 EL1 +
stage-2), which does not exist at EL2.

## This corrects run 04

Run 04 concluded "the fault is caught at EL3, not EL2" after patching 12 entries at
**0x80040330** and seeing nothing. That was a misread: QHEE's `ldr x4,#0x80040330; msr vbar_el2,x4`
loads the **literal value at** 0x80040330, which is **0x80093000** — the real `VBAR_EL2`
(confirmed by the run-05 dump and by disassembly: VBAR+0x200 @0x80093200 = `b 0x8004126c`).
Patching the real vectors (`--mode faultdump`, VBAR 0x80093000, offsets 0,0x180,0x200,0x380,
0x400,0x580 → `b dump`, chain to 0x8004126c) caught the fault immediately. **The fault is at
EL2, not EL3.**

## What this means for KVM

The blocker is now concrete and narrow: to run anything at EL2 via this handoff, the target must
be **mapped executable in QHEE's EL2 stage-1** (TTBR0_EL2=0xbb800000 tables), OR QHEE's EL2 MMU
must be turned off before the eret and the target entered flat-physical. But the real KVM goal is
Linux-at-EL2, and the HLOS here is a stage-2 guest of QHEE — so the actual path remains displacing
QHEE as EL2 owner, not flipping this handoff. The value of this run: the fault is fully explained
and the EL2 capture channel works, so any future EL2 construction can be validated on-device.

## Method / reliability notes

- **Capture that works:** a `run_in_background` `cat /dev/ttyUSB0 > file` (single reader). The GUI
  monitor repeatedly dropped whole boots this session (stalled reader); for critical one-shot
  captures use the background cat. The fault dump prints before QHEE's handler resets to EDL, so
  UART (unlike the DDR breadcrumb of run 03) survives.
- Flashed via EDL (`unbrick/edl_usb.py --program 5 1184 2048 <img> --reset`); recovered by
  programming stock `hyp_b` back (digest F69538BF…0240D8B2). Both slots stock hyp again.
- FT232 wedges under heavy USB cycling (`OSError:[Errno 5]`); clear with a USBDEVFS_RESET ioctl.
