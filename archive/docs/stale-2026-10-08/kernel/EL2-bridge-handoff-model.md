# Full QHEE cold handoff — 2026-10-06

Original, unpatched nio QHEE now completes its full cold initialization path,
executes the payload ERET and runs a synthetic RAM probe at **EL1**. This closes
the offline original-handoff milestone under explicit response and environment
assumptions. It does not establish physical Linux EL2 entry or KVM execution.

The regression milestone has **713 passing checks**: the previous 656, plus
41 bridge/PRNG contract checks, 15 differential/CLI checks and one outcome
classification regression. No phone access or early-firmware flash was made
for this milestone; the last physical result is the October 5 diagnostic Linux
boot at EL1 without `/dev/kvm`.

## Exact bridge response and handle consumer

`--shm-bridge-handle UINT64` enables a separate one-shot response experiment
for SCM `0xc2000c1e`. It requires the preceding late-PRNG model and the pinned
original firmware. Only the observed scalar operands are accepted:

```text
FID = 0xc2000c1e, arginfo = 4
x2 = 0x800ab000, x3 = 0x800ab004, x4 = 0x1001a, x5 = 0
x6 = x7 = 0; SMC #0, EL2h, return PC = 0x80041aa4
```

The model assumes transport/service success, returns x0=x1=0, and returns the
nonzero synthetic handle in x2. x3..x30, SP and NZCV are preserved. The token is
opaque, not a pointer or an actual TZ handle. Its ledger records exactly one
creation, the four operands and the handle. Repeats, changed inputs and other
FIDs—including bridge deletion—remain terminal. No ownership enforcement,
physical shared-memory service or generic bridge API was added.

Read-only checkpoints establish the consumer:

1. At `0x80054eec`, the caller's stack has service status 0 and the full handle.
2. At `0x80054f30`, the caller has stored the handle through its output pointer.
3. At `0x800495a8`, bridge bookkeeping has returned and the outer helper's
   local output retains the same full-width handle.
4. At `0x80040174`, that helper has returned. The bridge record reached via
   root `0x801e4eb8` is at `0x800cbba0` in this run. It records size 64 KiB,
   base `0x800ab000`, and the handle at offset `0x38`.
5. The record still holds the handle immediately before the payload ERET.

Original code at `0x8006bb7c` creates or updates that 72-byte bookkeeping
record. The trace reads only its exact object bounds. No delete call is observed
on this cold interval at the monitored SMC instruction, `0x80041aa0`; this is
not a claim about every later runtime consumer or every SMC instruction.

## Bounded allocator PRNG reply

After bridge creation, QHEE initializes a temporary buffer and requests eight
bytes of PRNG data at `0x800ab090`. `--bridge-prng-word UINT64` enables exactly
that one write, only after the modeled bridge is created, at the original SMC
return PC, with arginfo `0x22` and zero reserved registers. Adjacent memory and
all GPRs except returned x0, plus SP/NZCV, are preserved.

The default reproduction uses `0x736d656d736d656d`; a separate regression uses
zero and a different full-width handle. These are deterministic inputs, not
entropy. Unexpected buffers, sizes, ordering and repeats stop. The earlier
three heap and three late PRNG requests retain their separate bounded models.

At `0x80040178`, temporary-buffer initialization has returned; after the next
helper returns at `0x8004017c`, QHEE's stack canary at `0x80095a48` contains the
new 64-bit test word. This allows the original cold-entry code to proceed to
its final target/PSTATE setup and register clearing.

## Complete ERET and the synthetic target correction

The old synthetic incoming x0 target was `0x40400000`, in QEMU's RAM but outside
the executable HLOS mapping constructed by this QHEE run. Reaching its address
at ERET did not mean its first instruction executed:

| Observation | Old target | RAM target |
| --- | --- | --- |
| Synthetic incoming x0 | `0x40400000` | `0x90000000` |
| Final ERET instruction | `0x80040328` | `0x80040328` |
| SPSR_EL2 | `0x85` | `0x85` |
| State immediately after ERET | PC `0x40400000`, PSTATE `0x85` (EL1h) | PC `0x90000000`, PSTATE `0x85` (EL1h) |
| Next instruction step | EL2 vector `0x80093400`, ESR_EL2 `0x8200000e`, FAR_EL2 `0x40400000` | PC `0x90000004`, ESR_EL2=0 |
| Normal run outcome | Stage-2 instruction permission fault, then fatal watchdog request | Probe reports EL1 and exits successfully |

