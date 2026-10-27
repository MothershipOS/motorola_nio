# VMID 21/22 secure-channel ownership — 2026-10-05

Follow-up: [VMID 21/42 channel](EL2-TZ-channel-21-42-model.md) now passes the
second entry described below. This document preserves the first-channel milestone.

The offline model now accepts the exact original-QHEE ownership request for
`0x80dc1000`, length `0x1000`, from VMID 3 to VMIDs **21 and 22**, both read/write.
Original QHEE continues to the adjacent channel's request. No phone ownership
call, memory write or firmware flash was performed.

## Descriptor role and consumers

In the pinned hyp image, the descriptor at `0x800a2c70` is a 56-byte record:
64-bit start/length, four 32-bit destination slots, four 32-bit permission
slots, a destination count and padding. The first two VMIDs are 21/22, their
permissions are 6/6, and the count is two. The table has two records, with
its count at `0x800a2ce0`; the next record begins at `0x800a2ca8`.

The startup code at `0x80065b30..0x80065b58` supplies this table, count and
source VMID 3 to `0x80065704`. That routine walks records with stride `0x38`,
builds destination descriptors and calls the ownership-assignment path.
Its caller's error diagnostic at `0x80080acb` identifies this as a
**TZ–subsystem secure channel**. A separate channel lookup at `0x800666e8`
searches the same table by destination ID. The mapping code around
`0x80042f04` also consumes the table.

This establishes the page's firmware role. The specific endpoint names behind
VMIDs 21 and 22, channel protocol and actual page contents remain unidentified.
The evidence does not establish the real TrustZone response or an EL2-release
facility. Static consumer evidence is saved in
`reports/qhee-offline/vmid21-22-consumers.txt`.

## Bounded implementation

`--tz-channel-assign` is disabled by default and requires `--smem-toc-assign`
for the common pinned-image/caller contract. The existing handler checks the
exact SMC #0, EL2h caller, FID `0xc2000c16`, arginfo `0x1117`, return PC
`0x80041aa4`, source VMID, buffer addresses, lengths and reserved arguments.

The new handler accepts only the exact page and 48-byte destination list:
21/RW followed by 22/RW, with all context/reserved bytes zero. It validates
all arguments before updating a separate channel ledger. Reader and writer
bitmaps transition from assumed initial owner `{3}` with unknown permissions
to `{21,22}` (`0x600000` for each). VMID 3 is removed. A repeated request with
stale source ownership stops; malformed, reordered or adjacent-page requests
stop without changing ledger state.

Only the synthetic ledger changes. QHEE buffers, page tables and channel
contents are not written by this handler; all GPRs except the two return
values, SP and NZCV are preserved. Returning transport/service success is
an explicit model assumption, as is initial ownership. The ledger does not
enforce CPU/DMA access. The prior IsDeviceNonSecure unsupported-response
experiment remains a prerequisite for reaching this path.

## Result and next stop

With both initial GCC clock states, original QHEE completes eleven SMEM
assignments and the VMID 21/22 channel assignment. The SMEM ledgers retain
their completed state and the new channel ledger contains `0x600000/0x600000`.

The next request is `0x80ddc000`, length `0x2000`, source VMID 3, destinations
**21 and 42**, both RW. Its static descriptor is the second record at
`0x800a2ca8`. It remains unmodeled. Next implement that separate exact
contract and follow original QHEE beyond the two-entry channel table.

Neither a complete payload handoff nor physical KVM is demonstrated.
Linux still needs a real EL2 boot-chain transition and guest-execution test.

## Validation and reproduction

**357 checks passed:** the previous 327 regressions plus 30 channel checks.
The new suite checks argument/caller rejection, both owner slots, permissions,
reserved/context fields, region boundaries, stale ownership, disabled mode,
register/buffer preservation, the pinned descriptor and both full QHEE runs.
Read-only debugger inspection verifies the next call and final channel/SMEM
ledger state. The disabled option preserves the earlier VMID 21/22 stop.

Use the full command in [the SMMU context milestone](EL2-SMMU-context-model.md)
with `--smem-toc-assign --smem-partition-assign --tz-channel-assign` and a new
output directory. The checks and debugger capture are reproducible with:

```sh
python3 tools/hyp_re/test_tz_channel.py
python3 tools/hyp_re/inspect_assign_mem.py \
  --manifest kernel-work/out/qhee-tz-channel-tests/qhee-off/manifest.json \
  --skip 12 --out reports/qhee-offline/tz-channel-inspection
```

Artifacts:

- `kernel-work/out/qhee-tz-channel-tests/results.json`: 30 checks and hashes.
- `kernel-work/out/qhee-tz-channel-tests/qhee-{off,on}/`: original-firmware
  execution manifests and read-only inspection of the next request.
- `reports/qhee-offline/tz-channel-regressions/`: previous-suite logs.
- `reports/qhee-offline/tz-channel-milestone.json`: aggregate check evidence.

See [KVM-PLAN.md](KVM-PLAN.md) for the remaining physical EL2/KVM gates.
