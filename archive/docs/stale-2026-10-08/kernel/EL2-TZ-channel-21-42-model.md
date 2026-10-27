# VMID 21/42 channel — 2026-10-05

Follow-up: command-database/log setup now passes; see [init-tail tracing](EL2-init-tail-trace.md).
This document preserves the preceding milestone.

The exact 8 KiB channel assignment at `0x80ddc000` now passes offline. Original
QHEE completes both records in its TZ-subsystem channel table and continues
to command-database memory ownership. No firmware or phone memory was changed.

## Contract and implementation

The second pinned descriptor is at `0x800a2ca8`, stride `0x38` after the first
channel. It specifies start `0x80ddc000`, length `0x2000`, VMIDs 21/42,
permissions 6/6 and count two. The original SCM request independently matches
these fields. The table role and consumers are documented in the
[first-channel evidence](EL2-TZ-channel-model.md).

`--tz-channel-21-42-assign` is a separate optional switch, disabled by default.
It requires `--tz-channel-assign`, which in turn requires the pinned SCM
contract via `--smem-toc-assign`. Common checks validate the exact firmware,
SMC #0, EL2h caller, FID/arginfo, call site, argument buffers and source VMID.
The second handler validates its exact region and all 48 destination bytes.

Its independent ledger moves from assumed owner VMID 3, with unknown initial
permissions, to reader/writer sets `{21,42}`. Each final bitmap is
`0x40000200000`; the 64-bit value preserves VMID 42. VMID 3 is removed.
The first channel and SMEM ledgers retain their previous state. Repeated
stale-owner requests, other regions, incorrect lengths, owner lists, permissions,
contexts and reserved bytes stop without an ownership update.

As before, this is an explicit successful-response experiment, not a TrustZone
implementation or proof of physical acceptance. The handler updates only its
ledger, preserves QHEE argument buffers, SP/NZCV and non-return registers, and
does not enforce access or implement channel contents. The earlier
IsDeviceNonSecure unsupported-response assumption remains required.

## Next boundary

Both GCC clock initial states now complete eleven SMEM assignments plus both
secure-channel assignments. The next SCM request has:

| Field | Value |
| --- | --- |
| FID / arginfo | `0xc2000c16` / `0x1117` |
| Region | `0x80860000`, length `0x20000` (128 KiB) |
| Source | VMID 3 |
| Destinations, in order | 1, 2, 5, 3, 6, 26, 30, 22 |
| Permissions | Read-only (4) for all eight |
| Context/reserved fields | Zero |

The base equals the measured command-database pointer at `0x0c3f000c`, so
this is identified as the command-database region from the pointer evidence
and execution path. Its ownership request remains unmodeled. Next trace that
path and add its exact contract; unknown requests must remain terminal.
The complete payload handoff has still not been reached.

## Validation

**387 checks passed:** the previous 357 regressions plus 30 second-channel
checks. The new checks cover register/buffer preservation, independent ledgers,
full-width owner masks, disabled/repeated/malformed requests, descriptor bytes,
CLI prerequisites and original QHEE with both clock initial states. Read-only
inspection verifies the next request and both channel/SMEM ledgers.

Reproduce using the full command in [the context milestone](EL2-SMMU-context-model.md),
adding `--smem-toc-assign --smem-partition-assign --tz-channel-assign
--tz-channel-21-42-assign` and a fresh output directory. Tests and inspection:

```sh
python3 tools/hyp_re/test_tz_channel_21_42.py
python3 tools/hyp_re/inspect_assign_mem.py \
  --manifest kernel-work/out/qhee-tz-channel-21-42-tests/qhee-off/manifest.json \
  --skip 13 --out reports/qhee-offline/tz-channel-21-42-inspection
```

Evidence:

- `kernel-work/out/qhee-tz-channel-21-42-tests/results.json`: 30 checks and hashes.
- `kernel-work/out/qhee-tz-channel-21-42-tests/qhee-{off,on}/`: manifests and
  debugger captures of the next request and completed ledgers.
- `reports/qhee-offline/tz-channel-21-42-regressions/`: prior regression logs.
- `reports/qhee-offline/tz-channel-21-42-milestone.json`: aggregate evidence.

See [the KVM plan](KVM-PLAN.md) for the scope and gates before physical firmware
experiments. This milestone does not demonstrate physical EL2 or KVM.
