# Touchscreen (NT36672C over SPI)

> Bring-up log moved from the old PORT-NOTES diary (2026-10-08..12); dated entries are as written then.
> Paths were updated to the current repo layout.

### A4: touchscreen (2026-10-11)
Novatek NT36672C TDDI touch, 0-flash: firmware must be written to its SRAM over SPI after every panel power-on.
- Stock: `novatek,NVT-ts-spi` on spi@a94000 (QUP1 SE5 = spi13), pins gpio36-39 func qup13 drive 6, 9.6 MHz,
  IRQ gpio24 rising, reset gpio50 never driven (TDDI shares the panel RESX). fw from vendor_a
  `/firmware/novatek_ts_fw.bin` (extracted from the super backup; motorola_nio/firmware/nio-touch/, also MP bin/csv and the
  stock nova_0flash_mmi.ko for reference). Source: MotorolaMobilityLLC/motorola-kernel-modules
  branch android-11-release-rrn, drivers/input/touchscreen/nova_0flash_mmi (GPL) -> kernel-work/reference/.
- QUP SE13 comes up with proto INVALID in our chain (XBL does not load its SE fw). 6.18 geni loads it itself:
  geniqup@ac0000 `firmware-name = "qcom/sm8250/nio/qupv3fw.elf"` = raw dump of the qupfw partition (identical
  on a/b; has SPI segment proto 1 v0xb01). Stored in motorola_nio/firmware/nio-qup/, in the initramfs and on mship-root.
- Kernel patch 0006: `drivers/input/touchscreen/novatek-nt36xxx-spi.c` (TOUCHSCREEN_NOVATEK_NT36XXX_SPI).
  drm_panel follower (`panel = <&nio_panel>`): on panel_prepared -> work: eng reset, chip trim check (0x3f004
  -> 0c xx xx 72 66 03 = NT36672C, NT36675 memory map), bootloader reset, write ILM/DLM/info/overlay partitions
  (63 KiB SPI chunks), program BLD hw-CRC banks, enable CRC, BOOT_RDY, wait reset state 0xA0 then 0xA1, read fw
  info. IRQ: 65-byte point packet (10x6 + force + checksum), MT type B. panel_unpreparing disables the IRQ.
  Firmware name from DT: `novatek/nt36672c-tianma-nio.bin` (initramfs + mship-root).
- Result: chip identified, fw ver 10, 16x36 sensors, 1080x2520, download ~100 ms at 4.6 s boot. evtest: 5-finger
  MT, x 26-1028 / y 78-2095 in a quick test, pressure 1-1000. Re-download verified after
  `swaymsg output DSI-1 power off/on`. sway sees it as type:touch (`map_to_output DSI-1` in sway-config).
- Lesson: an oops inside a system-workqueue item (first build: NULL chip ptr) wedged that CPU's worker pool,
  which stalled UFS runtime PM and therefore all block I/O (mount and dd stuck in D). Offlining that CPU
  (`echo 0 > /sys/devices/system/cpu/cpuN/online`) unbinds the pool and unsticks it — that's how boot_b was
  re-flashed without EDL.
- FIT: nio-el2-touch.itb (= nio-el2.itb). DT: nio-el2-display.dts now holds display + touch.
