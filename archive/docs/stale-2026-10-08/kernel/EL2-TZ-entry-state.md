# TZ entry controls through full cold QHEE — 2026-10-06

The full modeled QHEE cold path now completes with the controls derived from
[original TZ monitor restore/ERET](EL2-TZ-monitor-restore.md): SPSR `0x89`,
software SCR `0x505`, SCTLR_EL2=0, and HCR initially either zero or RW-only.
The stock path still enters its payload at EL1. A revised bounded terminal
block sets all DAIF masks before cache maintenance and enters the diagnostic
probe or original XBL SEC prefix at EL2.

This resolves the mismatch between the earlier all-masked synthetic entry and
TZ's constructed-record output. It is an offline entry-state variation, not
one continuous execution from XBL through TZ and QHEE. Actual bootstrap
records, remaining startup state and physical KVM remain unverified.

Current progress: [original stack query and QHEE forwarding](EL2-XBL-stack-SMC.md)
now reaches the first SMC and checks routing, with 806 checks across 35 suites.

Ten new tests cover twenty derived-entry execution combinations and an
additional earlier-entry baseline. That milestone had **788 passing
checks across 33 suites**. No phone access or firmware partition write occurred.

## Explicit entry-state selection

`run_qemu.py --entry-state-model` accepts only three finite choices:

| Input control | `synthetic-masked` (default) | `tz-frame-hcr-zero` | `tz-frame-hcr-rw` |
| --- | --- | --- | --- |
| Software SCR_EL3 | `0x501` | `0x505` | `0x505` |
| SPSR_EL3 | `0x3c9` | `0x89` | `0x89` |
| Initial SCTLR_EL2 | `0x30c50830` | `0` | `0` |
| Initial HCR_EL2 | `0x80000000` | `0` | `0x80000000` |

`entry_state.py` pins TZ, reexecutes its bounded frame-building slice and
checks original instructions for the SCTLR reset, NS-bit update and conditional
HCR update. Each profile records its derivation, synthetic-record hash and
actual x0–x3 inputs. The earlier default controls remain available.

The derived variants require the existing bounded cold-path bridge model and
a payload at `0x90000000` or `0x9fc00000`. The former explicitly overrides the
candidate APPSBL address for the diagnostic; the latter uses the original
configured XBL candidate. The target override is recorded, not presented as a
captured boot record. x1=2 and x2=x3=0 are supplied explicitly.

The runner seeds these controls with its synthetic EL3 code. It does not run
the original TZ monitor in this fixture or inherit its complete context/GIC
state. The existing Cortex-A76 CPU model, EL2 stack at `0x803f0000`, timer
controls, other registers and finite SCM/MMIO responses remain assumptions.
The isolated original monitor tests separately cover CPU identity fields.

## Entry checkpoints and full-path results

The read-only tracer now inspects the initial synthetic ERET and steps normally
into `0x80040000` before QHEE executes. Derived-profile inspection is automatic;
`--inspect-entry` also checks the earlier default. It verifies all selected
controls and x0–x3. SCR readback includes QEMU's fixed bits: `0x535` for a
software write of `0x505`.

The matrix is two HCR inputs × two GCC clock inputs × five payload/transition
cases. Every case starts at EL2h with PSTATE `0x89`; QHEE's cold path retains
those DAIF masks until the terminal block.

| Case | Result under all four input combinations |
| --- | --- |
| Original QHEE, diagnostic target | Full cold path, ERET, diagnostic at EL1; exit 0 |
| SPSR-only loaded-code change | Selects EL2h; first fetch faults with ESR_EL2 `0x8600000e`, FAR `0x90000000` |
| DAIF-masking MMU-off diagnostic | Full cold path; masks DAIF, cleans audited ranges, clears M/C/I, diagnostic at EL2; exit 0 |
| Original QHEE, original XBL FV | Enters original SEC prefix at EL1 through VBAR setup |
| DAIF-masking MMU-off XBL transition | Enters original SEC prefix at EL2 through VBAR setup |

