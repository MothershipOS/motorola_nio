# Executable CPU0 EL2 diagnostic transition — 2026-10-06

The complete modeled QHEE cold path now executes a synthetic diagnostic at
EL2 with the MMU, data cache and instruction cache disabled. Both GCC initial
clock-state experiments (`off`, `on`) print `EL2` and exit cleanly. This clears
the first-fetch blocker from the [SPSR-only experiment](EL2-entry-contract.md).
It does not establish a physical firmware-to-Linux handoff or working KVM.

## Implementation and bounds

`run_qemu.py --handoff-experiment el2-diag-mmu-off` makes two changes in the
emulator's loaded copy of the pinned original firmware:

| Range | Change |
| --- | --- |
| `0x800401d8`, 4 bytes | Select masked AArch64 EL2h, SPSR_EL2=`0x3c9` |
| `0x800402b0..0x8004032c`, 124 bytes | Replace final register clears/ERET with the diagnostic terminal transition |

The original register-clearing block is verified instruction-for-instruction.
The original image hash, segment base/end and expected SPSR instruction are
also checked. The replacement is exactly 31 instructions, occupies no extra
memory and leaves ERET at its original address `0x80040328`. It uses no stack,
calls or branches outside that block. Original backups and image-integrity
metadata are untouched; this is not a flashable candidate.

The transition is assembled from
`tools/hyp_re/emulator/el2_diag_transition.S`. It:

1. Derives the minimum D-cache line size from CTR_EL0.
2. Uses VA-based `dc cvac` loops for QHEE's image/BSS range
   `[0x80040000,0x8028b000)` and the synthetic probe range
   `[0x90000000,0x90001000)`.
3. Issues DSB, instruction-cache invalidation, DSB and ISB.
4. Reads SCTLR_EL2 and clears only `M|C|I` (`0x1005`), then issues ISB.
5. Clears x0–x3 and executes the original-address ERET with SPSR_EL2=`0x3c9`.

The entry contract is deliberately narrow: synthetic CPU0 AArch64 cold path,
with DAIF already masked and the original QHEE identity mappings. It does not
implement the AArch32 path or validate re-entry/secondary CPUs. HCR, TTBR,
timer/GIC configuration and QHEE service ownership are not taken over by this
diagnostic. Old translation entries are unused while M is clear; this is not
a reusable translation context or a complete Linux preparation routine.

## Read-only execution evidence

The tracer validates every 4 KiB page in the two cleaned ranges before the
transition: 587 QHEE pages plus one probe page. All map VA=PA and have Normal
memory attributes (`0x44` or `0xff`). The terminal code page is executable;
the probe remains non-executable in QHEE's unchanged EL2 stage-1 table.
The tracer also checks masked AArch64 entry, SPSR and the explicit target.
No debugger writes to registers, page tables or other guest memory occur.

Three new checkpoints observe transition entry, immediately before the SCTLR
write and immediately after it. The original pre-ERET checkpoint and two
normal instruction steps then observe the payload and its first fetch.

| Observation | Value in both runs |
| --- | --- |
| Entry SCTLR_EL2 | `0x8100f` |
| CTR_EL0 / derived stride | `0x8444c004` / 64 bytes |
| Cache-loop final x1/x2 | Both `0x90001000` |
| SCTLR_EL2 after write | `0x8000a`; all bits outside `0x1005` preserved |
| HCR_EL2 | `0x80080005`, preserved |
| Stack pointer | `0x801f6ff0`, preserved |
| Before ERET x0–x3 | All zero |
| After ERET | PC=`0x90000000`, CPSR=`0x3c9` |
| After first fetch | PC=`0x90000004`, ESR_EL2=`0` |
| Normal run | Clean exit 0, semihosting `EL2`, no firmware stop |

The first seven bridge checkpoints and all requests at the monitored SCM
instruction match the SPSR-only control runs. The 241 PMIC mapping ledger,
bridge handle and PRNG counts remain intact. Stage-1 and stage-2 descriptors
match the control; successful EL2 execution follows the MMU switch rather
than a permission edit.

## What remains before Linux/KVM

QEMU TCG does not model physical dirty CPU caches or system-cache coherency.
These results verify the instruction sequence, mappings, register transition
and subsequent execution. They do not prove the cache sequence is sufficient
on SM8250. The two clean ranges cover this diagnostic, not every boot-chain
allocation, Linux Image or DTB. CPU errata and physical cache handling still
need review for a real candidate.

The payload is the synthetic probe, not captured UEFI/ABL or Linux. x0 is zero
and supplies no DTB. Required timer/GIC state, SCR_EL3.HCE, PSCI behavior,
remaining firmware services and memory reservations remain unverified for a
Linux handoff. Other general registers retain diagnostic scratch/cold-path
values; clearing them is not an isolation or confidentiality proof.

Next establish the actual incoming target/width/argument contract and trace
the real UEFI/ABL kernel-launch path. The statically identified XBL SEC entry
is a candidate, not a capture of that target. Then adapt the terminal
transition to the verified stage, clean the real kernel/DTB ranges and satisfy
the pinned Linux boot contract before attempting CPU0 KVM guest execution.

Image acceptance and restoration independent of ABL remain separate hardware
gates. No phone access, boot or hyp/XBL write occurred in this milestone. The
last physical observation remains the October 5 diagnostic Linux EL1 boot
without `/dev/kvm`.

## Reproduction and checked artifacts

```sh
python3 tools/hyp_re/test_transition.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/transition-regressions
```

All **744 checks across 27 suites pass**, including the earlier 736 and eight
new transition cases. They cover patch bounds, original-instruction and memsz
guards, no stack/external control flow, emitted maintenance instructions,
CLI dependencies, complete-path execution and rejection of a changed stub.

- `kernel-work/out/qhee-transition-tests/{off,on}-el2-diag-mmu-off/manifest.json`:
  exact commands, model assumptions, original/loaded code and source hashes.
- Their `trace/manifest.json`: all eleven checkpoints, 588 page audits,
  ledgers, unchanged translation tables and ERET/fetch observations.
- `kernel-work/out/qhee-transition-tests/{off,on}-spsr-el2h/`: control runs.
- `reports/qhee-offline/transition-regressions/results.json`: all suite results.
- `reports/qhee-offline/diagnostic-transition-milestone.json`: aggregate
  evidence hashes and explicit scope.

All earlier SMEM, SMMU, TZ, PMIC, PIL and PRNG model assumptions still apply.
No physical TZ acceptance, modified-image acceptance, real Linux EL2 entry
or physical KVM guest execution is inferred.

Follow-up: [the original ABL boundary](EL2-ABL-boundary.md) now preserves
EL2 in isolated preparation/launch tests. XBL's configuration supplies a
`0x9fc00000` candidate. [The later SEC-prefix milestone](EL2-XBL-prefix.md)
executes the original prefix after full modeled QHEE and distinguishes the
interface configuration from a separate later secure call.
The current aggregate has 764 passing checks; the 744-check report above
records the earlier complete-cold-path diagnostic milestone.
