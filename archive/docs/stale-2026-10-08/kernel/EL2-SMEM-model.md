# Nio SMEM model and heap initialization — 2026-09-28

> Current follow-up: [GCC/SMMU model](EL2-GCC-MMU-model.md) and
> [minimal KVM plan](KVM-PLAN.md). Results below describe the earlier milestone.

## Result

Original, unmodified QHEE now passes the observed SMEM initialization, board
information lookup, heap PRNG requests and RAM partition-table update in the
offline model. It next faults at **0x0017c02c**, PC **0x80063aec**. QHEE's own
configuration names this register **gcc_mmu_tcu_clk**. This is a new clock/MMU
hardware dependency, not a remaining missing SMEM byte on this executed path.

Two different deterministic heap seeds reach the same boundary. **88 checks
pass**, including 45 SMEM checks and 10 new PRNG checks. This does not establish
a complete stock handoff, Linux entry at EL2, or working KVM.

## Captured state versus model assumptions

The complete input is `reports/nio-smem-layout-20260928-v7/manifest.json`.
The collector reads fixed metadata and two explicitly selected firmware items
from nio's RAM-booted diagnostic Linux. It does not write phone SMEM or flash
partitions. Each block has an address, length, command, exit status and SHA-256.

| Input | Source / behavior |
| --- | --- |
| Pointer pair | Measured 0x01fd4000/4 → 0x80aff230 |
| Target info | Measured SIII; 2 MiB at 0x80900000; 625 item IDs |
| Partition table | Measured version 1, 11 entries |
| Global partition | Measured header at 0x80901000 |
| Global item index | 17 measured allocation headers; payloads skipped unless selected |
| Board info, item 137 | 268 captured bytes at 0x80907210, replayed read-only |
| RAM partitions, item 402 | 2328 captured bytes at 0x80911a88; version 3, six entries |
| Header version write | Optional private-memory write to 0x80900040, exactly 32 bits |
| RLOCK, item 404 | Optional zero-initialized 8192-byte private buffer at 0x809051b0 |
| TCSR mutex 9 | Optional claim/read-owner/release model at 0x01f49000, initially free |
| RAM-table writes | Optional writes only inside the private captured item 402 |
| Heap PRNG | Optional deterministic word split across three exact requests |

There are **3692 captured bytes** in the SMEM snapshot. The remaining bytes in
the 2 MiB reservation fault, except the explicitly enabled RLOCK buffer. The
model overlays the entire reservation on QEMU virt RAM, so uncaptured holes
cannot silently read as zero. Input files are never changed by guest writes.

