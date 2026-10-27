# nio EL2 offline results — 2026-09-27

> Follow-up: [secure-monitor resolution](EL2-secure-monitor.md). The original
> 0xc2000108 stop is now identified as a fatal watchdog request caused by the
> missing hardware-version register. The optional register model gets past it
> to 0x42000604 (secure-state query). The initial results below remain a record
> of the baseline before that model was added.

## Decision

The offline harness is implemented. It establishes a local EL-selection effect,
not a complete firmware-to-Linux handoff. No firmware was flashed. Keep the
known-working Linux 6.18.54 EL1 boot while investigating the secure-monitor
contract and establishing recovery independent of ABL.

The phone was not visible in the final USB inventory. Hardware claims below are
from saved logs, not a new boot in this investigation.

## Preserved baseline

The working Image, diagnostic DTB, initramfs and boot-v2.img are copied into
`kernel-work/baselines/nio-lts-el1-20260927/`. Its manifest records full SHA-256
hashes; source artifacts were checked against their build manifests and recorded
boot-image hash. Saved boot logs are under
`reports/nio-diag-boot-20260927T161817Z/`.

These logs confirm EL1 and unavailable KVM with `maxcpus=1`. They do not validate
secondary CPU startup. Firmware backups cover both slots and GPTs but do not
establish recovery after a fault before fastboot.

## Static analysis corrected

Input `hyp_a.img` SHA-256:
`f69538bf3fded342bb1679c3d01f0b2ad4ba930b235c11fda210efcf0240d8b2`.

The old Capstone sweep stopped after 203 instructions at the first embedded
undecodable word. The analyzer now preserves four-byte alignment and accounts
for the entire 0x6ab88-byte executable segment: 0x39360 bytes decode as instruction
candidates and 0x31828 are undecoded. This is coverage of bytes, not a proof of
reachable code. Nine ERET candidates are reported in
`reports/qhee-offline/sweep.json`.

The cold path and later CPU entry paths differ:

- Entry saves x0 in x21 and x1 in x22. On the first initialization path,
  `0x8004017c -> 0x800401bc` skips the table getters. This corrects the earlier
  review's implication that the cold path necessarily overwrites these values.
- Re-entry through `0x80040180` loads per-CPU entry tables
  `0x801cc108 / 0x801cc148` and width table `0x801cc1c8`. Argument table
  `0x801cc188` supplies x0 before return.
- Writers include `0x80047684 / 0x800476a4`; wrappers at `0x800476d4`,
  `0x800477d4`, and `0x8004792c` populate entry, width and argument slots.
  Their full CPU/secure-monitor semantics still need tracing. Disassembly is
  saved in `reports/qhee-offline/table-paths.txt` and `cold-init.txt`.
- At `0x800401bc`, x21 becomes ELR_EL2. Width 2 selects SPSR_EL2=0x85
  (AArch64 EL1h) at `0x800401d8`; width 1 selects 0x93 (AArch32 SVC).
  SPSR_EL2 is written at `0x80040210`, with ERET at `0x80040328`.
- Startup enables SCTLR_EL2.M/C only when the saved translation-table pointer
  is nonzero. Earlier descriptions that it always enables the MMU were too broad.

The real initial payload address and identity have not been captured. Do not
assume this return goes directly to Linux rather than intermediate firmware.
The other eight ERET candidates have not all been control-flow classified.

## Full firmware model: explicit secure-monitor stop

`tools/hyp_re/run_qemu.py` builds a synthetic EL3 harness and runs the original
QHEE code on QEMU virt with secure mode and virtualization enabled. QEMU 8.2.2
and its dependencies are extracted locally under `kernel-work/emulation/`;
package hashes are in `packages.lock.json`. Nothing is installed system-wide.

The run reaches an SMC at `0x80041a4c` and stops:

| Register | Observed value |
| --- | --- |
| ESR_EL3 | 0x5e000000 (SMC64 exception) |
| ELR_EL3 | 0x80041a50 (return PC after SMC) |
| SPSR_EL3 | 0x800003c9 (caller at EL2h) |
| x0 | 0xc2000108 |
| x1 | 1 |
| x2, x3 | 0, 0 |

The service behavior is unresolved. The harness does not fabricate a success
response. Its machine-readable outcome is `blocked_at_unmodeled_el3_exception`,
even though semihosting cleanly terminates QEMU with process exit 0.
See `reports/qhee-offline/full-run.json` for logs, command and tool hashes.

