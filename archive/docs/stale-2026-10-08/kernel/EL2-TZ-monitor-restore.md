# Original TZ monitor restores and enters EL2 — 2026-10-06

The unchanged original TZ monitor now consumes the earlier synthetic boot
frame, restores the next context and executes its own ERET in QEMU. The
QHEE-present fixture arrives at `0x80040000` at EL2h, with `x0=0x9fc00000`,
`x1=2`, `x2=x3=0` and `SPSR=0x89`. This closes the final monitor-restore
boundary for the constructed records. Actual bootstrap inputs and full TZ
startup remain unverified; no physical EL2 or KVM execution is established.

Seven new tests exercise eight successful execution combinations plus an
unsupported-CPU failure. The current regression milestone is **778 checks
across 32 suites**. The previous [771-check milestone](EL2-TZ-handoff.md)
covered selectors and argument copying without the complete restore.

Follow-up: [TZ entry controls through full QHEE](EL2-TZ-entry-state.md)
now tests these controls across the full cold path and SEC prefix, adding
a terminal DAIF mask. Current suite: 788 checks across 33 suites; the
778-check evidence below remains this earlier milestone.

## What runs

Pinned TZ is unchanged: SHA-256
`74c85ae47fc470021db7d84eabc16e4089ab17727c677a9c528c051a00d2d7d8`.
`tz_monitor.py` supplies a synthetic saved SMC frame constructed from the
original selectors tested in `tz_handoff.py`. It executes:

1. Original context-layout initializer `0x1c01e310`. It sets the layout flag
   at `0x1c028158` to 1 and offsets at `0x1c029770/778` to `0/0x108`.
2. Original SMC handler at `0x1c019200`, starting directly with the seeded
   stack frame. No preceding SMC instruction or vector-save path is executed.
3. Original command 1 / selector `0x81` dispatch and context preparation,
   including the reached GIC CPU-interface setup.
4. Original secure-context save, next-context copy and register restore at
   `0x1c0194b0`.
5. Original return epilogue and ERET at `0x1c0192a8`.

Nine read-only debugger checkpoints cover the path. At the candidate target,
three independent diagnostic instructions read CurrentEL, DAIF and SCTLR.
QEMU is terminated while paused before the following NOP. No QHEE instruction
or XBL instruction is executed by this fixture. No debugger register or
memory edits are used while the original path runs.

The frame's context-SP field, previously left zero, is seeded with CPU0's
original literal `0x1c155290`. The secure stack helper itself remains
unexecuted. Other saved registers and unused frame fields are explicitly zero;
EL3/EL2 stacks and initial CPU state are fixtures. The monitor saves the secure
EL1 continuation context but never runs that continuation.

## Controls now resolved under these inputs

| Observed output | QHEE present | QHEE absent control |
| --- | --- | --- |
| Arrival PC | `0x80040000` | `0x9fc00000` |
| CurrentEL diagnostic | 8 (EL2) | 4 (EL1) |
| SPSR / arrival PSTATE | `0x89` | `0x85` |
| DAIF diagnostic | `0x80` | `0x80` |
| x0 / x1 | `0x9fc00000` / `2` | `0` / `0` |
| x2 / x3 | `0` / `0` | `0` / `0` |
| Final stored SCR | `0x505` | `0x405` |
| QEMU SCR readback | `0x535` | `0x435` |
| SCTLR_EL2 | `0` | `0` |
| HCR_EL2, input 0 | `0` | `0x80000000` |
| HCR_EL2, input RW only | `0x80000000` | `0x80000000` |

The initialized AArch64 layout places ELR/SCR/SPSR at context offsets
`0x1b8/0x1c0/0x1c8`. This differs from the zero-layout backing in the earlier
argument-only fixture; its x0–x3 conclusion remains valid, since those offsets
are unchanged.

Original `0x14680614` writes `SCTLR_EL2=xzr` before context preparation. The
initial fixture value `0x30c50830` is therefore replaced by original TZ code,
not by a debugger or monitor success stub. The arrival diagnostic independently
reads SCTLR=0.

