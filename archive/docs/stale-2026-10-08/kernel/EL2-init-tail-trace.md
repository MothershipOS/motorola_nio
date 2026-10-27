# QHEE initialization tail — 2026-10-05

Follow-up: PMIC metadata scans now pass; see [PMIC tracing](EL2-PMIC-metadata-model.md).
This document preserves the preceding milestone.

Original, unpatched QHEE now passes command-database ownership, returns from
memory initialization, and maps both hypervisor and TZ diagnostic logs in the
offline model. The next observed boundary is the first PMIC arbiter APID-table
read: `0x0c440900` at PC `0x80060d40`. Complete payload handoff is still open.

## Implemented contracts

All switches are optional and default off. Earlier SoC/SMEM/GCC/SMMU assumptions
and the explicit IsDeviceNonSecure unsupported-response experiment still apply.

| Option | Exact behavior | Assumption / limit |
| --- | --- | --- |
| `--cmd-db-assign` | `0x80860000`/128 KiB, source VMID 3, destination VMIDs 1,2,5,3,6,26,30,22, each read-only | Successful TZ acceptance and initial owner assumed; ledger only |
| `--hyp-log-share` | `0x80209000`/8 KiB, source VMID 4, destinations 3 R and 4 RW | Successful TZ acceptance and initial owner assumed; ledger only |
| `--tz-log-sample PATH` | Only 32-bit read at `0x146bf720`, measured value `0x14695000` | Postboot EL1 value reused at cold EL2; equality unproven |
| `--imem-publications` | One exact 64-bit write `0x200080209000` at `0x146bfb30` | Records QHEE's log pointer/size publication; no general IMEM storage or readback |

The assignment models share the pinned SMC #0 / EL2h caller, FID `0xc2000c16`,
arginfo `0x1117`, return PC `0x80041aa4`, exact argument pointers, source byte
count and reserved-field checks. The log handler explicitly validates source
VMID 4 before the other handlers' VMID-3 check. All destination bytes must
match. Final command-database reader/writer masks are `0x4440006e`/0; log masks
are `0x18`/`0x10`. Repeats with stale ownership stop. Neither model changes
QHEE buffers/page tables or enforces CPU/DMA access.

The new IMEM device guards the whole `0x146bf000` page; unknown reads/writes
abort. The publication comes from original `stp w8,w10,[x9]` at `0x80045954`,
which QEMU presents as an 8-byte write. It occurs before log initialization,
so pointer replay without the separate publication option stops early.
Without the device, this address falls in QEMU virt's PCIe area: the disabled
control reads `0xffffffff`, not a captured nio value. This explains why the
previous model could publish silently but could not map the TZ log correctly.

## Read-only execution evidence

`trace_init_tail.py` sets eight debugger breakpoints and reads registers and
bounded QHEE stack frames. It changes no guest registers or memory. Both
initial GCC clock states produce the same ordered checkpoints:

| PC | Checkpoint | x0 |
| --- | --- | --- |
| `0x80065ce8` | Command-database setup returned | 0 |
| `0x800440b4` | Memory initialization returned | 0 |
| `0x80044108` | Enter log sharing | 0 |
| `0x800422a4` | Hypervisor log mapping returned | 0 |
| `0x800422d8` | TZ log mapping returned | 0 |
| `0x8004410c` | Log sharing returned | 0 |
| `0x8004415c` | Enter PMIC initialization | 0 |
| `0x80060d40` | Before first PMIC table read | 0 |

At the last point, x26=`0x0c440900`, x21=0. The candidate stack return chain is
`0x80060ccc → 0x80060274 → 0x8005fe7c → 0x80044160 → 0x80040170`.
Continuing without the breakpoint produces an external data abort at that
address, followed by QHEE's watchdog request. A subsequent IMEM read at offset
`0x10` is denied while QHEE handles the abort; it is not the primary fault.
The run also logs `HYPX REGISTRATION FAILED` and continues; no success reply
or branch bypass was added for that diagnostic.

Canonical runs and checkpoints:

- `kernel-work/out/qhee-init-tail-tests/complete-off/manifest.json`
- `kernel-work/out/qhee-init-tail-tests/complete-on/manifest.json`
- Each run's `checkpoints/manifest.json` includes registers and frame chains.
- `reports/qhee-offline/init-tail-milestone.json` hashes sources and evidence.

## Next tracing step: bounded PMIC mapping replay

The live device tree identifies `0x0c440000`/`0x1100` as the SPMI PMIC-arbiter
core. The pinned QHEE table at `0x800a4f46` sets a 512-entry read bound.
The local Linux source `drivers/spmi/spmi-pmic-arb.c` defines the v5 APID map
as `0x900 + 4*n`, matching this execution path.

Read-only capture on the connected diagnostic Linux returned arbiter version
`0x50010000`, first APID word `0x00000400`, and all 512 words from
`0x0c440900` through `0x0c4410fc` (354 nonzero). Evidence:
`reports/nio-pmic-arbiter-20261005/manifest.json`. No SPMI transaction or hardware
write was issued. These are postboot EL1 observations, not cold EL2 evidence.

Next implement a separate opt-in read-only replay of exactly that captured
array, with address/width/write guards and capture validation, then trace
subsequent accesses. Do not fabricate zero tables or implement PMIC power
transactions preemptively. Later PMIC ownership/configuration dependencies
remain unknown. IMEM publication at `0x146bfb20` and cold-entry return/ERET
appear later statically, but have not been reached by this full trace.

## Validation and reproduction

**477 checks passed:** all previous 387, plus 54 exact ownership checks,
28 TZ-pointer/publication checks and eight integration/dependency checks.
Coverage includes caller/register/buffer preservation, source-owner distinction,
malformed/repeated/disabled requests, pinned descriptor bytes, guarded MMIO,
malformed captures, differential full runs and both clock initial states.
The integration suite includes eight execution checkpoints per complete run;
these are assertions within those cases, not extra checks in the total.

```sh
python3 tools/hyp_re/build_qemu_model.py
python3 tools/hyp_re/test_init_assign.py
python3 tools/hyp_re/test_tz_log.py
python3 tools/hyp_re/test_init_tail.py
python3 tools/hyp_re/trace_init_tail.py \
  --manifest kernel-work/out/qhee-init-tail-tests/complete-off/manifest.json \
  --out reports/qhee-offline/init-tail-checkpoints
```

`test_init_tail.py` contains the complete explicit run arguments. All 17 test
scripts and the four original debugger checks were rerun; logs are in
`reports/qhee-offline/init-tail-regressions/`.

This is offline control-flow progress, not physical KVM. The phone remains in
diagnostic Linux at EL1; no hyp/XBL partition was written. Real boot-chain
entry, complete MMU/cache teardown, firmware acceptance and recovery independent
of ABL remain separate open work in [KVM-PLAN.md](KVM-PLAN.md).