Read-only stage-2 walks at the final ERET show the old L2 block descriptor
`0x500000404004c5` and the RAM target's `0x100000900004fd`. The trace verifies
the observed 4 KiB-granule/L1-start regime, VTCR_EL2 `0x8001355c`, rather than
assuming a generic walk. It does not edit either page table or permissions.

`--payload-address` accepts only the explicit old and RAM targets. The RAM
target uses `handoff_probe.S`, a QEMU semihosting payload, so proving execution
does not require extra device-MMIO permissions. Its EL1 report is on QEMU's
semihosting stderr stream. Outcome classification requires a clean exit and
gives firmware faults/timeouts precedence over any probe text.

Before ERET, all x0..x30 are zero in this synthetic cold contract. The firmware
retains SCTLR_EL2 `0x8100f`, HCR_EL2 `0x80080005` and VMID3 stage-2 context
VTTBR_EL2 `0x30000b7708000`. EL1 SCTLR is zero. EL2 MMU/cache and QHEE's
hypervisor state remain active. This is the stock EL1 handoff, not a valid
Linux EL2 handoff or a Linux DTB/entry-register contract.

## Next implementation target

Stop adding unrelated SoC/device models now that the observed cold path reaches
the synthetic payload. Follow the next two focused work streams in KVM-PLAN:

1. Establish the actual XBL/TZ target, argument contract and intervening UEFI/ABL
   stages. The executable synthetic address is not evidence of the phone's
   real target. Determine which stage would reconfigure EL2 before Linux.
2. Develop and verify the smallest CPU0 EL2 transition against the complete
   modeled path. Use the existing isolated SPSR experiment as a comparison,
   then address MMU/cache teardown, retained QHEE services, interrupt/timer
   state, reservations and Linux entry registers. An EL2 diagnostic can precede
   Linux, but CurrentEL alone does not prove a usable Linux/KVM handoff.

Firmware acceptance and recovery independent of ABL remain separate gates
before any physical early-firmware test. Existing backups and model success
have not established them. Physical success still means Linux at EL2 followed
by actual KVM guest execution and a checked result.

## Validation and reproduction

```sh
python3 tools/hyp_re/test_bridge.py
python3 tools/hyp_re/test_bridge_trace.py
```

The trace suite reproduces bridge-disabled and allocator-PRNG-disabled stops,
both old-target faults and both successful RAM-target clock states, plus the
alternate-handle/zero-word run. Contract tests check exact inputs, one-shot
ledgers, full-width return preservation, adjacent-byte preservation and denial.
All earlier suites and the four read-only MMU-inspection checks pass.

Evidence:

- `reports/qhee-offline/bridge-handoff-milestone.json`: all checks and hashes.
- `kernel-work/out/qhee-bridge-trace-tests/ram-target-{off,on}/manifest.json`:
  exact emulator commands, assumptions, source provenance and EL1 output.
- Their `checkpoints/manifest.json`: bridge handle consumer, all 241 PMIC
  mapping tuples at the monitored SMC, ledgers, stage-2 walks and ERET steps.
- `reports/qhee-offline/bridge-return-consumer.txt` and
  `bridge-bookkeeping-consumer.txt`: pinned original caller/record disassembly.

All assumptions from the SMEM, SMMU, PMIC and late-init milestones still apply,
including EL1-postboot replay at cold EL2, query failure, ownership/mapping
success, PIL empty list and synthetic entry state. No physical TZ acceptance,
changed-firmware acceptance, real Linux payload or KVM execution is inferred.

Follow-up: [the full-path EL2 experiment](EL2-entry-contract.md) retains this
stock EL1 baseline and tests one loaded SPSR instruction change. It selects
EL2 but fails the first fetch under the original EL2 stage-1 permissions.
The current aggregate milestone has 736 passing checks; the 713-check report
above remains evidence of the earlier original-code handoff milestone.