The prepared SCR `0x504` is restored, then the per-CPU return path sets NS:
CPU0's table contains `0x505`, and the epilogue loads it into SCR_EL3. QEMU
readback includes its fixed bits `0x30`. The FIQ-routing bit remains set.
The arrival has only I masked; it does not inherit the earlier full-path
emulator's all-masked `0x3c9` entry state.

A zero HCR selector bypasses the RW update on the QHEE-present path. The two
HCR input controls demonstrate that this path preserves its supplied value.
The absent control sets RW before entering APPSBL at EL1. This does not
measure the phone's actual incoming HCR; that remains a bootstrap question.
The monitor also does not establish the physical incoming EL2 stack used by
our fixture.

## CPU identity and terminal failures

The earlier Cortex-A76 model has implementer `0x41`, part `0xd0b`. Original TZ
rejects that identity in its CPU-helper selector and loops at `0x146838e4`.
This is now a checked terminal control, with no patched instruction or fake
helper return.

The successful CPU controls are ordinary QEMU Cortex-A55 and the same model
with MIDR fields replayed from the phone's captured CPU0 cpuinfo:
implementer `0x51`, variant `0xd`, part `0x805`, revision 14, yielding
`0x51df805e`. Both identities select original null helper-table entries and
produce the same handoff. The identity replay does not emulate Kryo hardware,
CPU errata or SM8250 cache behavior. The capture path and hash are recorded.

Eight combinations cover CPU identity, QHEE present/absent and HCR 0/RW.
Additional guards reject unsupported HCR/CPU choices and altered TZ bytes.
Every logged translated original code block is compared byte-for-byte against
the pinned firmware. Loaded file-backed RAM bytes are independently checked.

## RAM backing and limits

`nio-tz-fixture-ram` is an optional QEMU device that supplies only RAM at
`0x14680000`/64 KiB and `0x1c018000`/96 KiB. The fixture loads original TZ
file-backed bytes there; uncovered bytes start at zero. It supplies no secure
service or SoC register behavior and is never enabled by the QHEE runner.
The reproducible build tool includes its source and records the rebuilt QEMU
hash. Existing QHEE models remain independent of this device.

GIC CPU-interface register operations execute against QEMU virt's GIC, not
captured nio hardware. The synthetic SMC frame, zeroed initial contexts,
CPU identity/stack and cold records remain explicit inputs. No complete TZ
initialization, XBL SMC bootstrap, cache-coherency proof, firmware acceptance,
physical interrupt behavior or recovery route is inferred.

## Next step toward CPU0 KVM

Apply this derived entry-state variation to the full modeled QHEE cold path:
SPSR `0x89`, software SCR `0x505`, SCTLR_EL2=0, with HCR 0 and RW-only controls.
Keep its real SP, preceding startup and secure-service replies identified as
assumptions. Compare stock and EL2 terminal paths under both GCC inputs before
extending the required SEC/UEFI/ABL boundaries.

The earlier full-path model remains at its original synthetic entry controls;
this milestone does not silently change them. Establish the bootstrap bridge
from XBL's `0x82000114` buffer to TZ entry pointers and the actual record
selection. Firmware acceptance and independent pre-ABL recovery remain
separate gates before a physical early-firmware test.

## Reproduce and evidence

```sh
python3 tools/hyp_re/build_qemu_model.py
python3 tools/hyp_re/tz_monitor.py --cpu cortex-a55,midr=0x51df805e
python3 tools/hyp_re/test_tz_monitor.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/tz-monitor-regressions
```

- `reports/qhee-offline/tz-monitor/`: canonical successful fixture, static
  windows in the manifest, checkpoints and translated instruction bytes.
- `kernel-work/out/tz-monitor-tests/`: eight successful fixtures and the
  terminal unsupported-CPU control.
- `reports/qhee-offline/tz-monitor-regressions/results.json`: current suites.
- `reports/qhee-offline/tz-monitor-milestone.json`: verified evidence hashes.

No phone access, partition write or original firmware-backup change occurred.
