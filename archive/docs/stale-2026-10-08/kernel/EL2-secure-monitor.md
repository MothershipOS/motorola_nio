# Secure-monitor call resolved — 2026-09-28

> Current follow-up: [GCC/SMMU model](EL2-GCC-MMU-model.md) and
> [minimal KVM plan](KVM-PLAN.md). Results below describe the earlier milestone.

**Follow-up:** the [SMEM model and heap initialization](EL2-SMEM-model.md) now
advance QHEE to gcc_mmu_tcu_clk at 0x0017c02c. The sections below preserve the
secure-state investigation and initial SMEM capture milestone.

## Result

`0xc2000108` is **TZ_SECURE_WDOG_TRIGGER_ID**, QHEE's fatal-error watchdog
request. The original emulator reached it because it lacked a hardware-version
register at `0x01fc8000`, not because QHEE needed a normal initialization service.

A narrow QEMU device now supplies that read. With the original QHEE instructions
unchanged, execution passes the fault and reaches **0x42000604,
TZ_INFO_GET_SECURE_STATE**. A RAM-booted diagnostic kernel now measures the
EL1-visible response: status 0, r1 **0xf7f**, r2/r3 zero. Explicit replay of
that response, followed by a PSCI 1.1 version model, advances to SMEM layout
initialization at **0x01fd4000**. The pointer and layout metadata have also
been captured from nio, ready for the next bounded model addition.
No complete firmware handoff or phone KVM boot has been established.

## Evidence from this phone's firmware

The input remains `backups/nio-firmware-20260927T163534Z/hyp_a.img`, SHA-256
`f69538bf3fded342bb1679c3d01f0b2ad4ba930b235c11fda210efcf0240d8b2`.

- Function `0x80045618` logs a string at `0x8007afbf` naming
  `TZ_SECURE_WDOG_TRIGGER_ID`, builds the service identifier at `0x80045630`,
  and invokes the common SCM wrapper. Logging severity 4 also leads here.
- Capturing QHEE's own log ring at `0x80209200` reveals an EL2 synchronous
  external read abort: ESR_EL2 `0x96000010`, FAR_EL2 `0x01fc8000`,
  ELR_EL2 `0x80093da0`.
- The instruction is `ldr w11, [x8], #4`, bytes `0b4540b8`. QHEE's
  configuration initialization at `0x8005840c` copies four bytes from the
  hardware register to `0x801d4218`.
- Selector `0x80058308` compares the register's high 16 bits against the
  table at `0x800959a0`. This firmware's table names family **0x6008**.

The exact matching TZ dispatcher/handler has not been fully mapped or executed.
The call's identification and fatal purpose are established by the matching
QHEE caller, its string, and the executed fault path. Returning zero from the
watchdog request would not repair the aborted initialization.

Machine-readable evidence: `reports/qhee-offline/watchdog-evidence.json`.
Original recovered log: `reports/qhee-offline/watchdog-stop.txt`.
The translated instruction trace and decoded listing are saved alongside them.

## Implemented model

`tools/hyp_re/emulator/nio-soc-version.c` adds an optional QEMU device with one
four-byte register at `0x01fc8000`. Only an aligned 32-bit read succeeds. Writes,
byte reads, and neighboring addresses continue to abort. The model prints each
successful access and the value supplied.