The complete cold SCM call sequence matches the earlier default baseline for
all twenty cases. The 241-entry PMIC ledger, bridge handle/bookkeeping, late
PRNG counts and other checked ledgers remain unchanged. This is agreement
between explicit offline models, not measurement of actual TZ acceptance.

Both HCR inputs converge to QHEE's original pre-handoff HCR `0x80080005` and
SCTLR_EL2 `0x8100f`. On the EL2 path, SEC subsequently sets HCR to `0x10` and
VBAR_EL2 to `0x9ff8c000`, as observed in the earlier prefix experiment.

## Why the terminal variant needed one more operation

The previous terminal stub required all DAIF masks to be set on entry.
The derived entry has DAIF `0x80`, and original QHEE preserves it through this
cold path. Changing the saved payload SPSR alone does not mask the current
CPU during the preceding cache/MMU transition.

New experiments `el2-diag-masked-mmu-off` and `el2-xbl-masked-mmu-off` begin
with `msr daifset,#15`. They still occupy exactly `[0x800402b0,0x8004032c)`:
124 bytes, 31 instructions, original ERET address `0x80040328`.

One two-instruction end-address calculation becomes
`add x2,x1,#0x24b,lsl#12`, preserving the QHEE clean range
`[0x80040000,0x8028b000)`. The saved instruction fits the DAIF operation.
Bytes from the first cache-clean instruction onward are identical to the
corresponding earlier terminal stub. Payload clean ranges, barriers,
SCTLR clear mask `0x1005`, register clearing and ERET remain unchanged.
No stack, new page tables, allocation or out-of-block calls are introduced.

A new checkpoint at `0x800402b4` verifies PSTATE masks `0x3c0` before the first
cache operation. Later checkpoints confirm those masks remain set across
SCTLR disable and ERET. The diagnostic audit covers 587 QHEE pages plus one
probe page; XBL covers the same 587 plus 768 FV pages. Identity and Normal-memory
mappings are checked before maintenance. This does not validate dirty caches,
system-cache behavior or coherency on physical hardware.

Earlier terminal bytes retain their pinned hashes. The CLI rejects pairing a
TZ-derived entry with those earlier stubs, since their mask precondition would
not hold. It also rejects unsupported profiles/targets and tampered metadata.
Original firmware files remain unchanged; loaded-code copies do not have
updated image integrity metadata and are not flash-ready firmware candidates.

## Remaining work and next bounded step

1. Extend the original SEC path beyond VBAR setup only through required
   workspace/vector/BSS/stack initialization and the next concrete service
   boundary. Establish which subsequent register changes or firmware services
   affect an eventual Linux EL2 handoff.
2. Trace the bootstrap bridge from XBL's `0x82000114` buffer to TZ entry
   pointers and actual boot-record selection. These inputs remain unmeasured.
3. Validate a minimal CPU0 diagnostic candidate and separately establish image
   acceptance and recovery independent of ABL before an early-firmware test.
4. Require physical Linux at EL2 and a checked one-vCPU KVM guest result.

The modeled cold initialization and initial SEC entry no longer depend on an
all-masked incoming SPSR. Full UEFI/ABL/Linux execution, required service
availability, physical interrupt/timer behavior and recovery still remain open.

## Reproduce and evidence

```sh
python3 tools/hyp_re/test_tz_entry_state.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/tz-entry-regressions
```

To use the existing full-cold-path arguments, append
`--entry-state-model tz-frame-hcr-zero` or `tz-frame-hcr-rw`.
For an EL2 diagnostic use `--handoff-experiment el2-diag-masked-mmu-off`.
For original SEC use target `0x9fc00000`, `--prepare-only`, experiment
`el2-xbl-masked-mmu-off`, then `trace_bridge_handoff.py --xbl-prefix`.
The unit suite records those complete commands and input hashes.

- `kernel-work/out/qhee-tz-entry-tests/`: twenty execution cases and default
  baseline, manifests, entry/terminal checkpoints and page audits.
- `reports/qhee-offline/tz-entry-regressions/results.json`: entry-state milestone results.
- `reports/qhee-offline/tz-entry-milestone.json`: verified evidence hashes.
