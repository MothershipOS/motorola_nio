# EL2 readiness review — 2026-09-27

> Updated implementation evidence: [EL2-offline-results.md](EL2-offline-results.md).
> The decoder and emulator work below is now implemented; the full handoff remains unresolved.

## Recommendation

Keep the working LTS boot as the baseline. The next milestone is a validated
firmware-to-Linux EL2 handoff, beginning with offline analysis and full-system
emulation. The current SPSR patch is a hypothesis, not a deployable fix. Do not
use a blank hyp image as the next experiment.

## Confirmed state

- Saved Linux console logs show 6.18.54-mothership-nio-dev reaching init,
  `CPU: All CPU(s) started at EL1` and `kvm [1]: HYP mode not available`.
- The tested command line contains `maxcpus=1`. The EL1 result is conclusive
  for the booted CPU; it does not validate the other seven CPU startup paths.
- USB diagnostic shell, framebuffer diagnostics and ramoops recovery are
  recorded as working. M04 has an initial boot, not full phone hardware support.
- Both-slot hyp/xbl/abl/tz backup hashes were rechecked against the firmware
  manifest during this review. Backup existence does not establish recoverability
  after a fault before fastboot.
- No nio ADB, fastboot or diagnostic ACM connection was visible during this
  review. Current state is based on saved boot evidence, not a new phone test.

## Findings that qualify the earlier analysis

1. The original analyzer stopped after 203 instructions (0x32c of 0x6ab88
   bytes). This is fixed: the entire segment is now accounted for. Nine ERET
   candidates were found; a linear sweep of mixed code/data is not a CFG proof.
2. Entry x0/x1 are saved in x21/x22. The first initialization path branches
   directly to the dispatch at 0x800401bc, skipping table getters. Later entries
   use helpers at 0x800474c0 and 0x8004752c to load per-CPU tables. Table writers
   have been located, but the actual cold payload (UEFI/ABL versus Linux) and
   complete secondary-CPU contract remain unresolved.
3. Replacing register-clearing instructions with `msr sctlr_el2, xzr; isb`
   is not a validated MMU teardown. Check required register bits, VA-to-PA
   continuity, dirty cache cleaning, barriers, stack/vector ownership, interrupt
   routing and firmware call behavior. A raw zero write is not equivalent to a
   reviewed handoff sequence.
4. `secure: no`/engineering status does not by itself prove XBL accepts modified
   hyp contents. The patch tool changes instructions but does not update ELF/MBN
   hash metadata. Establish actual authentication/integrity policy and validate
   the final image container; do not assume that disabling signature enforcement
   disables every integrity check.
5. Unicorn can help with instruction-level/data-flow checks. A partially stubbed
   run cannot validate the real EL3/EL2, MMU/cache, interrupt-controller and PSCI
   contract. Use an explicit full-system model (for example QEMU plus an EL3
   harness) and document all unmodeled hardware behavior.
6. There is no verified nio EDL programmer/recovery procedure in the reviewed
   evidence. Keeping slot B stock is useful but does not prove XBL will fall
   back after a fault, nor that slot switching remains accessible.

## Ordered next steps

1. Freeze hashes of the known-working kernel/DTB/initramfs and preserve the
   validated diagnostic/recovery workflow.
2. Correct the analysis harness, trace the entry-table writers and all relevant
   return paths, and prove which stage currently selects EL1. Search for a
   supported firmware handoff mechanism before designing a patch.
3. Build the smallest full-system handoff experiment that reproduces the stock
   EL1 result. Only then test a candidate EL2 handoff with documented register,
   cache/MMU, firmware-call and secondary-CPU behavior.
4. Establish a device-compatible EDL recovery path that works without ABL before
   any hyp/XBL modification. Possessing backup files alone is insufficient.
5. If a candidate passes those gates, an on-device success requires Linux's
   verified EL2 entry and actual KVM guest execution, then timer/interrupt and
   multi-vCPU checks. `/dev/kvm` or KVM_CREATE_VM alone is not the final criterion.

Independent useful work: fix cpufreq/OPP/interconnect dependencies and bring up
all CPUs on the unchanged firmware. This advances both Linux usability and the
future shared CPU pool without depending on an EL2 firmware patch.

Reference: Linux ARM64 boot protocol,
https://docs.kernel.org/arch/arm64/booting.html (also the pinned 6.18.54 source's
Documentation/arch/arm64/booting.rst). All CPUs must enter at the same exception
level and satisfy the documented system-register/cache/MMU conditions.
