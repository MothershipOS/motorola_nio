# QHEE late initialization — 2026-10-05

Historical 656-check milestone. The follow-up [full cold-handoff model](EL2-bridge-handoff-model.md)
now completes this path and runs a synthetic RAM probe at EL1.

Original, unpatched nio QHEE now returns from its main initialization function
in the offline model. It then stops at SCM `0xc2000c1e`, shared-memory bridge
creation, inside the next cold-entry helper. The payload ERET has not executed.
The complete regression milestone is **656 passing checks**: the previous
580 plus 62 model-contract checks and 14 differential/provenance checks.

This continuation made no phone accesses or firmware writes. The last physical
result remains diagnostic Linux at EL1 without `/dev/kvm`.

## Finite PMIC region mappings

`--pmic-region-map` enables a separate response experiment for SCM `0xc2000c19`.
The inventory comes from the three pinned PMIC captures and the pinned firmware
policy, independently checked against QHEE's constructed channel records and
all executed mapping requests. Of 512 channels, 241 valid records belong to
EE4. The firmware's EE-mask and VMID-policy tables route them to VMID2 using
the TZ mapping path. Channels 111 through 353 are selected, except 137 and 211.
Each request maps exactly its 64 KiB interval, with arguments
`[base, exclusive_end, 2, 6, 1]`.

The model accepts only the exact next request in the 241-entry table. It checks
SMC #0 from EL2h, return PC `0x80041aa4`, arginfo 5, extended buffer
`0x801cc390`, permissions 6, operation 1 and zero reserved registers. Only the
two actual extended arguments are interpreted; unused trailing words are
preserved. Wrong, repeated, skipped, oversized and exhausted requests stop.

Each accepted request appends a VMID2 RW addition to a ledger initially empty
of modeled additions. This does **not** imply that initial physical mappings
are absent. It does not transfer ownership or enforce accesses. Transport and
service success are assumed, not measured at cold EL2. The PMIC MMIO model
continues to reject every write and unrelated read; no SPMI transaction model
was added.

All 241 calls complete and PMIC initialization returns at `0x80044160` with
x0=0. Both initial GCC clock states produce the same request sequence and
ledger, containing exactly 241 entries of permission value 6.

## Explicit PIL and late-entry experiments

| Optional model | Exact behavior | Limit |
| --- | --- | --- |
| `--pil-empty-region-list` | One SCM `0x4200020e`, arginfo 1, zero inputs, original return PC; returns zero transport/service/base/length | Physical reply is unknown. Zero length skips the caller's protected-region clearing loop. |
| `--imem-ready-publication` | One 8-byte store of `0x800a5021` at `0x146bfb20`, after the earlier log publication | Records the observed publication; does not implement general IMEM storage or permit readback. |
| `--handoff-prng` | Three ordered requests: `0x80095a60`/4 bytes, `0x801ccaa8`/2 bytes, `0x801ccaaa`/2 bytes, at the original SMC return PC | Uses the fixed input `0x736d656d`; this is deterministic test data, not entropy. |

The PIL zero-length branch is present in original code at `0x800570fc` onward.
It is a deliberate additional assumption, independently enabled and reported.
The ready publication executes at `0x800441cc`; main initialization returns
to `0x80040170`. x0 there is `0xffffffff`: reaching the return does not establish
a success status, and the cold-entry code does not branch on that value.

Without each model, the original firmware stops at its corresponding boundary:

| Furthest models enabled | Next observed boundary |
| --- | --- |
| PMIC metadata only | SCM `0xc2000c19` |
| All finite PMIC mappings | SCM `0x4200020e` |
| PIL empty-list experiment | IMEM write fault at `0x146bfb20`, PC `0x800441cc`, followed by fatal watchdog request |
| Ready publication | SCM PRNG request `0xc2000a02`, buffer `0x80095a60`, size 4 |
| Three late PRNG replies | SCM shared-memory bridge creation `0xc2000c1e` |

## Current bridge boundary and next implementation

The local Linux 6.18.54 driver identifies service MP / command `0x1e` as
`qcom_scm_shm_bridge_create()` and describes four **scalar packed operands**.
QHEE's own error string at `0x8007f68e` also identifies SHM bridge creation.
The packed address operands are not output-buffer pointers.

| Register / state | Observed value |
| --- | --- |
| FID / arginfo | `0xc2000c1e` / `4` |
| x2: packed physical address / NS permissions | `0x800ab000` |
| x3: packed intermediate address / secure permissions | `0x800ab004` |
| x4: size and flags | `0x1001a` (64 KiB size plus low flags `0x1a`) |
| x5: packed NS VMIDs | 0 |
| x6 / x7 | 0 / 0 |
| SMC / return PCs | `0x80041aa0` / `0x80041aa4` |
| Candidate return-PC chain | `0x80048690 → 0x80054eec → 0x80055034 → 0x800495a8 → 0x80040174` |

`0x80040174` is a **pending return address**, not an executed checkpoint.
The bridge call occurs inside helper `0x800494fc`. The first 32 bytes of its
region are zero at this boundary; that is an observation of modeled RAM, not
proof of physical TZ state. SCTLR_EL2 remains `0x8100f` and ELR_EL2 is zero:
the final payload-target setup and ERET have not yet executed.

Next trace the bridge return contract and the caller's handle lifetime, then
add an independently enabled, exact one-shot bridge/handle experiment if the
consumer can be bounded. Verify returned status and handle placement, reserved
arguments, repeat rejection and any subsequent delete/use call. Keep physical
TZ acceptance and access enforcement separate from that experiment. Continue
to the first payload ERET before proposing a CPU0 firmware transition.

The reference implementation is in
`kernel-work/linux-6.18.54/drivers/firmware/qcom/qcom_scm.c:1684`; its public
header supplies command `0x1e`. QHEE's variant flags and acceptance still need
to be established from its caller rather than inferred from the Linux HLOS
helper's different inputs.

## Validation and reproduction

`test_late_init.py` checks all GPRs, SP and NZCV on accepted replies, exact
writes and adjacent-byte preservation, PMIC ledger contents, one-shot guards,
wrong EL/SMC/callsite/arguments, out-of-order requests and unused extended words.
`test_late_init_trace.py` executes original QHEE under both clock states, checks
all 241 mapping tuples, 16 executed checkpoints, physical reads of all model
ledger entries, all three late PRNG calls and the final SCM registers/stack.
It also checks CLI dependencies and rejects unpinned captures and firmware.

```sh
python3 tools/hyp_re/test_late_init.py
python3 tools/hyp_re/test_late_init_trace.py
```

Use the project QEMU built by `tools/hyp_re/build_qemu_model.py`. Existing
`test_*.py` suites and the four read-only MMU-inspection checks also pass.

Evidence:

- `reports/qhee-offline/late-init-milestone.json`: aggregate checks and hashes.
- `kernel-work/out/qhee-late-init-trace-tests/complete-{off,on}/manifest.json`:
  exact emulator commands, model assumptions, source provenance and outputs.
- The corresponding `checkpoints/manifest.json`: executed checkpoints, exact
  mapping sequence, model counts and full PMIC ledger.
- `reports/qhee-offline/late-c1e-{caller,marshalling}.txt`: pinned static caller evidence.
- `reports/qhee-offline/pmic-region-map-inventory.json`: original inventory.

These results do not establish the real XBL/TZ payload contract, firmware
acceptance, independent recovery, Linux-compatible MMU/cache teardown, physical
EL2 entry or KVM guest execution. All earlier replay assumptions remain in force.
