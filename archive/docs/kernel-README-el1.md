# nio LTS kernel bring-up

This is an initial upstream LTS development baseline for Motorola nio (the
connected XT2125-4). It is not yet a bootable phone distribution. No phone
partition has been written and no reboot has been requested by these tools.

## Inputs and build

Linux 6.18.54 is pinned in `sources.lock.json`. On 2026-09-27 it was the latest
release in kernel.org's latest LTS series. The downloaded archive matches the
upstream SHA-256 list over HTTPS; the detached signature has not been verified.
The source tree is kept under ignored `kernel-work/` so board definitions and
configuration can be reviewed without checking in the complete Linux tree.

On an Ubuntu host, the build needs Python 3.12+, GNU make, native GCC, the ARM64
GNU cross compiler/binutils, flex, bison, bc, OpenSSL development headers, and
libelf development headers. DTB checks also need GCC, `dtc` and `fdtget` from
`device-tree-compiler`.

This host already had the compiler dependencies. Missing flex and bison were
extracted locally with `apt download` and `dpkg-deb -x`; no system packages were
installed. Local binaries live under `kernel-work/host-tools/usr/bin`. The build
script supplies their PATH and BISON_PKGDATADIR automatically. Versions used:
flex 2.6.4-8.2build1, bison 2:3.8.2+dfsg-1ubuntu0.24.04.1, and GCC 13.3.0.

Run from the project root:

```sh
python3 tools/prepare_kernel.py
python3 tools/build_kernel.py configure
python3 tools/build_kernel.py build --jobs 4
python3 tools/build_nio_dtb.py
```

The source-preparation command verifies the tarball checksum on every invocation.
An existing extracted tree is left alone; its contents are not reverified. The
configure command regenerates the build configuration and the checked-in
`configs/nio-host.defconfig`. It starts from ARM64 defconfig, disables other SoC
families and merges `configs/nio-host.config`, then checks that every requested
option survived dependency resolution.

Outputs:

- `kernel-work/out/lts/arch/arm64/boot/Image`: ARM64 kernel, not an Android boot image.
- `kernel-work/out/lts/build-manifest.json`: kernel/config hashes and compiler identity.
- `kernel-work/out/nio-dtb/sm8250-motorola-nio.dtb`: initial board definition.
- `kernel-work/out/nio-dtb/manifest.json`: board checks and hashes.
- `kernel-work/out/nio-dtb/dtc.log`: compiler diagnostics, including inherited
  disabled-peripheral duplicate addresses and unused address-cell warnings.

Only the kernel Image is built. The configuration still contains modules; module
build/install and a matching initramfs are required before enabling consumers of
those modules. DT compilation and structural checks are not dt-schema validation
or hardware validation. The new board compatible also needs a binding entry
before proposing this board upstream.

## Evidence and safeguards

`evidence/nio-board.json` records non-identifying hardware facts from the live
DTB. The checker verifies all 25 fixed reservations, their non-overlap, no-map
flags, board selection IDs and the enabled UART address. It can also compare a
fresh captured DTB directly:

```sh
python3 tools/build_nio_dtb.py --reference-dtb reports/REPORT_DIRECTORY/live.dtb
```

The board inherits the SM8250 memory map and adds seven Motorola reservations.
It reserves the ramoops region without activating its driver until the vendor
record layout and cross-boot log recovery have been checked. Dynamic vendor DMA
pools are not copied; revisit their requirements when enabling each consumer.
RAM-bank sizes are expected from the bootloader, and that handoff is untested.

The running tree has a stale serial0 alias pointing to disabled UART2 at
0x988000. UART12 at 0xa90000 is enabled, matching the downstream nio overlay;
the development board selects UART12. Physical access to its pins is unverified.
PM8150/PM8150B/PM8150L definitions are included. Secure TLMM GPIO ranges 28–31
and 40–43 are excluded.

USB 2.0 peripheral mode, the splash buffer as simple-framebuffer and
reboot-mode are enabled and boot-tested. UFS, the display pipeline, GPU, USB3
and remote processors remain disabled. KVM, memory cgroups, pressure reporting,
vhost-net and vhost-vsock are enabled in the kernel configuration, and work when Linux
is entered at EL2 via u-boot (see ../ARCHITECTURE.md); the stock ABL path enters at EL1.

## Capturing another baseline

```sh
python3 tools/capture_kernel_baseline.py --serial DEVICE_SERIAL --backup-slot a
```

The capture tool checks for nio and existing root access, reads kernel config,
live DT and boot command line, and optionally copies the five boot-related
partitions in the selected slot. It validates formats and exact sizes before
renaming partial backups, and stores SHA-256 manifests. It does not install root,
reboot, unlock or write to the phone. These are partial boot backups, not backups
of user data, firmware/calibration partitions or the complete device. Restore
has not yet been tested. `reports/` and `backups/` are private local outputs and
excluded from version control.

See `STATUS.md` for the ABL/EL1 path reference and `../ARCHITECTURE.md` for current status.

## Diagnostic boot (RAM only)

```sh
python3 tools/build_diagnostic_ramdisk.py
python3 tools/gen_abl_overlay_sink.py backups/BACKUP_DIRECTORY/dtbo_a.img
python3 tools/build_nio_dtb.py --diagnostic --reference-dtb reports/REPORT_DIRECTORY/live.dtb \
    --dtbo backups/BACKUP_DIRECTORY/dtbo_a.img
python3 tools/package_diagnostic_boot.py
python3 tools/fastboot_diag_boot.py --serial DEVICE_SERIAL [--after stay|bootloader|android]
```

The ramdisk needs `kernel-work/downloads/busybox/busybox-static_1.36.1-6ubuntu3.1_arm64.deb`
(hash pinned in the tool; verified against the gpgv-checked noble-updates index).
The packager expects `kernel-work/tools/mkbootimg.py` (LineageOS
android_system_tools_mkbootimg 68697756a3ad6a2f123534b21ad55b9d4a97f0b5) and
checks its hashes. The header-v2 image carries our Image, ramdisk and DTB with
an empty header cmdline; kernel parameters live in the diagnostic DTB's
`/chosen/bootargs`. See STATUS.md for the three Motorola ABL requirements.

`fastboot_diag_boot.py` only uses `fastboot boot`. It waits for the USB ACM
gadget (1d6b:0104) and collects dmesg, previous-boot pstore and device state
into `reports/nio-diag-boot-*`. If the phone returns to fastboot or Android, it
saves `fastboot oem logdump`, the `logfs` UEFI logs and Android pstore instead.

Interactive shell: `picocom /dev/ttyACM1` (or whichever ttyACM belongs to
1d6b:0104), or `python3 tools/nio_console.py run 'CMD'`. The first command
from `nio_console.py` cancels the image's 180 s automatic return to fastboot.
`nio_console.py reboot bootloader` returns to fastboot; `reboot` goes to Android.