This is not SM8250 emulation: no Qualcomm MMIO, actual TZ, ABL or Linux runs.
EL3 initial arguments and system-register state are assumptions. It has **not**
reproduced the complete stock handoff, much less validated a phone patch.

## Isolated handoff tests: four pass

`test_handoff.py` extracts actual instruction ranges
`0x800401bc..0x80040214` and `0x800402b0..0x8004032c` (end exclusive), then runs
those slices against a synthetic payload that reads CurrentEL and SCTLR_EL2.
Intermediate QHEE setup is intentionally omitted.

| Model | Observed payload EL | SCTLR_EL2 | Conclusion |
| --- | --- | --- | --- |
| Stock dispatch | EL1 | Not read from EL1 | Original constant selects EL1h |
| SPSR=0x3c9, MMU initially off | EL2 | 0x30c50830 | Constant selects EL2h |
| SPSR=0x3c9, identity MMU on | EL2 | 0x30c50835 | SPSR patch leaves M/C enabled |
| Same, model clears M/C | EL2 | 0x30c50830 | Model transition works under its assumptions |

The final case preserves SCTLR's other bits and uses an identity map. It is not
an implementation of phone Patch B and does not validate dirty-cache cleaning,
real translation continuity, vectors, stage-2 ownership, PSCI or other CPUs.
Results and tool hashes: `reports/qhee-offline/handoff-slices.json`.

## Firmware integrity and recovery

The stock executable segment's SHA-384 digest occurs at file offset **0x1138**.
An instruction edit changes that digest while the existing patch tool leaves
hash/signature metadata untouched. It therefore creates an integrity-inconsistent
analysis copy. Updating a digest alone would not establish signature validity.
`secure=no` does not establish which XBL integrity/authentication checks apply.

`hyp_patch.py` now reports this limitation, protects the input and backup tree,
and refuses to replace existing outputs. It does not rehash, sign or flash.

No compatible EDL programmer or tested recovery route is established. A search
found a third-party listing labelled nio / XT2125-4 blankflash, but its bytes,
authenticity, configuration and compatibility were not verified; it is only a
lead. Slot B is not proven automatic recovery for a pre-ABL failure. Do not use
a blank hyp or modified early firmware as the next phone experiment.

Recovery work must identify a matching programmer/package, inspect its intended
writes, and establish its read/restore operation on this hardware. A generic
Firehose tool or matching SoC name is insufficient evidence.

## Reproduce

From the project root, with Capstone and aarch64-linux-gnu-gcc available:

```sh
python3 -m unittest discover -s tools/hyp_re -p test_analysis.py -v
python3 tools/hyp_re/analyze.py --json reports/qhee-offline/sweep.json
python3 tools/hyp_re/run_qemu.py
python3 tools/hyp_re/test_handoff.py
python3 tools/hyp_re/hyp_patch.py
```

Seven regression tests pass: decoding across an invalid word, ELF/read bounds,
EL3 outcome classification, embedded digest evidence, and copy-only patch
behavior. All four isolated QEMU tests pass. The full firmware run stops at the
unmodeled SMC as described above; it is not counted as a successful handoff.

## Next work in order

1. Identify the semantics of `0xc2000108` in the matching TZ/boot interfaces;
   trace its caller and the cold payload address. Extend the model only with
   sourced behavior and label every assumption.
2. Reach the stock payload through the complete modeled path. Then evaluate an
   EL2 transition against actual register, MMU/cache and firmware ownership
   requirements; trace secondary entry paths separately.
3. Establish and verify recovery before considering an early-firmware write.
4. Independently fix cpufreq interconnect/OPP dependencies and test all CPUs on
   unchanged firmware. Those tests need the phone reconnected.
5. A later hardware EL2 milestone requires KVM guest instruction execution,
   followed by timer/interrupt and multi-vCPU tests, not merely `/dev/kvm`.

Reference requirements: [Linux ARM64 boot protocol](https://docs.kernel.org/arch/arm64/booting.html).
The locally pinned kernel has the same relevant requirements in
`Documentation/arch/arm64/booting.rst`. Model platform:
[QEMU virt documentation](https://www.qemu.org/docs/master/system/arm/virt.html).
