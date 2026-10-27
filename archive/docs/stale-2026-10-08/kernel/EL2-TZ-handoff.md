# Original TZ boot records and QHEE argument frame — 2026-10-06

Original TZ instructions now select QHEE and prepare its next-stage arguments
in bounded offline fixtures. With synthetic AArch64 APPSBL and QHEE records,
the resulting QHEE context has `x0=0x9fc00000`, `x1=2`, `x2=x3=0`.
A separate original monitor slice copies those four arguments into the next
context. This gives the earlier QHEE fixture a firmware-derived basis; it
does not establish the contents of the phone's actual boot records.

All **771 checks across 31 suites pass**. Seven new tests cover the record
layout, original frame construction, argument copy, width controls, version-3
selection, fallback, malformed inputs and firmware pin rejection. Physical
Linux remains last observed at EL1, without `/dev/kvm`.

Follow-up: [original monitor restore and ERET](EL2-TZ-monitor-restore.md)
now closes the final restore for these synthetic records. The current suite
has 788 checks across 33 suites; the 771-check evidence below is historical.

## Buffer dataflow and the remaining bootstrap boundary

Pinned TZ SHA-256:
`74c85ae47fc470021db7d84eabc16e4089ab17727c677a9c528c051a00d2d7d8`.
The static inventory records fourteen original instruction windows and their
hashes. No firmware instruction is changed by these fixtures.

XBL's separate later SMC uses `x0=0x82000114`, `x1=0x22`,
`x2=0x80716100`, `x3=0xe00`; see [the XBL trace](EL2-XBL-prefix.md).
The original TZ dataflow is:

1. TZ entry preserves its incoming pointers and stores them at `0x1468d008`
   (`stp x0,x1` at `0x146800e8`).
2. `0x146804f8` reads their low 32 bits and copies `0xe00` bytes from the
   first pointer into `0x1c02c008`. It copies a separate 16-byte object from
   the second pointer into `0x1c02ce08`. The getter at `0x14684014` returns
   the first internal buffer.
3. The secure startup branch at `0x1c04baa8` obtains that buffer and calls
   `0x1c04f470`, copying it into `0x1c179c18`.
4. The cold initialization branch reaches `0x1c04b6a8`, which constructs
   the next context frame from those records.

The bridge from the XBL SMC to TZ's ELF-entry pointers remains untraced.
Searching the pinned TZ image did not find the SMC identifier as a literal;
that does not prove cold-boot rejection. Runtime SCM dispatch and bootstrap
entry are different boundaries. We have not executed the full secure startup.

## Record layout and original execution

The selectors use a `0xe00`-byte table: version at offset `0x8`, count at
`0xc`, records at `0x18`, stride `0x110`. Each record starts with a 32-bit
image ID, a 32-bit width and a 64-bit entry address. Version 3 additionally
uses the selected record index at `0xdf8`.

Original search is bounded to thirteen records. APPSBL selects image ID 9
(with an ID 14 fallback); QHEE selects image ID 21. `0x1c04bf4c` distinguishes
QHEE present from direct APPSBL entry. The synthetic fixtures seed ID 9 with
XBL's configured `0x9fc00000` candidate and ID 21 with `0x80040000`.
These are candidate records, not a captured table. A version-3 control that
selects the other record changes the forwarded target, demonstrating that
actual record contents matter.

`tz_handoff.py` executes unchanged frame-building code from `0x1c04b710`
to `0x1c04b7e4`, along with only its reached selectors. It seeds CPU0, a frame
pointer and a stack; execution and writes have explicit bounds. It stops
before the context-stack helper `0x1c1195f4`. Missing records and unsupported
paths fail within the instruction limit. No MMIO or secure initialization is
modeled by this slice.

| Prepared field, both widths 2 | QHEE present | QHEE absent control |
| --- | --- | --- |
| Next PC | `0x80040000` | `0x9fc00000` |
| Next x0 / x1 | `0x9fc00000` / `2` | `0` / `0` |
| Next x2 / x3 | `0` / `0` | `0` / `0` |
| HCR RW selector | `0` | `1` |
| Prepared SPSR | `0x89` (EL2h, I masked) | `0x85` (EL1h, I masked) |
| Prepared SCR | `0x504` | `0x404` |
| Frame-slice instructions | 204 | 133 |

The six width controls also cover AArch32 records. They test prepared frame
values, not AArch32 execution. In particular, QHEE width 1 prepares SPSR
`0x9a` and SCR `0x104`; width 2 prepares `0x89` and `0x504`.

## Monitor argument copy and control limits

Static monitor dispatch for command 1 / selector `0x81` resolves through
`0x1c01d8f4` and `0x1c01d924` toward context preparation. A second independent
fixture seeds the emitted frame and executes `0x1c01d444..0x1c01d4a4`, including
its original byte-flag getter. It confirms frame slots `0x10..0x28` become
the next context's x0..x3. It stops before ELR, HCR, SPSR, SCR and context-stack
handling; the rest of monitor dispatch and ERET are not executed.

The prepared SCR is not a measurement of QHEE's incoming SCR: later monitor
handling must establish the final nonsecure state. Likewise, prepared SPSR
`0x89` differs from the earlier emulator's deliberately masked entry `0x3c9`;
its synthetic starting SCR is `0x501`. Do not silently replace the full-path
model's controls or claim a physical register capture. The frame's RW selector
zero also requires following its actual monitor interpretation.

## Next bounded work

1. Trace final monitor control restoration and ERET, including nonsecure SCR,
   HCR, SPSR, ELR and context SP. Reconcile the prepared `0x89` with the masked
   QHEE fixture before extending the CPU0 boot-chain experiment.
2. Establish how bootstrap supplies TZ's entry pointers and the actual boot
   record selection. Then extend only the necessary SEC/UEFI/ABL register and
   service boundaries toward Linux.
3. Validate a minimal diagnostic candidate and separately establish image
   acceptance and recovery before ABL. Those remain prerequisites for a
   physical early-firmware change.
4. Require physical Linux EL2, `/dev/kvm`, and a checked one-vCPU guest result
   before resuming Ubuntu/Android and resource-sharing work.

We are closer to a concrete CPU0 EL2 experiment. The final secure restore,
intervening boot stages and hardware acceptance/recovery still prevent a
reliable estimate of distance to physical KVM.

## Reproduce and review

```sh
python3 tools/hyp_re/tz_handoff.py
python3 tools/hyp_re/test_tz_handoff.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/tz-handoff-regressions
```

- `reports/qhee-offline/tz-handoff-static/`: original windows, layout, dispatch
  metadata and QHEE-present/absent execution logs.
- `kernel-work/out/tz-handoff-tests/width-controls.json`: six control fixtures.
- `reports/qhee-offline/tz-handoff-regressions/results.json`: all 31 suites.
- `reports/qhee-offline/tz-handoff-milestone.json`: verified evidence hashes.

No phone interaction, partition write or original backup change was performed
for this milestone. No full TZ boot, monitor ERET, physical EL2 transition or
KVM guest execution is claimed.
