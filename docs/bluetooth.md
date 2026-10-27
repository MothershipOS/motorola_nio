# Bluetooth (QCA6390 over UART)

> Bring-up log moved from the old PORT-NOTES diary (2026-10-08..12); dated entries are as written then.
> Paths were updated to the current repo layout.

## Bluetooth (2026-10-12)
- QCA6390 BT core on QUP0 SE6 UART (serial@998000 = ttyHS1, gpio16-19), stock qcom,qup_uart@998000 + bt_qca6390.
  DT (nio-el2-display.dts, FIT nio-el2-bt.itb): geniqup@9c0000 okay + firmware-name qupv3fw.elf (has the UART
  proto segment), per-pin config (cts bus-hold, rts/tx no bias, rx pull-up), alias serial1, bluetooth child
  qcom,qca6390-bt on the qca6390-pmu LDOs (bt-en tlmm 21), local-bd-address = the phone's own address
  (stock androidboot.btmacaddr; without it hci0 stays "unconfigured: missing public-address"). It identifies the
  phone, so it is not in git: put it in `boot/bd-address` (`00:11:22:33:44:55`) and `cargo xtask fit` writes it in.
- hci_qca: ROME/QCA6390, SoC 0x400a0200, ROM 0x200; firmware = stock bluetooth_a /image/htbtfw20.tlv + htnv20.bin
  (motorola_nio/firmware/nio-bt; linux-firmware pair kept as *.linux-firmware). BT 5.2, BR/EDR + LE, scan finds devices.
- Modules added (no Image change): UHID (BLE HID / HOGP), BT_RFCOMM(+TTY), BT_BNEP; uhid in modules-load.d.
- Userspace: bluez 5.85 (bluetooth.service), mship-admin bt-*, shell Settings > Bluetooth (power, visible,
  paired devices connect/disconnect/forget, scan, pair with just-works agent NoInputNoOutput).
- Not done: physical Bluetooth audio validation (PipeWire/SPA are installed), passkey entry UI, BT wake from suspend, Wi-Fi MAC (still
  the 00:03:7f default; stock takes it from persist, not the cmdline).
