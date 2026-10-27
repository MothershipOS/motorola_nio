QCA6390 (ath11k) firmware for the nio host, installed to /lib/firmware.
- ath11k/QCA6390/hw2.0/{amss.bin,m3.bin}: linux-firmware (WLAN.HST.1.0.1, 2021-11-04)
- ath11k/QCA6390/hw2.0/board.bin: nio board data = stock modem partition /image/bdwlan.elf.nio.epa
  (chip reports board_id 0xff). linux-firmware's board-2.bin (Qualcomm reference boards) is kept aside as
  board-2.bin.linux-firmware so ath11k falls back to the nio calibration.
- qca/{htbtfw20.tlv,htnv20.bin}: linux-firmware QCA6390 Bluetooth (BT not wired up yet).
Stock Android WLAN/BT firmware (amss20.bin, bdwlan.*, regdb.bin, ...) is in ../nio-wlan.
