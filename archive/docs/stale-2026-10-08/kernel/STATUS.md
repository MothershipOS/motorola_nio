# Kernel status — 2026-10-06

## Slot-B candidate boot: HARD BRICK, then EDL-recovered — 2026-10-06

The modified `hyp_b` EL2 candidate did NOT boot: on `reboot bootloader` to slot B
the phone went fully dark — no USB enumeration, fastboot or ADB. A bad hyp faults
before ABL runs, so fastboot never comes up (expected for a hyp-stage failure).
No early-boot EL2 result could be inferred; the candidate simply failed to boot.

**Recovered via EDL 9008 the same day.** Forced EDL (Vol-Up+Vol-Down + plug USB),
Sahara-uploaded the Moto-signed SM8250 firehose, and restored the stock `hyp_b`
partition from backup (LUN5/LBA1184/2048 sectors). Phone then booted normally on
slot B (Android 16, adb up). No bootloader partition was written; Moto `qboot`/
`singleimage` was NOT run (anti-rollback risk avoided). hyp_a was verified stock
throughout. **Independent EDL recovery is now PROVEN** — see `unbrick/`. **Root cause (corrected 2026-10-06)**: secure boot is NOT enforced on this engineering unit (`secure=no`, `secure_hardware=0`) — an on-device test booted a stock-code hyp with a deliberately corrupted signature, proving the signature is ignored. So the modified hyp's code executed and the non-boot was the **EL2 patch faulting at runtime**, not the stale signature. See `kernel/EL2-hypb-nonboot-cause.md`.
Firehose loader saved: `backups/nio-firmware-20260927T163534Z/prog_firehose_ddr_SM8250.elf`.

Evidence: `reports/nio-el2-slot-b-boot-20261006/`.
The inactive-slot-only result below describes the earlier staging phase.

## Physical EL2 candidate staging — 2026-10-06

The user authorized creating and flashing an EL2 firmware candidate. The
8 MiB `el2-xbl-masked-mmu-off` image was written successfully to inactive
`hyp_b`; slot A remains active and original. Rooted Android readback verified the exact
candidate in B and the unchanged original in A. Flashing marked B unsuccessful
but did not mark it unbootable. The candidate changes two code ranges and
repairs the code SHA-384 entry. Its preserved OEM signature is stale.

Four new packaging checks and nine existing XBL startup checks passed.
This is a real partition write, **not physical EL2/KVM execution**. No modified
firmware has been booted. Fastboot acceptance does not establish early-boot
authentication. Independent EDL recovery remains unverified. The phone was returned to the
working diagnostic Linux USB shell on original slot A (EL1, no KVM).

Artifacts and physical preflight/write/readback records:
`reports/nio-el2-firmware-20261006/README.md`.
Builder: `tools/hyp_re/build_firmware_candidate.py`.
Candidate: `kernel-work/out/el2-firmware-20261006-v1/hyp-el2-xbl-masked.img`.

## Summary

Linux 6.18.54 boots on the connected nio via `fastboot boot` (RAM only, no
partition writes) and reaches a busybox initramfs with a USB CDC-ACM root shell.
Reproduced on four consecutive boots. Logs are available over USB, and the
previous kernel log (including panics) survives in ramoops.

**KVM/M03 blocker:** the kernel is entered at EL1 (`CPU: All CPU(s) started at
EL1`, `kvm [1]: HYP mode not available`). The Qualcomm hypervisor keeps EL2,
so no Linux configuration change can create `/dev/kvm`. M03 needs a boot-chain
answer (firmware that hands EL2 to Linux) or an explicit architectural decision.

## Implemented

- Pinned Linux 6.18.54 LTS archive and checksum; reusable preparation/build tools.
- ARM64 Qualcomm host config with KVM, cgroups, PSI and VM networking support,
  plus bring-up options: simpledrm/fbcon, qcom-pon + syscon reboot-mode, APSS
  watchdog, USB gadget ACM/NCM, 1 MiB printk buffer, TER16x32 console font.
