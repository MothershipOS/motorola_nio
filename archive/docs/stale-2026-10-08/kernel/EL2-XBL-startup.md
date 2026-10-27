# Original XBL vector, BSS and temporary stack — 2026-10-06

The full modeled QHEE cold path now executes original XBL SEC past VBAR setup,
through its vector stores, SIMD BSS clear and temporary stack assignment.
The EL2 experiment retains EL2 at the next call, `0x9fc0cf28`. Stock QHEE
provides an EL1 control. This is offline evidence; the phone's last verified
Linux boot remains at EL1 without `/dev/kvm`.

Current progress: [original stack query and QHEE forwarding](EL2-XBL-stack-SMC.md)
now reaches the first SMC and checks routing, with 806 checks across 35 suites.

Nine new tests cover ten startup combinations and an additional legacy-prefix
trace. That milestone had **797 passing checks across 34 suites**.
No phone access, partition write or original firmware modification occurred.

## Exact execution boundary

The existing `--xbl-prefix` still stops at `0x9fc0ceb4`, before workspace
initialization. New `trace_bridge_handoff.py --xbl-startup` runs through
`0x9fc0cf28`, then terminates QEMU while paused before that instruction's call
to the stack-sizing helper at `0x9fc21ce8`. Both modes validate the pinned
original 3 MiB FV and loaded-code experiment before execution.

Only the emulator's loaded QHEE terminal block changes for the EL2 variant.
SEC instructions, literals, store loops and helper bytes remain original.
There are no debugger writes to guest registers or RAM. Other XBL segments
remain unloaded; physical RAM permissions and firmware services remain open.

| Original operation | Evidence after execution |
| --- | --- |
| Read MPIDR and take CPU0 startup branch | x4 from original `mrs` at `0x9fc0ceb8`; relevant affinity bits zero |
| Store startup timestamp | `0x9fc0cd60` equals SEC's x19 timestamp |
| Fill `[0x9ff8c000,0x9ff8c800)` | 256 copies of original literal `0xaa0403f314000000` |
| Enable SIMD through CPACR_EL1 | `0x300000` before the first SIMD zero operation |
| Clear `[0x9ff90000,0x9ffd0000)` | All 256 KiB zero after original `st4` loop |
| Establish temporary stack | SP=`0x9ffd0000`, x0=`0x40000` at `0x9fc0cf28` |

The vector literal contains a self-branch as its first instruction. This fill
provides an early stop loop, not a functional exception handler. The tracer
places read-only breakpoints at all sixteen vector slots and rejects an
exception entry rather than silently continuing.

On EL2 runs, HCR remains `0x10` after SEC's earlier write. SCTLR_EL2 remains
`0x8000a` with M/C/I off, VBAR_EL2 remains `0x9ff8c000`, and all DAIF masks
remain set. QHEE supplied CPTR_EL2=`0x33ff` (TFP clear), and original SEC's SIMD
clear executes without an exception. QEMU exposes CPACR_EL1 as `CPACR` to GDB;
MPIDR is observed through SEC's original x4 result.

## Sentinel experiment and controls

`run_qemu.py --xbl-workspace-sentinel` is accepted only with the original XBL
target and `--prepare-only`. Two finite loader images initialize vectors and
BSS to `0xa5`, with sixteen-byte guards before and after each range. They are
synthetic RAM contents, not firmware patches or captured phone memory.

The tracer verifies that all sentinel bytes still exist at the earlier VBAR
boundary. Original SEC then overwrites the full vector table and BSS. Whole
range hashes verify the results, and every surrounding guard remains `0xa5`.
This distinguishes actual original stores from QEMU's default zero RAM.
The loaders, files and metadata are checked before QEMU starts; changed bytes,
missing loaders and unreported loaders are rejected.

Eight sentinel executions cover two TZ-derived initial HCR inputs × two GCC
inputs × stock EL1 / terminal EL2 paths. Two additional controls use the earlier
synthetic entry and ordinary zero-backed RAM. All ten pass. The original cold
SCM call sequence, bridge handle, 241 PMIC ledger entries and model counters
agree across the matrix. One additional trace confirms the legacy prefix still
stops before these stores.

Existing synthetic EL3, CPU, timer, RAM and finite SCM/MMIO response assumptions
remain. These results do not validate physical cache coherency, secure ownership,
secondary CPUs, later stack sizing or a complete UEFI/ABL/Linux boot.

## Next concrete service boundary

The call at `0x9fc0cf28` enters original stack-sizing code. Static dataflow shows
it consumes a nibble from global `0x9fc3d710`, invoking source dispatcher
`0x9fc2849c` when empty. Its selector at `0x9fc356c8` is zero in the original FV.
Under that condition, the dispatcher reaches:

```text
0x9fc284dc: smc #0
x0 = 0x02000601
x1 = 1
x2 = 0x02000602
```

This is conditional static evidence, not a captured execution or supplied reply.
The subsequent [stack-query milestone](EL2-XBL-stack-SMC.md) inspects both
globals and executes the original stack prologue/dispatcher to this SMC. Capture inherited x3–x7 and compare
EL1 and EL2 routing before deciding whether any exact service model is needed.
The existing QHEE PRNG model does not establish support for this XBL call.
Subsequent branches contain different service IDs and buffer conventions.

Actual XBL bootstrap records, required later firmware services, the Linux entry
contract, firmware image acceptance and recovery independent of ABL remain the
hardware-test gates. The current loaded-code experiment is not flash-ready.

## Reproduce and evidence

```sh
python3 tools/hyp_re/test_xbl_startup.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/xbl-startup-regressions
```

For a prepared original-FV fixture, append `--xbl-workspace-sentinel` to the
existing full-cold runner arguments, then use `--xbl-startup` on the tracer.
The test manifests record complete commands, input hashes and selected models.

- `kernel-work/out/qhee-xbl-startup-tests/results.json`: ten startup cases.
- `reports/qhee-offline/xbl-startup-static/`: original instruction windows,
  literals and conditional next-service dataflow.
- `reports/qhee-offline/xbl-startup-regressions/results.json`: startup milestone suites.
- `reports/qhee-offline/xbl-startup-milestone.json`: verified evidence inventory.

The earlier entry-state milestone is documented in
[TZ entry controls through full QHEE](EL2-TZ-entry-state.md).