The comparison uses **0x60080201**. Its family matches this QHEE table, and the
[reference SM8250 emulator](https://github.com/Qualcomm-HypX-Reversing/emulation/blob/3d440c31c578aafbfffc115f782da45120143360/qemu/qemu-8.0.0/hw/misc/qcom_misc.c)
supplies the same word at this address. **A read-only 32-bit `/dev/mem` read on
nio confirmed 0x60080201 on 2026-09-28.** The SCM IO_READ route returned -22;
its zero output is invalid and was not used. Evidence and image hash are in
`reports/nio-scm-live-20260928-direct/manifest.json`.

A clean upstream QEMU 8.2.2 source archive was used; the reference emulator's
firmware patches and generic success-returning monitor were not imported.
The only QEMU source addition is this optional device plus its build entry.
`build_qemu_model.py` reproduces the build. Archive, source and executable hashes
are recorded in `kernel-work/emulation/qemu-model-build.json`.

The generic QEMU virt board is still not SM8250. Other address ranges can collide
with unrelated QEMU devices; not every unsupported access is guaranteed to
fault. Timer logs, for example, are not real phone timing evidence.

## Differential and access tests

Seven integration checks pass:

| Case | Result |
| --- | --- |
| Register absent | Nonsecure EL2 read aborts |
| Modeled 32-bit read | Returns 0x60080201 |
| 32-bit write | Aborts |
| Read at adjacent address | Aborts |
| Byte read | Aborts |
| Original QHEE, model disabled | Fault at 0x01fc8000, then fatal watchdog request |
| Same QHEE and emulator, model enabled | No preceding QHEE abort; reaches secure-state query |

Results: `reports/qhee-offline/secure-call-tests.json`. Each whole-firmware case
has its own manifest under `kernel-work/out/qhee-secure-call-tests/`.
Eight analysis regressions and all four earlier isolated handoff tests also pass.
Fourteen additional checks in `test_replay.py` pass: secure-state and PSCI
responses preserve all unaffected general registers, SP and NZCV; unknown
services, watchdog, wrong arginfo, caller EL and SMC immediate stop; disabled
replay stops; invalid samples are rejected; original QHEE reaches PSCI then
the identified SMEM fault. See `reports/qhee-offline/replay-tests.json`.

The runner now captures the bounded QHEE log, decodes the terminal exception,
and classifies the watchdog request as `qhee_fatal_watchdog_request` rather
than an unexplained service boundary. Unknown calls still stop without a
fabricated response.

## Matching configuration segment

The real `devcfg_a.img` contains a QHEE segment at **0x805fd000**, matching the
address used by QHEE's initialization. `run_qemu.py --devcfg PATH` loads only
that segment and records both image and segment hashes. Its TZ segment is not
loaded or executed.

The run with this configuration still reaches the same secure-state query.
Some property warnings remain; loading the segment is not proof that all device
configuration, boot arguments or preceding firmware setup is correct.
See `reports/qhee-offline/soc-devcfg-run.json`.

## Reproduce

From the project root:

```sh
python3 tools/hyp_re/build_qemu_model.py
python3 tools/hyp_re/test_secure_call.py
python3 tools/hyp_re/run_qemu.py \
  --qemu kernel-work/emulation/qemu-build/qemu-system-aarch64 \
  --soc-hw-version 0x60080201 \
  --devcfg backups/nio-firmware-20260927T163534Z/devcfg_a.img \
  --secure-state-sample reports/nio-scm-live-20260928-direct/manifest.json \
  --psci-version 0x10001 \
  --out kernel-work/out/qhee-live-state-psci --trace
```

Omit `--soc-hw-version` to reproduce the original fault. No phone is needed and
none of these commands flashes firmware.

## Live secure-state query and replay

`0x42000604` is a 64-bit SiP information-service call, service 6 / command 4.
Qualcomm's published [SCM driver](https://android.googlesource.com/kernel/msm/+/15cf51a0f2ebde6529357685543e0b4170fb3b5c/drivers/soc/qcom/scm.c)
names this command `TZ_INFO_GET_SECURE_STATE`. It takes no arguments and returns
a security-state bitmask. QHEE's caller at `0x800434b8` checks transport status,
then consumes the returned word at `0x800434f8`, including bits 0 and 2.

`kernel/patches/0001-nio-read-only-scm-diagnostics.patch` exposes two fixed,
root-readable attributes through the existing SCM driver. It accepts no
arbitrary function identifiers or addresses. The build tool applies patches
idempotently and records their hashes. The tested image is
`kernel-work/out/scm-diagnostic-v2/boot-v2.img`, SHA-256
`40747057018ee89c9f964de97fa8d534a68cac9cb08facbb2a7e04abd2317a4d`.

The ABL overlay changes the root compatible to `qcom,kona-nio`; checking only
`motorola,nio` did not create the attributes on the first diagnostic attempt.
The guard now accepts both; the second RAM boot succeeded and supplied the
measurements. Collect again with `tools/capture_nio_scm.py --out NEW_DIR
--boot-image IMAGE --direct-register`.

The secure-state sample is **EL1-visible under the running QHEE**. Replaying it
for QHEE's own EL2 caller assumes both observe the same answer. Likewise,
PSCI 1.1 is the version Linux reports through QHEE, not a captured underlying
EL3 reply. Both are explicit model inputs, with markers and provenance in the
run manifest. Neither 0xf7f nor `secure=no` establishes firmware authentication
policy. Unknown calls and the fatal watchdog service still stop.

## Next boundary: SMEM target information

With both query models enabled, the unchanged QHEE faults at PC `0x8005f778`
reading `0x01fd4000`. The following instruction reads `0x01fd4004`; together
these supply a 64-bit pointer. QHEE checks the pointed structure's first word
against `0x49494953` (SIII). This matches Qualcomm's
[SMEM target-info definition](https://android.googlesource.com/kernel/msm/+/android-7.1.0_r0.2/drivers/soc/qcom/smem.c)
and the target-info register pair in its
[published device tree](https://android.googlesource.com/kernel/msm/+/3242618979ee08bc3b7fdac5d3950f7d702be0cd/arch/arm64/boot/dts/qcom/sdm845.dtsi).
The matching local LTS SMEM driver also defines the SIII layout.

`tools/capture_nio_smem.py` captured only the pointer pair and bounded layout
headers, with per-block hashes, from nio's reserved region. Evidence:
`reports/nio-smem-layout-20260928-v2/manifest.json`.

| Field | Measured value |
| --- | --- |
| Pointer registers | low 0x80aff230, high 0 |
| Target-info magic | SIII |
| SMEM base / size | 0x80900000 / 0x200000 |
| Item count | 625 |
| Table | 0x80aff000, version 1, 11 entries |

The original Android device tree independently reserves that same region.
The first collector attempt rejected a shell prompt attached to one output
line; its incomplete report is retained. The fixed parser's second capture
validated the pointer, reservation, table count and entry bounds, including
the table's own reserved entry. No SMEM item payloads were captured.

Next implement a bounded SMEM model using these metadata blocks. Reads outside
captured/modelled ranges must remain observable; do not silently provide a
zero-filled shared-memory heap or import another phone's SMEM dump. Establish
which boot-time items and synchronization operations QHEE requires before
extending it. These measurements are post-boot state, not an atomic snapshot
of the cold-boot state consumed by QHEE. This is still not a complete stock
handoff, an EL2 Linux transition, or validation of secondary CPUs.

Before any later early-firmware flash, EDL recovery and firmware integrity still
need validation. The phone remains on RAM-booted diagnostic Linux; no firmware
partition was flashed. The original working image remains preserved under
`kernel-work/baselines/nio-lts-el1-20260927/`.
