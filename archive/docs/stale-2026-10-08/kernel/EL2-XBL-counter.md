# Original SEC counter conversion and platform-selection boundary — 2026-10-06

Original SEC now executes `CNTVCT_EL0`, converts the returned ticks, stores
its result, loads an original SIMD constant, and copies a 40-byte initialization
descriptor. Ten complete modeled profiles retain the current EL through these
operations. Diagnostic execution remains at EL2 with I/D enabled and translation
off; stock EL1 remains the comparison control.

The next external dependency is exactly one four-byte read of `0x01fc8004`
at PC `0x9fc2a150`. An optional normal instruction step produces a synchronous
external data abort at the current EL, paused before the vector handler. This
is a missing MMIO observation, rather than evidence that the counter or SIMD
access requires another firmware change.

The connected phone returned `0x00000000` on two fixed read-only checks of
that register. It still runs diagnostic Linux 6.18.54 at EL1 with HYP unavailable.
The capture is postboot evidence only: cold-entry and diagnostic EL2 equality
remain unverified. No register replay was enabled in this milestone.

## Counter dataflow and timing limit

The original wrappers at `0x9fc19b5c` and `0x9fc27fdc` reach
`mrs x0, cntvct_el0` at `0x9fc2bb48`. The read completes at both ELs without
an exception. Returned ticks are observed from the original instruction, with
no debugger writes or synthetic replacement result.

The conversion at `0x9fc19b78` calls the frequency helper at `0x9fc19be4`.
Its original global at `0x9fc2f2e4` contains `19200000`, so the helper returns
that value directly. The alternative `CNTFRQ_EL0` instruction at
`0x9fc2bb40` is not executed on this path.

Original quotient/remainder, multiplication and division helpers calculate:

```text
(ticks // 19200000 * 1000000000
 + ticks % 19200000 * 1000000000 // 19200000) modulo 2^64
```

The result is stored at `0x9fc3b3c0`. The conversion stack unwinds from
`0x9ffcfb90` to `0x9ffcfbc0`. Eight independent original-instruction Unicorn
slices verify zero, one tick, values around one second, the 32-bit boundary,
and the maximum uint64 input, including overflow behavior. Writes are confined
to the bounded conversion stack.

QEMU's Cortex-A76 counter advertises **62.5 MHz**, while this original firmware
path uses **19.2 MHz**. Both values and their mismatch are recorded in each
counter checkpoint. `CNTVOFF_EL2=0` and `CNTHCTL_EL2=3` stay unchanged.
The arithmetic is verified against the observed ticks; its result is not
physical elapsed-time evidence. Future delay/poll models must account for this
mismatch before relying on timing. No timer rate, guest frequency global or
counter return value was changed here.

## Original initialization and concrete next access

SEC's platform initializer at `0x9fc0e45c` enters the one-time initializer
at `0x9fc17604`, then the original helper at `0x9fc22828`.
`ldr q0, [x8, #0x5f0]` at `0x9fc22850` succeeds at both ELs, reading the
original FV constant at `0x9fc325f0`. Existing controls are
`CPACR_EL1=0x300000` and `CPTR_EL2=0x33ff`; no new SIMD setup is needed for
this bounded path.

The descriptor initializer at `0x9fc22018` copies that 16-byte constant plus
24 zero bytes to `0x9fc3d728`. Traces verify all 40 destination bytes. The
selection wrapper at `0x9fc22bf8` calls `0x9fc2a140`, which constructs
`0x01fc8004` and reads it as uint32. The low two bits are compared with one:

| Observed low bits | Original selected descriptor |
| --- | --- |
| Exactly `1` | `0x9fc35728` |
| Any other value | `0x9fc356e0` |

The measured postboot value zero selects the second row if reused at modeled
entry. That reuse is the next explicit assumption to evaluate; it has not been
implemented in this milestone. No hardware register name is inferred solely
from this descriptor-selection code.

## Bounded trace and fault control

`trace_bridge_handoff.py --xbl-counter` requires the earlier exact query,
first buffer, second canary reply and measured hold-flag replay. It appends
19 counter/initialization checkpoints to the established chain and stops
before the selector read at `0x9fc2a150`, SP=`0x9ffcfaa0`.

Adding `--inspect-xbl-next-step` attempts only that original load. With the
current model it records:

| Path | Exception level | Syndrome | FAR | Vector PC |
| --- | --- | --- | --- | --- |
| Stock | EL1 | `0x96000010` | `0x01fc8004` | `0x9ff8c200` |
| Diagnostic | EL2 | `0x96000010` | `0x01fc8004` | `0x9ff8c200` |

ELR is the original load PC, and SP is unchanged. The handler is never executed.
The ordinary trace stops before attempting the load. An earlier
`--xbl-readiness` trace still stops before the counter read. Four controls
verify these earlier/default boundaries at stock EL1 and diagnostic EL2.

Throughout the new path, traces check the original canary, exact reply ledgers,
cache/hypervisor controls, EL and interrupt masks, workspace guards, stable
timer/SIMD controls, the computed result and descriptor bytes. The earlier
263 QHEE calls and 241-entry PMIC ledger remain unchanged. Stock still forwards
two buffer requests; diagnostic EL2 forwards neither through QHEE.

## Next implementation step

Extend the existing adjacent SoC-register device only for the exact uint32
selector read, using the repeated captured value under an explicit
postboot-to-entry/EL2 assumption. Preserve the existing `0x01fc8000` contract;
keep writes, other widths, neighbors and unsupported sequences denied.
Then follow the original selected descriptor to its next concrete dependency.
Do not substitute a whole register bank or bypass the original initializer.

The physical goal remains Linux receiving EL2 and running one CPU0 KVM guest.
Cold monitor records, hold-flag publisher/state, intervening UEFI/ABL/Linux
entry, image acceptance and recovery independent of ABL remain open.
Original cache maintenance in TCG does not establish physical coherency.
No phone firmware or partition was written, and no flashable candidate was
created by this tracing change.

## Reproduce and evidence

```sh
python3 tools/hyp_re/xbl_counter.py
python3 tools/hyp_re/test_counter.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/counter-regressions
```

- `reports/qhee-offline/counter-static/`: original windows and eight conversion slices.
- `kernel-work/out/qhee-counter-tests/results.json`: ten full profiles with bounded fault steps.
- `kernel-work/out/qhee-counter-tests/earlier-controls.json`: four earlier/unstepped stops.
- `reports/nio-platform-selector-20261006/manifest.json`: repeated fixed phone reads and EL1 context.
- `reports/qhee-offline/counter-regressions/results.json`: full regression results.
- `reports/qhee-offline/counter-milestone.json`: verified current evidence inventory.

## Subsequent milestone

The exact selector replay now executes at both modeled ELs; original SEC
selects/stores its descriptor and matches its table before the QUP wrapper
version read at `0x00ac0004`. See [selector and QUP boundary](EL2-XBL-selector.md).
The subsequent current milestone has 878 checks across 43 suites; counter
regression evidence above remains the historical 869/42 milestone.
