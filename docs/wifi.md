# Wi-Fi (QCA6390, ath11k)

> Bring-up log moved from the old PORT-NOTES diary (2026-10-08..12); dated entries are as written then.
> Paths were updated to the current repo layout.

## Wi-Fi (2026-10-12)
- QCA6390 on PCIe0, ath11k_pci, WORKS at EL2 first try (FIT nio-el2-wifi.itb): enumerates 17cb:1101,
  MHI -> mission mode, fw 0x10121492, interface wlp1s0, scans 2.4 + 5 GHz.
- DT (nio-el2-display.dts): rb5-style qcom,qca6390-pmu power sequencer with the stock cnss supplies
  (s6a aon/pmu/rfa0p95, s4a io (fixed), s5a 1.9 V, s8c 1.35 V; antenna switch l5c 1.8 V always-on),
  wlan-en tlmm 20, bt-en tlmm 21; pcie0 + phy@1c06000 (l5a/l9a) okay; wifi@0 under pcie@0.
- Kernel modules now installed on the rootfs (/lib/modules/6.18.54-mothership-nio-dev, 788 modules,
  from out/lts-modroot). New autoload candidates audited; LPASS/crypto/bwmon ones blacklisted
  (motorola_nio/rootfs/modules/mothership-blacklist.conf). rtc_pm8xxx now loads.
- Firmware: motorola_nio/firmware/nio-wlan-linux (README). Userspace: NetworkManager (usb0 unmanaged), wpasupplicant.
- Not yet: Bluetooth (QCA6390 BT over a GENI UART), regulatory country, power save tuning.
