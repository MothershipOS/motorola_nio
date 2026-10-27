# EL1 / ABL boot path — reference

Facts about the stock Motorola boot path (ABL → Linux at EL1 via `fastboot boot`), still relevant
whenever slot A / ABL is used. The current mothershipOS boot chain (u-boot as hyp → Linux at EL2,
KVM) is described in `../ARCHITECTURE.md` and `../el2-debug/uboot/PORT-NOTES.md`.
The pre-2026-10-08 status/plan history is archived in `backups/stale-docs-20261008.tar.gz`.

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

