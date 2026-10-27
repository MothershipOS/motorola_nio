# SMMU context controls and SMEM ownership boundary

Follow-up: [SMEM ownership model](EL2-SMEM-ownership-model.md) now passes the
eleven captured region assignments; this document preserves the preceding
context-model milestone and its reproduction command.

Updated 2026-10-05. This is an offline QHEE control-path milestone, not a
physical EL2 handoff or working KVM. Nio is running diagnostic Linux 6.18.54
at EL1 after RAM-only boot; `/dev/kvm` remains absent. No partition was flashed.

## What changed

Original QHEE now passes the earlier VMID-5 initialization failure and reaches
SCM memory assignment `0xc2000c16` with arginfo `0x1117`. The changes are:

1. Firmware-derived minimum context/stream counts, checked against the
   captured Linux-visible counts.
2. Bounded SMMU context-bank control storage and TLB completion behavior.
3. Replay of the phone's command-database pointer: a 32-bit read at
   `0x0c3f000c` returned `0x80860000`.

The run still explicitly assumes IsDeviceNonSecure (`0xc2000310`) returns
unsupported. Its actual TrustZone reply is uncaptured. Without that option,
the model stops at that query. No reply is implemented for memory assignment.

## Reconstructed counts

The pinned hyp image has SHA-256
`f69538bf3fded342bb1679c3d01f0b2ad4ba930b235c11fda210efcf0240d8b2`.
The descriptor pointer at `0x800a2108` names `0x8009aa08`. Each SMMU descriptor
occupies `0x3b7c` bytes; its 96 context records start at offset `0xfc` with
stride `0x9c`. The GPU descriptor is at `0x8009e584`.

Enabled mode-0 records other than VMID 1 give private reservations. Taking the
highest such index plus one, and adding their stream counts to the measured
visible counts, produces this minimal hypothesis:

| SMMU | Model contexts | Private contexts | Visible contexts | Model streams | Private streams | Visible streams |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| apps | 95 | 21 | 74 | 128 | 41 | 87 |
| GPU | 8 | 3 | 5 | 7 | 1 | 6 |

VMID 5 uses apps context bank 86, record `0x8009df6c`, with two streams.
The model checks descriptor indices, firmware hash and projection to both
captured counts. Hidden ID0 feature bits remain zero: no stage-2 capability
is inferred. The counts are **not measured raw EL2 hardware capabilities**.
The firmware may contain reservations for other configurations; projection
and successful execution support this hypothesis without proving it.

Model IDs are apps `4c017e80/6000005f/00005111` and GPU
`4c017e07/20000008/00005511`. Original firmware masks/subtractions explain
how these counts project to the captured EL1 view. Debugger dumps before
enumeration match the original descriptor bytes.

## Model scope

`--smmu-firmware-counts` enables the count hypothesis. `--smmu-contexts`
requires `--smmu-control` and enables separate zero-initialized context storage.
Bank base/stride come from ID1; bank indices must fit ID1 and the 96-entry
storage. Only aligned 32-bit accesses to a fixed offset whitelist work:
`0, 4, 10, 20, 24, 28, 2c, 30, 34, 38, 3c, 58, 5c, 610, 7f0, 7f4` (hex).

FSR is write-one-to-clear. FSRRESTORE accepts only zero writes and rejects
reads/nonzero writes. TLB commands complete immediately and TLBSTATUS reads
zero and rejects writes. There are no DMA clients, cached translations or
SMMU page-table walks. Initial register contents and timing are explicit model
assumptions, not boot-time captures. Context state is not clock-gated.

The pointer device guards a 4 KiB SRAM aperture and permits only the measured
32-bit read. Unknown offsets, widths and all writes abort. A 64-bit unaligned
read may be split by TCG and faults on its second word. Its capture is EL1-visible;
replaying it for EL2 is an assumption. Surrounding SRAM is not modeled.

For the architectural FSRRESTORE offset, see the
[Qualcomm kernel definition](https://android.googlesource.com/kernel/msm/+/8c383ac59dec97338932568036da7f7623832fe9/drivers/iommu/arm-smmu.c).
The firmware's observed zero write is the only permitted operation.

## Differential execution and next secure call

| Enabled additions to the preceding model | Original QHEE boundary |
| --- | --- |
| Firmware counts only | Write `0x150de020`, PC `0x80059330` |
| Counts and context controls | Read `0x0c3f000c`, PC `0x8006ca84` |
| Counts, context controls and measured pointer | SMC `0xc2000c16`, arginfo `0x1117` |

Both initial GCC clock states reach the same SMC without the VMID-5 failure
or denied SMMU/SMEM accesses. No firmware instruction or page-table entry
was patched to obtain this result.

The pinned Linux source identifies service `0x0c`, command `0x16` as
`qcom_scm_assign_mem`. At the call, read-only debugger inspection gives:

| Field | Value |
| --- | --- |
| Memory descriptor | `x2=0x8020c000`, size `x3=0x10` |
| Source array | `x4=0x8020d000`, 4 bytes, VMID 3 |
| Extended arguments | `x5=0x801cc390`: `[4, 0x8020b000, 0xc0, 0]` |
| Region | `0x80aff000`, length `0x1000` (SMEM TOC page) |
| Destination descriptors | Eight 24-byte records |
| Destination VMIDs | 3, 6, 5, 30, 27, 4, 40, 26 |
| Permissions/context fields | Read (4), zero contexts |
| CPU translation | `TTBR0_EL2=0xb7700000`, `SCTLR_EL2=0x8100f` |

At this boundary the SMEM TOC L2 entry is `0xb77ca003`; the global SMEM L2
entry is still zero. This does not establish completion of all SMEM mappings.
The call changes ownership; it is not a diagnostic query and was not issued
on the phone. The next model should validate the exact contract and update
an explicit synthetic ownership ledger. Returning success for arbitrary SCM
calls would hide the remaining dependency.

## Reproduction and evidence

Run from the project root:

```sh
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
  --smmu-firmware-counts --smmu-control --smmu-contexts --qcom-timer \
  --qfprom-sample reports/nio-gcc-mmu-checkpoint-20260928/manifest.json \
  --cmd-db-sample reports/nio-cmd-db-pointer-20261005/manifest.json \
  --nonsecure-query-unsupported \
  --out kernel-work/out/qhee-contexts-cmd-db --trace
python3 tools/hyp_re/test_smmu_contexts.py
python3 tools/hyp_re/test_cmd_db.py
```

264 checks passed: 218 existing regressions, 25 context/count checks and 21
pointer checks. The old VMID-5 failure remains reproducible when these optional
models are disabled. These tests establish bounded model behavior, not hardware
correctness or KVM guest execution.

Evidence paths:

- `reports/nio-diag-boot-20261004-kvm/`: physical RAM boot and Linux logs.
- `reports/nio-cmd-db-pointer-20261005/manifest.json`: physical fixed-word read.
- `reports/qhee-offline/smmu-configuration/`: pre-enumeration descriptor dumps.
- `kernel-work/out/qhee-contexts-cmd-db/manifest.json`: complete model inputs,
  hashes, trace and terminal register state.
- `reports/qhee-offline/assign-memory-inspection/`: raw argument buffers,
  debugger commands and page-table observations.
- `reports/qhee-offline/context-regressions/`: existing regression logs.
- `reports/qhee-offline/context-milestone.json`: check counts and evidence hashes.

The [KVM plan](KVM-PLAN.md) retains the remaining gates: complete original
handoff, actual boot-chain contract, recoverable CPU0 EL2 transition and real
KVM guest execution.
