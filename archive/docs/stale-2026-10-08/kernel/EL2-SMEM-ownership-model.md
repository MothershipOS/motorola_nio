# SMEM ownership model — 2026-10-05

Follow-up: [VMID 21/22 channel model](EL2-TZ-channel-model.md) resolves the
next page described below. This document preserves the SMEM milestone.

Original QHEE now completes eleven modeled SMEM ownership assignments and
constructs CPU mappings for the previously missing SMEM addresses. This is
an offline control-path result. The phone still boots Linux at EL1 and has
no `/dev/kvm`; a complete EL2 handoff has not been demonstrated.

## Exact contract, explicit assumptions

The pinned Linux `qcom_scm_assign_mem` implementation identifies service
`0x0c`, command `0x16`, arginfo `0x1117` as memory ownership assignment. The
[upstream implementation](https://raw.githubusercontent.com/torvalds/linux/master/drivers/firmware/qcom/qcom_scm.c)
also documents the memory/source/destination buffer layout and the separate
transport and service return values. The authoritative local ABI reference
is `kernel-work/linux-6.18.54/drivers/firmware/qcom/qcom_scm.c`.

`--smem-toc-assign` permits only the observed TOC-page transition. The separate
`--smem-partition-assign` adds ten exact captured SMEM regions. Both options
are disabled by default. The partition option requires the TOC option and
the pinned SMEM capture hash; the TOC option requires the pinned hyp hash.

The handler checks AArch64 EL2h, SMC #0, FID, arginfo, the pinned call site
(return PC `0x80041aa4`), exact buffer pointers, all lengths, reserved fields,
region start/size, source VMID and every destination descriptor byte. It
checks the pointers before dereferencing them and accepts no other regions,
partial overlaps or reordered destination lists. It does not implement a
general Qualcomm secure monitor.

Each region starts with an **assumed** owner set `{3}` and unknown permissions,
inferred from QHEE's source list, not from captured TrustZone state. After all
checks pass, the handler updates only its own ledger, then returns `x0=x1=0`.
Successful TrustZone acceptance is an explicit experiment. A repeated request
with stale source ownership stops. Regions have independent state; the model
does not require their observed ordering.

No QHEE buffers, instructions or page-table entries are edited by this handler.
Registers other than the two return values, SP and NZCV are preserved. The
ledger tracks ownership/permissions but **does not enforce CPU or DMA access**.
It neither programs real hardware nor validates actual TrustZone behavior.
The existing IsDeviceNonSecure unsupported-response experiment is still needed
for this execution path. Disabling it stops at that earlier query.

## Regions and observed destination records

The host-to-VMID associations were checked against all eleven actual QHEE
request buffers. Two initial candidate mappings and one descriptor order
were rejected by the model and corrected using read-only debugger evidence.
The final contracts below all match original firmware execution.

`R` is permission 4; `RW` is permission 6. All context/reserved fields are zero.
Source ownership is `{3}` in every observed request. `ALL` means VMIDs
`3, 6, 5, 30, 27, 4, 40, 26`, in that order.

| Region start | Length | Destination VMIDs and permissions, in order |
| --- | --- | --- |
| `0x80aff000` | `0x1000` | ALL: R |
| `0x80acf000` | `0x30000` | 3: RW, 6: RW |
| `0x80aaf000` | `0x20000` | 3: RW, 30: RW |
| `0x80a7f000` | `0x30000` | 3: RW, 5: RW |
| `0x80a73000` | `0xc000` | 3: R, 6: RW, 5: RW |
| `0x80a6b000` | `0x8000` | 3: RW, 27: RW |
| `0x80a67000` | `0x4000` | 3: R, 1: RW, 26: RW |
| `0x80a57000` | `0x10000` | 3: RW, 40: RW |
| `0x80a47000` | `0x10000` | 3: R, 30: RW, 40: RW |
| `0x80901000` | `0x146000` | ALL: RW |
| `0x80900000` | `0x1000` | ALL: RW |

The TOC ledger stores owner bitmap and uniform permission. Partition records
store separate reader and writer bitmaps, preserving VMID 3's read-only access
to remote-only partitions. Ten independent final ledger entries match their
requested permissions; the TOC has eight readers and no write permission.

## Progress and next boundary

Both initial GCC clock states complete one TOC and ten partition transitions.
Read-only inspection then confirms these CPU page-table leaves:

| Virtual address | Final leaf descriptor |
| --- | --- |
| `0x80900000` | `0x50000080900703` |
| `0x80901010` | `0x50000080901703` |
| `0x80aff230` | `0x40000080aff783` |

QHEE constructed these entries itself. This checks three important addresses,
not every mapping or access permission throughout SMEM.

The next request uses the same SCM service, but targets `0x80dc1000`, length
`0x1000`, source VMID 3, destination VMIDs **21 and 22**, both RW. This page is
outside the SMEM reservation and remains unmodeled. A static descriptor at
`0x800a2c70` in the pinned hyp image contains that exact region and VMID pair.
The live DT places the page inside the larger removed-memory reservation
`0x80b00000..0x85dfffff`; this does not establish its specific purpose.

Next trace the descriptor's consumers and surrounding protected-range table.
Classify the page and its ownership requirements before adding another exact
transition. Continue toward the complete original payload handoff without
relaxing unknown-call stops. No ownership-changing SCM was issued on the phone.

## Reproduction and validation

Use the full command in [the context-model milestone](EL2-SMMU-context-model.md),
adding `--smem-toc-assign --smem-partition-assign` and selecting a new `--out`.
For reproducible contract, ledger and original-firmware checks:

```sh
python3 tools/hyp_re/test_smem_assign.py
python3 tools/hyp_re/inspect_assign_mem.py \
  --manifest kernel-work/out/qhee-smem-assign-tests/qhee-partitions-off/manifest.json \
  --skip 11 --out reports/qhee-offline/smem-ownership-inspection
```

The inspector performs only reads. It bounds argument reads to the known QHEE
RAM segment, reads EL3 ledger memory physically, and records input/binary/tool
hashes. `--skip N` selects the N+1-th memory-assignment request.

**327 checks passed:** 264 earlier regressions plus 63 ownership checks.
The new suite covers successful register/buffer preservation, every partition,
unchanged unrelated ledger entries, stale ownership, invalid pointers/lengths,
permissions, reserved fields, partial/unlisted regions and disabled models.
It also independently inspects all eleven original QHEE requests, tests both
clock states and verifies the next request, final ledger and CPU mappings.

Artifacts:

- `kernel-work/out/qhee-smem-assign-tests/results.json`: 63 checks and hashes.
- `kernel-work/out/qhee-smem-assign-tests/qhee-partitions-{off,on}/`: final
  execution manifests and debugger inspection; `request-0` through `request-10`
  under the off case contain all original request buffers.
- `reports/qhee-offline/ownership-regressions/`: baseline regression logs.
- `reports/qhee-offline/ownership-milestone.json`: aggregate checks and hashes.
- `reports/qhee-offline/smem-partition-contracts.json`: reviewed region/owner data.
- `reports/qhee-offline/next-ownership-descriptor.json`: next static descriptor.

Physical KVM still needs the real boot-chain entry contract, a compatible EL2
transition and a recoverable hardware test, followed by actual guest execution.
See [KVM-PLAN.md](KVM-PLAN.md).