- nio DTS: 25 live fixed reservations, ABL-compatible selection IDs/model,
  `/chosen/bootargs`, splash simple-framebuffer, PM8150 USB PHY rails,
  USB 2.0 peripheral (`a600000.usb`), PON and IMEM reboot-mode.
- Diagnostic variant: ramoops (stock layout), bootargs, ABL overlay sink.
- Diagnostic initramfs: verified Ubuntu arm64 busybox-static, `nio-diag` helper
  (KVM probe, reboot with mode), USB ACM shell, 180 s auto-return to fastboot
  when no host attaches.
- Host tools: `fastboot_diag_boot.py` (boot + collect), `nio_console.py`.

Original artifacts are preserved under `kernel-work/baselines/nio-lts-el1-20260927/`
(boot image `f9d5dda7…6411dc5`). The current, RAM-boot-tested SCM diagnostic image
is `kernel-work/out/scm-diagnostic-v2/boot-v2.img`, SHA-256
`40747057018ee89c9f964de97fa8d534a68cac9cb08facbb2a7e04abd2317a4d`.
It adds fixed root-readable SCM queries; the DTB and initramfs are unchanged.
Build patches and input hashes are recorded in the build/package manifests.

## Measured on this phone

| Item | Evidence |
| --- | --- |
| Hardware | nio / XT2125-4; MemTotal 7,837,876 kB (Android), 7,754,196 kB (6.18) |
| Installed Android kernel | 4.19.325-cip136-st20-perf+, built with clang 19.1.7 |
| Current RAM boot | 6.18.54-mothership-nio-dev, SCM diagnostic v2 |
| SoC register | 0x01fc8000 reads 0x60080201; SCM IO_READ denied (-22), direct read succeeded |
| Secure state | EL1-visible query status 0; r1=0xf7f, r2=r3=0; not proof of hyp authentication policy |
| TZ-log pointer | Fixed read at 0x146bf720 returns 0x14695000 |
| SEC hold flag | Two postboot EL1 reads at 0x146bf944 return 0x3a6506a5; publisher/cold state unverified |
| PMIC arbiter | Version 0x50010000; captured 512 APID, 512 owner and 256 secondary mapping words; read-only |
| Command-database pointer | Fixed read at 0x0c3f000c returns 0x80860000; surrounding SRAM not captured |
| SMEM layout | Pointer 0x80aff230; 2 MiB at 0x80900000; table version 1, 11 entries |
| Root | Existing Magisk `su` returns uid 0 (may fail for ~10 s after boot) |
| Bootloader | MBM-3.0-nio_retail-9376d694c3-220503; secure=no, securestate=engineering, orange |
| Virtualization | Tested LTS boot CPU entered at EL1 (`maxcpus=1`); HYP unavailable |
| Boot image | Header v2 via `fastboot boot` works; stock is v3 + vendor_boot v3 |
| DTB selection | ABL picks our DTB as "Best Soc Dtb 0x164/0x20001/0x0/0x0" |
| dtbo | ABL always applies stock `dtbo_a` entry 0 (board-id 0xa000) on top |
| UEFI watchdog | UEFI enables the HW watchdog; qcom-wdt keeps it serviced |
| Reset type | PS_HOLD reset; DDR retained across Linux-initiated resets (ramoops works) |

## Motorola ABL/MBM requirements (learned from ABL logs and binary)

All three were fatal and silent from the host (`fastboot boot` still says OKAY):