RLOCK's item ID is corroborated by Qualcomm's
[published LK SMEM definitions](https://android.googlesource.com/kernel/lk/+/qcom-dima-8x74-fixes/platform/msm_shared/smem.h).
Its zero contents are an explicit single-CPU assumption, not a measurement of
the phone's lock state. Mutex semantics follow the local pinned Linux
`drivers/hwspinlock/qcom_hwspinlock.c` claim/read-owner/release protocol and the
executed QHEE accesses. It models no remote processors or contention timing.

The snapshot was captured after Android's boot chain and QHEE initialized the
phone. The collector checks that the global partition header stays unchanged
during its item-header walk, but this is not an atomic cold-boot snapshot.
The earlier EL1-to-EL2 secure-state replay and PSCI version assumptions remain.

## Execution milestones

| Model inputs added | Next observed boundary |
| --- | --- |
| Initial SMEM layout | Global partition header 0x80901000 |
| Global partition header | First item header 0x80901020 |
| Item-header chain | Version publication at 0x80900040 |
| Version writes | RLOCK write at 0x809051b0 |
| RLOCK backing memory | Hardware mutex 9 at 0x01f49000 |
| Mutex protocol | Board-info read at 0x8090723c |
| Board info | PRNG SMC 0xc2000a02 |
| Three PRNG requests | RAM partition-table read at 0x80911a88 |
| RAM table snapshot | Table write at 0x80911ae0 |
| Private table writes | gcc_mmu_tcu_clk read at 0x0017c02c |

The observed RAM-table write stores the 64-bit value 0x37700000 at 0x80911ae0.
We let QHEE execute that write against the private table copy; no instruction
or firmware branch is skipped.

## PRNG call contract

The QHEE caller at 0x80048bc4 constructs service 0xc2000a02, arginfo 0x22,
then passes a writable buffer and length. Its failure string at 0x8007bd04 is:
`TZ was unable to generate a random number for Hypervisor in hyp_prng_get_data`.
The heap initializer at 0x80052194/0x800521b8/0x800521c4 requests:

- 4 bytes at 0x80095a28: the supplied model word.
- 2 bytes at 0x801cc5d0: its low half.
- 2 bytes at 0x801cc5d2: its high half.

`--prng-word` enables only these exact buffer/length pairs, from EL2h via
SMC #0 and the exact function/arginfo. It writes those bytes, returns status
zero, preserves other general registers, SP and NZCV, and emits
`MODEL_PRNG_FIXED_WORD_NOT_ENTROPY`. Other requests still stop. This is solely
a deterministic execution aid; it is not a source of cryptographic entropy or
a replacement for phone TrustZone.

## Reproduce

```sh
python3 tools/hyp_re/build_qemu_model.py
python3 tools/hyp_re/test_smem.py
python3 tools/hyp_re/test_prng.py
python3 tools/hyp_re/run_qemu.py \
  --qemu kernel-work/emulation/qemu-build/qemu-system-aarch64 \
  --soc-hw-version 0x60080201 \
  --devcfg backups/nio-firmware-20260927T163534Z/devcfg_a.img \
  --secure-state-sample reports/nio-scm-live-20260928-direct/manifest.json \
  --psci-version 0x10001 \
  --smem-sample reports/nio-smem-layout-20260928-v7/manifest.json \
  --smem-version-write --smem-rlock-zero --smem-mutex \
  --smem-ram-table-write --prng-word 0x736d656d \
  --out kernel-work/out/qhee-smem-ram-write --trace
```

All model options are opt-in. Omit write-model switches to reproduce the
corresponding earlier boundary. No phone is needed to reproduce these runs.
To collect a fresh sample while diagnostic Linux is connected:

```sh
python3 tools/capture_nio_smem.py --out NEW_DIRECTORY \
  --boot-image kernel-work/out/scm-diagnostic-v2/boot-v2.img \
  --board-info --ram-partitions
```

The collector uses a short arithmetic loop to fit the USB shell input limit.
The failed v6 capture is retained and explicitly marked incomplete; the model
rejects it. The successful v7 capture is used for the complete run.

## Validation and next step

Tests cover little-endian reads, pointer access rules, uncaptured holes,
cross-boundary accesses, rejection of damaged/overlapping captures, permitted
write widths and ranges, local write readback, lock contention/release,
unchanged input files, original-QHEE progression, and exact PRNG bounds and CPU
state preservation. Both 0x736d656d and 0x12345678 produce three PRNG replies,
the same RAM-table update and the same final fault. Earlier analysis, EL3 replay,
hardware-register and isolated handoff tests also pass.

Evidence is under `reports/qhee-offline/`: `smem-tests.json`, `prng-tests.json`,
`smem-model-build.json`, `smem-ram-write-run.json`, and the caller/register
disassembly files. Differential runs and traces remain in `kernel-work/out/`.

Next trace and model the required GCC/MMU clock accesses, starting with
gcc_mmu_tcu_clk. QHEE stores its register address at 0x800a2418 and its name
pointer at 0x800a2410; the string is at 0x8007fce4. The helper reads the register,
records the previous bit state, sets bit 0, and later has a corresponding
clear-bit helper. Do not assume that accepting a clock write models the MMU,
its power state or its completion/status registers.

After the stock handoff is reproduced, the EL2 transition still needs separate
validation of MMU/cache teardown, interrupt and stage-2 ownership, and secondary
CPU entry. Firmware integrity and an independent recovery route remain open.
The real phone is still RAM-booted at EL1; no /dev/kvm is established.
