# motorola_nio: Motorola nio (XT2125-4, SM8250 / Snapdragon 870)

Everything mothershipOS needs that is specific to this phone. 8 cores (A55 ×4, A77 ×3, A77 prime), 8 GB,
Adreno 650, 1080×2520 90 Hz panel (NT36672C, DSI), QCA6390 Wi-Fi/BT, PM8150/PM8150B/PM8150L.

## Hardware state at EL2 (2026-10-12)

| Subsystem | State | Doc |
|---|---|---|
| Boot chain | ✅ u-boot in hyp_b → FIT on boot_b → Linux 6.18 EL2/KVM → persistent root `mship-root` | `docs/boot.md` |
| Display | ✅ msm KMS drives the panel; fbcon; sway | `docs/display.md` |
| GPU | ✅ Adreno 650, freedreno (no zap shader needed at EL2; secure mode open) | `docs/gpu.md` |
| Touch | ✅ NT36672C over SPI (patch 0006) | `docs/touch.md` |
| USB | ✅ USB3 SuperSpeed gadget (NCM/ACM dev link; verified in reverse orientation, normal untested) | `docs/usb.md` |
| Wi-Fi | ✅ QCA6390 / ath11k_pci | `docs/wifi.md` |
| Bluetooth | ✅ QCA6390 over UART | `docs/bluetooth.md` |
| CPU / RTC / shell | ✅ cpufreq (3 policies, profiles), RTC offset | `docs/system.md` |
| Charging | ✅ PM8150B charger + fuel gauge | `docs/charging.md` |
| Audio | ✅ ADSP at EL2, speaker via AW882xx at fixed -36 dB; ⚠ speaker protection (SKT feedback) open; mics/headset untested | `docs/audio.md` |
| Camera | ◐ OV64B RAW10 frames through CAMSS; no ISP/processing | `docs/camera.md` |
| Modem, CDSP, video, sensors, GNSS | ✗ untested (remote processors need the QHEE-replacement treatment like the ADSP) | — |

## Layout

| Dir | What |
|---|---|
| `kernel/` | `configs/nio-host.config` (fragment), `dts/` (upstream-style board DTS), `patches/` (the series on pristine 6.18.54), `drivers/aw882xx_nio.c`, `sources.lock.json`. `cargo xtask host-kernel` builds it (target/host-kernel); `cargo xtask abl-dtb` the ABL-path board DTB |
| `boot/` | FIT inputs: `nio-el2-display.dts` (the board DT for the FIT, on top of `nio-el2.dts`; older variants alongside), `nio-el2.its`, `initramfs.json` (early firmware, pinned), u-boot: `nio-hyp*.dts`, `nio-uboot-local.patch`, `UPSTREAM-COMMIT`, `u-boot-src/` (untracked). `cargo xtask initramfs` + `cargo xtask fit` build the FIT, `mship-dev deploy-fit` installs it. Images (`*.itb`, untracked): `nio-el2-known-good.itb` = recovery FIT |
| `firmware/` | firmware extracted from the stock partitions (untracked blobs; READMEs and SHA256SUMS tracked) |
| `unbrick/` | EDL recovery kit (`mship-dev edl`: Sahara + Firehose), proven 2026-10-06 |
| `tools/` | `uart/` (the live log of `mship-dev uart` and `mship-dev sh`) |
| `hardware/` | 3D model of a mounting plate |
| `docs/` | bring-up log per subsystem (moved from the old PORT-NOTES diary) |

Rules for working on the phone (approval for flashing, slot A fallback, things that reset the SoC):
`mothershipOS/docs/dev-workflow.md`.
