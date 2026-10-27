# Boot chain: u-boot as the hypervisor, Linux at EL2, dev loop, persistent root

> Bring-up log moved from the old PORT-NOTES diary (2026-10-08..12); dated entries are as written then.
> Paths were updated to the current repo layout.

Goal (per Linaro docs): u-boot on the **hyp partition → runs at EL2 → boots Linux with KVM**.
Phase A first: validate u-boot on nio hardware via `fastboot boot` / boot partition (EL1).

## Build
- Source: upstream u-boot (shallow clone), `qcom_defconfig qcom-phone.config`.
- SM8250 is first-class: `clock-sm8250.c`, `pinctrl-sm8250.c`, many SM8250 phone DTs upstream.
- `u-boot.bin` carries the arm64 Image header + PIC + `LINUX_KERNEL_IMAGE_HEADER=y` → ABL accepts it as a "kernel".
- Build deps installed on host: flex bison swig python3-dev libgnutls28-dev libssl-dev.
- Artifacts: `motorola_nio/boot/u-boot.bin`, boot image `motorola_nio/boot/uboot-nio-boot-v2.img`.

## Packaging (nio boot-v2, from kernel-work/tools/mkbootimg.py)
```
mkbootimg.py --header_version 2 --pagesize 4096 --base 0 --kernel_offset 0x8000 \
  --ramdisk_offset 0x1000000 --tags_offset 0x100 --dtb_offset 0x1f00000 --cmdline "" \
  --kernel u-boot.bin --ramdisk empty-ramdisk.gz \
  --dtb kernel-work/out/nio-dtb-diagnostic/sm8250-motorola-nio-diagnostic.dtb --output ...
```
(empty cmdline: a non-empty v2-header cmdline trips nio ABL's SafeString assert.)

## Findings (2026-10-08)
1. **ABL accepts the image and hands off to u-boot** — `fastboot boot` and flashing to `boot_b`
   both reach `Exit EBS / UEFI End`, then jump to u-boot. Packaging/load is correct.
2. **u-boot RUNS and reaches `board_fdt_blob_setup`** — proven by the `reset_cpu()` bisect:
   placing `reset_cpu()` at the start of `board_fdt_blob_setup` produces a CLEAN reset
   (`motorola_wdog_dump wdog_status: 0`, a commanded reset) instead of the previous silent hang.
   Earlier builds (no reset_cpu) went dark → so the crash is **at/after `qcom_parse_memory`**,
   i.e. the Qualcomm RAM-node parsing (phones.rst: "ABL known to give bogus memory entries").
3. **Early uart12 console does not emit post-EBS** — `CONFIG_DEBUG_UART_MSM_GENI`
   (base 0xa90000, clk 7372800), with/without SKIP_INIT, and an explicit `debug_uart_init()`
   call in `board_fdt_blob_setup`, all produced no output. ABL likely tears down uart12 at
   ExitBootServices, so bisect with `reset_cpu()` (observable via the XBL/ABL re-log on reset)
   rather than relying on u-boot's console for now.

## Local source patches (in the clone, not yet upstreamable)
- `arch/arm/mach-snapdragon/board.c`: `#include <debug_uart.h>`, `#include <cpu_func.h>`;
  at top of `board_fdt_blob_setup()`: `debug_uart_init(); printascii("[UBOOT]...")` + a
  `reset_cpu()` bisect marker (REMOVE before a real boot).
- `.config` extras: `DEBUG_UART=y DEBUG_UART_MSM_GENI=y DEBUG_UART_BASE=0xa90000
  DEBUG_UART_CLOCK=7372800 DEBUG_UART_ANNOUNCE=y`.

## Next
- Move `reset_cpu()` to AFTER `qcom_parse_memory(...)` to confirm the memory parse is the crash;
  if so, fix the memory node (pass a DT with a sane /memory, or patch qcom_parse_memory handling
  of the nio ABL memory layout — DRAM is cs0 0x80000000+4GB, cs1 0x180000000+4GB).
- Then remove bisect markers, get u-boot to its prompt, bring up UFS, and move to Phase B:
  package u-boot for the **hyp partition** (EL2) and boot Linux with KVM.

## Flash/recover
Flashed to `boot_b` (slot B) + stock `hyp_b`; slot A untouched stock. u-boot reset_cpu build
boot-loops. Recover: `fastboot set_active a` (stock Android) or restore `boot_b` from
`nio-firmware-20260927T163534Z/boot_b.img` (NAS backups, see `mothershipOS/docs/dev-workflow.md`).

## MILESTONE (2026-10-08): u-boot boots on nio
After making board_fdt_blob_setup prefer the EXTERNAL (ABL-passed) nio DTB as the control FDT
(the built-in default was `qcom/sdm845-db845c` — wrong SoC), u-boot runs on the phone:
```
U-Boot 2026.10-gbc15e2be5bd5-dirty
Model: nio
DRAM:  8 GiB (total 7.9 GiB)
```
`Model: nio` + correct 8 GiB DRAM = it's using the real nio DT (SM8250 clk/pinctrl/uart) and
ABL-filled memory. Banner prints on uart12 (the pre-banner garbage was my early debug_uart at the
wrong baud; removed — the DT console is clean).

Then it hangs right after `DRAM:` (no `Core:`/`MMC:`/prompt), i.e. in early board_init_r/driver
bind. Next: per phones.rst, disable suspect drivers (pinctrl, mmc, scsi/ufs, usb/phy, clk refs in
fb node) to isolate, reach the `=>` prompt. Then Phase B: package u-boot for the HYP partition
(EL2) -> boot Linux -> KVM.

Required board.c change (keep): prefer external DTB for both memory parse and control FDT.

## PHASE A COMPLETE (2026-10-08): u-boot fully interactive on nio
u-boot runs end-to-end to its autoboot/boot-menu:
```
Model: nio ; DRAM: 8 GiB ; Core: 188 devices, 26 uclasses, devicetree: board
MMC: (none) ; In: serial,button-kbd ; Out: serial,vidconsole
QCOM-FMP: Failed to find boot partition ; Net: No ethernet
Hit any key to stop autoboot: 0
```
Notes: no "hang after DRAM" — it reached the menu. Autoboot fails only because UFS isn't up
(MMC empty). Input = serial (uart12 RX) + volume-button kbd.

## Path to the goal (KVM) from here
To boot Linux at EL2 without depending on UFS: build u-boot with an EMBEDDED FIT (our 6.18
kernel + nio DTB + small initramfs) so u-boot boots Linux from RAM. Then package THAT u-boot for
the HYP partition (EL2). XBL -> u-boot@EL2 -> boots embedded Linux@EL2 -> KVM/VHE. Avoids the UFS
bring-up entirely for the first KVM bring-up.
Alternative: bring up the SM8250 UFS driver in u-boot and load the kernel from the boot partition.

## PHASE B step 1 (2026-10-08): u-boot packaged + flashed AS the hypervisor (EL2)
Built `u-boot.mbn` as a QHEE-format hyp image and wrote it to hyp_b via EDL:
- mkmbn entry added: `b"qcom,sm8250\0": MbnData(0x80040000, 6, SwId.hyp)` (hyp load addr 0x80040000,
  MBN v6, sw_id 0x15 = hyp) — matches stock QHEE's ELF (entry/load 0x80040000, v6 hash seg).
- Control DTB = nio with REAL /memory (3 ranges: 0x80000000+0x3b800000, 0xC0000000+0xC0000000,
  0x180000000+0x100000000) built in via `EXT_DTB=nio-hyp.dtb`. Needed because at EL2/hyp TZ passes
  NO DTB (unlike ABL), so u-boot must use its built-in DTB + can't rely on ABL filling memory.
- Artifact: `motorola_nio/boot/u-boot-hyp.mbn` (ELF entry 0x80040000, LOAD@0x80040000, v6 MBN+hash).
- fastboot flash hyp_b = "Preflash validation failed" (ABL rejects non-stock hyp) -> flashed via
  EDL instead: `mship-dev edl --loader prog_firehose_ddr_SM8250.elf --program 5 1184 385 <padded img>`.
  hyp_b = LUN5 / LBA1184 / 2048 sectors (8MiB), 4096B sectors. Digest verified on-device.

### Boot test: what to look for (slot B)
- SUCCESS = u-boot banner (`U-Boot 2026.10 / Model: nio / DRAM: 8 GiB`) appears with NO ABL/UEFI
  log before it (no `UEFI Start` / `Exit EBS`). That means XBL->TZ->u-boot@EL2 directly (u-boot IS
  the hyp now; QHEE+ABL are bypassed). u-boot-as-hyp is EL2 by definition (TZ hands hyp EL2).
- FAIL = pre-ABL brick / `blank mode` / watchdog (XBL/TZ rejected the hyp image), or partial u-boot
  then hang (EL2 handoff/init differences). Both EDL-recoverable.
### Recover
Phone to EDL -> `mship-dev edl --loader <firehose> --restore-hyp-b <stock hyp_b.img> --commit`
(writes stock hyp_b.img back to LUN5/1184/2048). Slot A untouched stock throughout.

## *** PHASE B step 1 ACHIEVED (2026-10-08): u-boot runs AS the hypervisor at EL2 ***
Boot log (slot B, hyp_b = our u-boot.mbn):
```
QHEE Image Loaded, Delta - (1568772 Bytes)   <- XBL loaded OUR u-boot as the hyp (stock QHEE ~450KB)
APPSBL Image Loaded ...                        <- ABL loaded but NEVER entered
SBL1, End ; DDR Frequency 1555 MHz
U-Boot 2026.10 ... Model: ...SM8250 Motorola nio ; DRAM: 8 GiB
Core: 188 devices ... devicetree: separate ; libfdt ... FDT_ERR_BADMAGIC
```
PROOF it's EL2: (1) XBL loaded our 1.5MB image AS the hyp (accepted MBN/sw_id). (2) TZ hands the
hyp EL2; nothing demoted it (QHEE, the thing that demoted HLOS->EL1, is gone). (3) NO ABL/UEFI ran
(no `UEFI Start`/`Exit EBS` before the banner; contrast the EL1 boot). (4) `devicetree: separate` +
BADMAGIC on prev-stage FDT = TZ passes no DTB at EL2 -> u-boot used its built-in nio DTB (real
/memory -> correct 8GiB with no ABL). We now OWN EL2 with an interactive bootloader. QHEE displaced.

### Next (to KVM): embed a FIT (6.18 kernel + nio DTB + initramfs) in u-boot so it boots Linux from
RAM at EL2 (UFS not up). Confirm kernel enters at CurrentEL=2 (head.S init_el2), then CONFIG_KVM+VHE
-> /dev/kvm. Optional rigor: add a CurrentEL print to u-boot board init to show "2" on the banner.

## PHASE B step 2 (2026-10-08): boot Linux at EL2 via u-boot+UFS+FIT  [TEST PENDING]
Flashed (EDL, both LUN5, digest-verified):
- hyp_b (LBA1184/385sec) = u-boot.mbn: UFS nodes ENABLED in built-in DTB (ufshc@1d84000 +
  phy@1d87000 were status=disabled -> okay), bootcmd rewritten in board/qualcomm/qcom-phone.env:
  `ufs init; scsi scan; for d in 0..7: if part start scsi $d boot_b -> scsi read 0x90000000; bootm`.
  bootargs: console=ttyMSM0,115200 earlycon=qcom_geni,0x00a90000 root=/dev/ram0 rdinit=/init.
  ARMV8_SWITCH_TO_EL1=n => kernel enters at EL2. QCOM_HYP_SMMU=y (DMA at EL2).
- boot_b (LBA137440/9944sec) = nio-el2.itb FIT: 6.18 Image@0x81000000 + nio-ufs DTB@0x87000000 +
  busybox initramfs@0x88000000. Kernel has CONFIG_KVM=y.
Watch UART: QHEE(=u-boot) load -> u-boot banner (EL2) -> `==EL2-UBOOT: booting Linux FIT==` ->
UFS/scsi init -> `FOUND boot_b on scsi N` -> `bootm` -> Linux boot log at EL2 -> busybox shell;
look for `kvm [N]: ... mode initialized` = KVM up at EL2.
Risks: UFS may not probe/DMA at EL2 (SMMU) -> "NO-BOOT-FIT"/scsi empty; kernel may fault if EL2
handoff state wrong. Recover: EDL + fh.py restore-hypb (+ reflash boot_b stock if needed).

## *** PHASE B step 2 ACHIEVED (2026-10-08): Linux 6.18 boots at EL2 with KVM (VHE) ***
First attempt hung at `Loading Kernel Image to 81000000` then watchdog -> `blank mode` -> EDL.
CAUSE: FIT load addrs were inside no-map firmware carveouts of the nio DT:
kernel 0x81000000 (image_size 0x2710000) in `memory@80b00000` (0x80b00000-0x85e00000, TZ/QTEE,
XPU-protected -> the copy stalls the bus); ramdisk 0x88000000 in `memory@87800000`.
FIX (FIT only, hyp_b u-boot unchanged): kernel load/entry 0xa0000000, fdt 0xa4000000, ramdisk
0xa4200000 (free DRAM 0x9e400000-0xaef9b800). Source: `nio-el2.its` (here); image `nio-el2.itb`
flashed to boot_b via EDL (digest MATCH). Rule: never place load addrs in reserved-memory no-map
ranges — check the DT before choosing addresses.
Result on UART: `Loading Kernel Image to a0000000` -> `Starting kernel` -> `CPU: All CPU(s) started
at EL2` -> `kvm [1]: VHE mode initialized successfully` -> /dev/kvm (10,232) -> nio-diag
KVM_API_VERSION=12, KVM_CREATE_VM_OK -> busybox root shell on serial.
Still open: guest execution untested; cpufreq deferred (icc paths); GICV missing (no GICv2 emu).

## Source tree saved (2026-10-08)
u-boot source + build dir now live in `motorola_nio/boot/u-boot-src/` (git clone of upstream at
`UPSTREAM-COMMIT`, build output in `.out/`). Local changes (board.c external-DTB preference,
qcom-phone.env EL2 bootcmd, mkmbn sm8250 hyp entry) are also exported as `nio-uboot-local.patch`.
Built-in control DTBs: `nio-hyp.dts/.dtb` and `nio-hyp-ufs.dts/.dtb` (UFS enabled; the one in hyp_b).

## Dev loop + A1 + GPU at EL2 (2026-10-08, afternoon)
- **Dev link**: host init (`host-initrd/init`, revision 4) brings up a USB composite gadget at boot:
  NCM network (phone 10.42.0.2, host 10.42.0.1 via NM profile `mothership-usb`, fixed MACs) + ACM +
  `telnetd -p 2323`. `tools/nsh.py 'cmd'` runs a shell command remotely (~34 MB/s wget).
  `motorola_nio/boot/build_fit.sh` builds the FIT; `motorola_nio/boot/deploy_fit.sh` writes it to boot_b
  FROM LINUX (UFS works at EL2), verifies sha256, reboots. No EDL needed for kernel/initramfs/DT
  iteration. Known-good fallback FIT: `nio-el2-known-good.itb` (needs EDL if a new FIT won't boot).
- **A1 (M03) DONE**: kvmtool (`vmm/src/kvmtool`, static, in initramfs as /bin/lkvm) boots a minimal
  6.18 guest (`mothershipOS/guest/kernel/guest-virt.config` -> `kernel-work/out/guest-virt`) with 4 vCPUs,
  timer OK, clean PSCI poweroff; two 4-vCPU VMs concurrently OK.
- Linux at EL2 owns apps SMMU (stage-2 capable) and dwc3 (USB gadget works through it); UFS works.
- **GPU**: DRM_MSM enabled, GPU+GMU nodes enabled in `nio-el2-gpu*.dts`, patch 0002 makes
  `msm.separate_gpu_kms` default (GPU = own DRM device, renderD128). Firmware: linux-firmware
  a650_sqe.fw/a650_gmu.bin (nio's own SQE v93 is too old for upstream, needs >=95).
  Zap shader at EL2 needed patch 0003: QHEE used to create the TZ SHM bridges for PIL; now Linux
  allocates PAS metadata from the SHM-bridge tzmem pool and bridges the image region
  (`qcom_scm_pas_el2_bridge`). With that, TZ init+auth of the zap SUCCEED (both nio's and RB5's
  zap), but CP then faults on CP_SET_SECURE_MODE (opcode error 0x70E60001).
  WORKING CONFIG: no zap-shader node (`nio-el2-gpu-nozap.dts`) -> driver writes
  RBBM_SECVID_TRUST_CNTL=0 -> `gpu-initialized: 1`, rbbm-status 0, ring rptr==wptr. GPU up at EL2.
  Secure-mode/zap (needed only for content protection) is an open item.
- Vendor partitions are readable from Linux: `motorola_nio/archive/prototypes/backup/lpdump.py` parses super LP metadata
  (vendor_a = sde25 sector 9063504); mount via `losetup -r -o` + `mount -o ro,noload`.
  Modem firmware (ADSP/CDSP/venus/zap) is in `nio-firmware-20260927T163534Z/modem_a.img` on the NAS (ext2; `debugfs -R dump`).
- **GPU RENDERS (2026-10-08)**: Ubuntu 26.04 arm64 in phone RAM (`motorola_nio/archive/el1-tools/ubuntu_ram_rootfs.sh`,
  apt via host `tools/proxy.py`), Mesa 26.0.8 freedreno: `GL_RENDERER FD650, GLES 3.2`;
  `glmark2-es2-drm --off-screen` 1080x2520: build 816 fps, texture 714, phong 610, refract 89,
  terrain 109, score 466 (cpufreq still deferred = cores at boot clocks). Vulkan (turnip) not yet
  verified: vulkaninfo aborts in vkGetPhysicalDeviceDisplayPlanePropertiesKHR (no KMS on GPU device).
  nsh.py mirrors all remote commands/output into motorola_nio/tools/uart/live.log so the monitor GUI shows them.

## *** A2 ACHIEVED (2026-10-08): persistent Ubuntu 26.04 host root on UFS ***
GPT on sde edited (super 12G -> `mship-root` 8G, userdata grown to 101G; see
`USERDATA-BACKUP-HANDOFF.md`). Both ext4: LABEL=mship-root (sde25, /), LABEL=mship-data (sde27,
/var/lib/mothership). Root = ubuntu-base 26.04 + systemd/udev/dbus/openssh/iproute2 (~470 MB), installed
from the RAM host by a provisioning script (chroot + apt via `proxy.py`).
Boot: u-boot(hyp) -> FIT (same kernel/DTB) -> initramfs init revision 5 brings up the USB gadget, then
`try_root`: finds PARTNAME=mship-root, bumps `/var/lib/mship-boot/attempts`, remounts ro, moves
/dev /proc /sys, `switch_root` -> systemd. `mship-boot-ok.service` resets the counter; after 3 unfinished
attempts init stays in the RAM host (`ROOT_FALLBACK`), as does `mship.ram` on the cmdline.
In the new root: systemd-networkd (usb0 10.42.0.2/24), **ssh root@10.42.0.2 (key auth)**,
`mship-telnet.service` (busybox telnetd on 10.42.0.2:2323, keeps nsh.py/deploy_fit.sh working),
autologin root on ttyMSM0 (UART) and ttyGS0 (USB ACM), GPU firmware in /usr/lib/firmware, lkvm/nio-diag
in /usr/local/bin. Verified: two consecutive reboots to `running` with no failed units, ~50 s to ssh,
data persists, journal persists. Previous FIT kept as `nio-el2-pre-a2.itb`.
Open: no RTC/NTP -> clock starts at systemd's epoch (set it from the PC over ssh before apt);
no kernel modules installed (all needed drivers are built in).
