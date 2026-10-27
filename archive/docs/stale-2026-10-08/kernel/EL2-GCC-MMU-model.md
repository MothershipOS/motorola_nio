# Minimal GCC/SMMU control-path model — 2026-09-28

> Follow-up: [QFPROM/MMU investigation](EL2-QFPROM-MMU-model.md) establishes
> that QHEE filters the captured SMMU IDs and identifies the skipped mapping path.

## Result

Original, unmodified QHEE now passes the observed applications and GPU SMMU
reset/configuration paths. With the required explicit models enabled, it stops
at SMC **0xc2000310**, x1=0, return PC 0x80041cc0. Its caller's error string is
`IsDeviceNonSecure failed` at 0x80080cc1.

An optional, separately labeled unsupported response (-1) follows QHEE's own
error path. That path reaches a missing 32-bit read at **0x00784218**, PC
**0x8006a908**, then requests the fatal watchdog. The watchdog remains a stop.
There is no fabricated success response, complete handoff or working phone KVM.
Initial clocks off and initial clocks on reach the same boundaries.

**182 checks pass** across the complete current suite, including 88 GCC/SMMU
checks and six added secure-call contract checks. The phone still runs Linux
6.18.54 at EL1; GPU runtime-PM policy is restored to `auto`; /dev/kvm is absent.
No firmware partition was written.

## Implemented scope

`tools/hyp_re/emulator/nio-gcc-mmu.c` adds one opt-in QEMU device:

- Eleven clock controls at 0x17c004..0x17c030, with the descriptor gaps denied;
  ten GDSC controls at 0x17c040..0x17c06c, also with gaps denied. These addresses
  come from this QHEE image's tables at 0x800a2410 onward and 0x800a2818 onward.
- GPU SMMU clock and power controls at 0x03d92000 and 0x03d92004.
- Bit 0 controls enable/collapse; bit 31 reports halted/powered state.
  Transitions complete immediately. No voltage, PLL, clock-rate or interconnect
  timing behavior is modeled. Unsupported bits and device transactions fail.
- Guard regions cover the whole 0x15000000 applications SMMU aperture (1 MiB)
  and 0x03da0000 GPU SMMU aperture (64 KiB). Unmodeled offsets abort.
- Optional measured ID0/ID1/ID2, and a separate whitelist for global reset,
  fault, stream and context-attribute registers. Array bounds derive from IDs.
  Registers start at zero; fault status is W1C. TLB completion is immediate
  because the model has no DMA clients or cached device translations.
- Optional 19.2 MHz read-only counter at 0x17c25000, driven by QEMU virtual time,
  lets firmware delay loops progress. This is not the complete QTIMER device
  and does not correct QHEE's separately generated log timestamps.

This is a single-CPU control-flow investigation, not a faithful SM8250 SMMU or
CPU translation model. SMMU accesses are not gated by simulated clock state.
No device DMA, context-bank translation, actual isolation, interrupts or
remote hardware clients are implemented. Firmware logs `VMID 4 not support`
with the measured EL1-visible IDs; those IDs do not establish EL2 capabilities.

An early run without full SMMU guards consumed default QEMU reads in the
applications aperture. That was invalid evidence of SMMU progress. The guards
were added before the successful bounded runs and are covered by negative
tests at both aperture ends.

## Captured IDs and power-state correction

Canonical capture: `reports/nio-mmu-ids-active-20260928/manifest.json`.

| SMMU | ID0 | ID1 | ID2 | Streams / context banks |
| --- | --- | --- | --- | --- |
| Applications | 0x4c017e57 | 0x6000004a | 0x00005111 | 87 / 74 |
| GPU, resumed | 0x4c017e06 | 0x20000005 | 0x00005511 | 6 / 5 |

The first GPU capture was taken while runtime-suspended and returned unusable
IDs. It is preserved at `reports/nio-mmu-ids-20260928/` and is rejected by the
input validator. The canonical capture temporarily resumed the GPU SMMU using
Linux runtime PM, read six fixed ID words, and restored the original `auto`
policy in cleanup. No direct hardware control-register writes were made.
The IDs are postboot EL1 observations, not captured reset-time EL2 state.

## New secure query and next register

Function 0x80067264 constructs the query. On failure it logs the string above
and returns an error. Caller 0x80065bb0 sets its local disable flag to zero and
continues; it does not consult the `/ac/smmu` `disable_smmu_ac` property through
the successful nonsecure-device branch. The failure experiment returns -1 only
for this exact FID, zero argument-info, SMC immediate 0, and EL2h caller. Other
contracts stop. Tests verify all GPRs except x0, SP and NZCV are preserved.
It is not a captured TZ response or a security-state determination.

Disassembly and strings are saved in `reports/qhee-offline/nonsecure-query-*`.
The next address falls inside `efuse@784000` in the pinned SM8250 device tree.
QHEE reads only 0x00784218 and tests bit 1. A new diagnostic read measured
**0x00000000** at EL1; see
`reports/nio-gcc-mmu-checkpoint-20260928/manifest.json`. No fuse was written.
A bounded replay of this word is the next model addition; its precise field
meaning and EL2 visibility remain unverified. The current model still stops
there rather than using this measurement automatically.

## Validation and reproduction

`test_gcc_mmu.py` checks clock/power transitions, read-only status, prohibited
bits, ID provenance, capture rejection, array ends, unmodeled apertures,
TLB status, advancing timer, write rejection and four original-firmware runs.
Native 64-bit clock transactions are rejected. An unaligned 64-bit CPU load can
be decomposed by TCG into two valid 32-bit device transactions; a separate test
records that limitation instead of claiming the device sees the original
instruction width.

```sh
python3 tools/hyp_re/build_qemu_model.py
python3 tools/hyp_re/test_gcc_mmu.py
python3 tools/hyp_re/test_replay.py
python3 tools/hyp_re/run_qemu.py \
  --qemu kernel-work/emulation/qemu-build/qemu-system-aarch64 \
  --soc-hw-version 0x60080201 \
  --devcfg backups/nio-firmware-20260927T163534Z/devcfg_a.img \
  --secure-state-sample reports/nio-scm-live-20260928-direct/manifest.json \
  --psci-version 0x10001 \
  --smem-sample reports/nio-smem-layout-20260928-v7/manifest.json \
  --smem-version-write --smem-rlock-zero --smem-mutex --smem-ram-table-write \
  --prng-word 0x736d656d --gcc-mmu-clocks off \
  --smmu-ids reports/nio-mmu-ids-active-20260928/manifest.json \
  --qcom-timer --smmu-control \
  --out kernel-work/out/qhee-mmu-control --trace
```

Add `--nonsecure-query-unsupported` and use another output directory to exercise
the explicit query-failure path. Neither run modifies the backed-up QHEE image.
Final test manifests, including binary/source hashes, are copied to
`reports/qhee-offline/gcc-mmu-tests.json` and `replay-tests.json`. The four
firmware runs referenced by the GCC/SMMU test report use the final rebuilt
model; earlier exploration reports are historical artifacts.

The actual KVM route and acceptance gates are in [KVM-PLAN.md](KVM-PLAN.md).