1. **Base DTB model must contain "Qualcomm Technologies, Inc."** Otherwise:
   `No match found for Soc Dtb type` / `Appended Soc Device Tree blob not found`,
   then ResetSystem back to fastboot. `qcom,board-id` must be `<0 0>` (the live
   `0xa000` is the dtbo's value). Both earlier attempts failed here.
2. **The stock dtbo overlay is applied to our DTB.** Its 110 `__fixups__` labels
   cannot resolve against a mainline DTB. `gen_abl_overlay_sink.py` generates a
   disabled sink node per label plus `__symbols__`; `build_nio_dtb.py --dtbo`
   proves with `fdtoverlay` that only sink/root/symbol nodes change.
   Side effect: `of_platform` still instantiates the overlay's ramoops node
   inside the sink (`probe ... failed with error -22`), which is harmless.
3. **The v2 header cmdline must be empty.** MBM budgets its cmdline buffer
   from the v3 header's cmdline offset (0x2c, `os_version` in a v2 header) and
   then appends the real v2 cmdline: `DXE_ASSERT ... SafeString.c (786)`
   `(CopyLen > SourceLen)` in AsciiStrCatS. Kernel parameters go in
   `/chosen/bootargs`, which ABL prepends to its own androidboot arguments.

Other notes: ABL loads the Image misaligned (`[Firmware Bug]: Kernel image
misaligned at boot`, harmless for RELOCATABLE kernels). The PMIC PON spare
"FASTBOOT_MODE" flag persists until ABL boots a kernel; a normal Linux reboot
then goes to Android, `nio-diag reboot bootloader` goes to fastboot, and a panic
(no reboot-mode notifier) goes to Android.

## Getting logs out

| Situation | Where the log is |
| --- | --- |
| Kernel reached init | USB ACM shell: `tools/nio_console.py run 'dmesg'` / `collect DIR` |
| ABL rejected image / asserted | `logfs` partition, `LogNN.txt` of the attempt's boot cycle (ABL messages up to ExitBootServices) |
| Reset reason, XBL/TZ log | `fastboot oem logdump` in the next fastboot session |
| Kernel crashed or reset after init | ramoops console: `/sys/fs/pstore/console-ramoops-0` on the next diagnostic boot, or in rooted Android (same layout) |
| Hang before USB | On-screen fbcon (TER16x32 on the splash buffer): the phone's screen |

`python3 tools/fastboot_diag_boot.py --serial SERIAL` runs the whole sequence
and chooses the sources that apply. Verified: panic via sysrq-c was recovered
from Android pstore (call trace + "Rebooting in 10 seconds").

## Local evidence

- `reports/nio-boot-attempt-2/` … `-6/`, `reports/nio-diag-boot-*`: fastboot
  output, USB timelines, `logfs` UEFI logs, collected Linux logs, pstore.
- `reports/nio-kernel-20260927T103955324089Z/`: live DT/config capture.
- `reports/nio-sec-flag-20261006/`: repeated fixed read-only flag capture and
  diagnostic kernel/EL1 context; no firmware or IMEM write.
- `backups/nio-current-20260927T103955324089Z/`: slot-A boot, vendor_boot, dtbo,
  vbmeta, vbmeta_system with hashes. Restore still untested (M02 open).

## Next implementation order

1. Follow [KVM-PLAN.md](KVM-PLAN.md): CPU0 EL2 handoff and actual guest
   execution take priority. The bounded ownership model now passes all eleven
   captured SMEM-region assignments, and QHEE builds the earlier missing
   SMEM mappings. Both TZ-subsystem channels (VMIDs 21/22 and 21/42) now pass their exact
   ownership models. Command-database/log ownership and both diagnostic log
   mappings now pass. Three captured PMIC metadata tables also replay;
   all 878 offline checks pass across 43 suites. Exact bridge and allocator PRNG models now
   complete the original cold path, execute ERET and run a RAM probe at EL1,
   under explicit response/environment assumptions. The full-path SPSR-only
   experiment selects EL2h but faults on EL2 stage-1 execute permission with
   MMU/caches retained. A bounded terminal replacement now cleans the diagnostic
   ranges, clears M/C/I and runs the probe at EL2 with no page-table edits.
   The full modeled QHEE path now executes the original SEC prefix at XBL's
   configured `0x9fc00000` candidate, retaining EL2 through vector/BSS/temporary
   stack setup under both HCR/GCC inputs. SEC rewrites HCR_EL2 to `0x10`;
   sentinel RAM and surrounding guards verify its original stores. SP reaches
   `0x9ffd0000`, and the stack-sizing dispatcher now reaches its first SMC
   at `0x9fc284dc`, with SP=`0x9ffcffb0` and all eight arguments captured.
   Original ABL preparation/launch blocks preserve EL2 in isolated tests.
   The earlier indirect XBL slot configures a descriptor; a separate later
   `0x82000114` SMC uses buffer `0x80716100`, size `0xe00`. Original TZ
   selectors/frame instructions and a monitor argument-copy slice now prepare
   the candidate QHEE arguments from synthetic records. Prepared SPSR is
   `0x89`; original monitor restore/ERET now enters EL2 under those inputs,
   with software SCR `0x505`, SCTLR_EL2=0 and HCR preserved. Actual bootstrap
   and records remain unverified. These controls now pass full QHEE and SEC
   prefix tests with both HCR/GCC inputs. A terminal variant explicitly masks
   DAIF before maintenance within the same 124-byte block. A normal SMC step
   enters EL3 from the EL2 experiment; stock EL1 traps into QHEE, which
   forwards the query unchanged at `0x80041cbc`. The terminal only clears
   x0–x3; inherited x5/x6 differences are captured explicitly. Original TZ
   query slices now validate these captured arguments without dereferencing x6
   and derive status/availability zero. An exact one-shot synthetic EL3 reply
   advances both paths to the eight-byte `0x02000a01` request at `0x9fc28468`.
   Original buffer slices now reach typed/handler pointer-check boundaries and
   the selected PRNG backend. Finite FIFO fixtures derive eight output bytes
   and an original status/count reply, with ownership/setup/cache assumptions.
   An exact one-shot buffer fixture reply now lets original XBL return from
   stack sizing and adjust SP to `0x9ffcfd00`, stopping before `0x9fc0cf38`.
   Original stock forwarding uses `0x80041aa0` and sets x7=3; the model checks
   this distinct contract. Original cache-startup helper now executes its
   set/way loop, then SEC enables I/D at the existing EL with translation
   still off. The canary initializer reaches the second buffer SMC at
   `0x9fc28468`, SP=`0x9ffcfce0`. Its
   stock forwarding clears x6 and sets x7=3. Policy/context switching remain
   unverified. A separate one-shot second fixture reply now lets original
   XBL store its canary and enter SEC main with the workspace base/size.
   The earlier trace stopped at `0x9fc0e37c` before flag read `0x146bf944`,
   retaining EL2 in the diagnostic path. Two read-only phone checks now return flag
   `0x3a6506a5`; original SEC holds only for `0x55444247`. One exact replay
   under an explicit postboot-to-entry assumption now exits the hold loop,
   executes the no-op hook and platform prologue, and stops before
   `CNTVCT_EL0` at `0x9fc2bb48` in the earlier trace. Original counter read,
   fixed-frequency conversion, SIMD load and descriptor copy now execute;
   the next uint32 read at `0x01fc8004` faults in the model at both ELs.
   Two fixed read-only phone checks return zero. Exact selector replay now
   selects/stores the original descriptor, matches its table and reaches
   QUP wrapper-version read `0x00ac0004`, which faults at the current EL.
   Wrapper AHB clocks are disabled postboot; serial runtime status is
   `unsupported`. Next prepare a fixed version-read diagnostic with balanced
   clock references and capture its value. Entry/EL2 equality remains an
   assumption. QEMU counter frequency is 62.5MHz versus original
   firmware conversion at 19.2MHz; arithmetic results are not physical timing. The publisher and cold flag state remain open.
   Full UEFI/ABL execution and the Linux handoff remain open. See
   [EL2-XBL-selector.md](EL2-XBL-selector.md),
   [EL2-XBL-counter.md](EL2-XBL-counter.md) and
   [EL2-XBL-readiness.md](EL2-XBL-readiness.md). The phone
   was rechecked in diagnostic Linux on October 6, at EL1 without `/dev/kvm`;
   GPU SMMU runtime-PM policy is `auto`. No hyp/XBL partition was written.
2. cpufreq: `qcom-cpufreq-hw: Failed to find icc paths` (deferred); add the
   interconnect/OPP bits, then enable all CPUs (currently `maxcpus=1`).
3. UFS (read-only first), thermal, charging/fuel gauge, Type-C + USB3 QMP PHY.
4. Display pipeline (DSI panel nt36672c) to replace the splash framebuffer.
5. Persistent host (M05) only after storage and power management are stable.
