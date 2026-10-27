# USB / Type-C

### USB-C dual role + DisplayPort alt mode (2026-10-18) — stack up, waiting for a dock/monitor test
- DT (nio-el2-display.dts, "USB-C" section, FIT nio-el2-dp.itb = the running kernel + initramfs of
  nio-el2-audio-skt.itb with the new DTB): the PM8150B Type-C/PD block (typec@1500, both register blocks) runs under
  TCPM (`qcom_pmic_tcpm`), replacing patch 0007's orientation-only node (the 0007 driver is still built, unused).
  usb-c-connector: power-role dual, try-power-role sink, data-role dual, source PDO 5 V/0.9 A, sink PDO 5 V/3 A
  (numeric PDOs: the DTS goes through dtc without cpp), DP alt mode SVID 0xff01 VDO 0x1c46 (as qrb5165-rb5).
  Graph as rb5: connector HS - dwc3 port@0; connector SS - NB7VPQ904M (i2c15 @0x1a, retimer + orientation switch)
  port@0, retimer port@1 - QMP combo PHY port@0; connector SBU - retimer port@2; DP controller (ae90000, 2 lanes) -
  PHY port@2. dwc3 dr_mode otg + usb-role-switch, role-switch-default-mode peripheral. VBUS regulator 0.5-1.5 A.
- NB7VPQ904M: the driver needs a vcc supply (`devm_regulator_get_optional` → -ENODEV, probe fails silently, then
  TCPM and DP stay deferred). The rail isn't modelled; the chip is powered from boot, so a software-only fixed
  1.8 V regulator (nb7_vcc) satisfies it.
- Result with the PC cable: no deferred devices, `/sys/class/typec/port0` (partner = PC; sink, device, orientation
  normal), `/sys/class/usb_role/a600000.usb-role-switch`, DRM connector card1-DP-1 (disconnected), charging as
  before (PM8150B charger online, 1.5 A), dev link unchanged.
- The UDC disappears while the port is a host: `motorola_nio/rootfs/usb/` udev rule rebinds the dev link gadget "m"
  when it comes back.
- Monitor test (2026-10-18, a USB-C monitor with a USB hub): DP alt mode entered by itself (SVID ff01 active, the
  phone took the host data role, no DR_SWAP needed), DP-1 connected with 3840x2160/2560x1440/1920x1080, the
  monitor's hub enumerated on the host. Leasing DP-1 while the panel was leased failed in the kernel
  (`object 44 failed -16`): wlroots gave DP-1 the panel lessee's CRTC 92 / plane 44 (fixed by
  host/sway/wlroots-patches/0001).
- 4-lane DP (pin C/E, 4K60): `mode-switch` on the PHY, DP data-lanes <0 1 2 3>. The PHY then powers its USB3 half off
  and the dwc3 lost its PIPE clock: even the monitor's USB 2.0 hub stopped enumerating (connect-debounce failed,
  device mode "failed to enable ep0out"). Patch 0017: the QMP combo PHY notifies the legacy dwc3-qcom glue, which
  switches to the UTMI clock and restarts its role (and back when USB3 returns). Verified: 3840x2160@60 with the
  monitor's hub and a Dell receiver enumerating automatically.
- Monitor attached while the phone boots: PD fails (TCPM's two hard resets go unanswered), no alt mode; a
  physical replug fixes it. Cause: the qcom TCPM driver's set_cc(TYPEC_CC_OPEN) doesn't open CC, so tcpm_init's
  PORT_RESET is no real disconnect. Tried making it TYPEC_DISABLE_CMD (2026-10-18): that does disconnect, but this
  monitor then never re-presents Rp (MISC_STATUS stays unattached in DRP and sink-only mode) until physically
  replugged, so it was reverted. Still open.
- DP audio (2026-10-19): the sound card's `dp-link` (Q6 AFE `DISPLAY_PORT_RX` -> the DP controller as codec, as
  qcm6490-fairphone-fp5) plays on the monitor, front end MultiMedia2 (`hw:0,1`, route
  `DISPLAY_PORT_RX Audio Mixer MultiMedia2`). Needs patch 0019: in 6.18 the DP driver turns its audio engine on in
  the codec prepare, after Q6 has tried to start the port (`AFE enable for port 0x6020 failed -110`, then DSP
  error 9 until the card is reloaded). Only plays while the DP link is up (the monitor is leased and lit). The
  Ubuntu VM gets it as virtio-snd (`vhost-device-sound --backend alsa`, launcher).
- Open (was): test with a USB-C dock/monitor (DP alt mode entry, HPD, link training through the retimer, the dock's USB
  as host); a dock that powers the phone and leaves it as UFP needs a data-role swap
  (`echo host > /sys/class/typec/port0/data_role`); NB7 EQ/gain still at power-on defaults.

> Bring-up log moved from the old PORT-NOTES diary (2026-10-08..12); dated entries are as written then.
> Paths were updated to the current repo layout.

### USB3 (2026-10-11) — ✅ SuperSpeed 5 Gbps gadget (verified in reverse orientation; normal untested)
- Fixed: QMP USB3/DP combo PHY had dummy supplies. Now vdda-phy = L9A 1.2 V, vdda-pll = new L18A 0.912 V
  (stock ssphy core = pm8150_l9, vdd = pm8150_l18) in nio-el2-display.dts. FIT nio-el2-usb3.itb (= nio-el2.itb).
- Phone side looks ready: dwc3 DCFG speed = SuperSpeed, GUSB3PIPECTL sane, QMP PCS_STATUS1 = 0xb7 (PHYSTATUS
  clear). PM8150B TYPEC_MISC_STATUS (0x150b) = 0x29: attached, CC orientation bit clear = CC1/normal, which is
  the QMP default without a typec switch, so orientation is not the blocker for this plug direction.
- PC side: phone hangs off a Realtek RTS5411 (USB2 half 0bda:5411 = 1-2, SS half 0bda:0411 = 2-2); the SS peer
  port 2-2-port1 stays "not attached" -> the host never detects SS receiver termination. Soft disconnect/connect
  of the UDC doesn't change it. Next suspects: cable without SS pairs, or that hub port; then flipped plug
  (needs pm8150b typec -> QMP orientation-switch, see qrb5165-rb5.dts) for the other orientation.
- Root cause: the base DT (nio-el2.dts, from the USB2-only bring-up) sets `qcom,select-utmi-as-pipe-clk` on the
  dwc3 glue, so the DWC3 PIPE side ran from UTMI and SS never started (GDBGLTSSM frozen). Deleted in
  nio-el2-display.dts. Other required pieces (all in nio-el2-display.dts):
  - QMP PHY supplies L9A/L18A (above);
  - USB3 redriver enable: TLMM gpio12 output-high (gpio-hog). The board's redriver is the ON Semi NB7VPQ904M
    at i2c15 0x1a (GEN_DEV_SET reads 0xfb after enable = chip on, all 4 channels, USB mode, so no I2C init is
    needed for USB; the Diodes @0x52 variant and fsa4480 @0x42 don't answer). i2c15 + QUP2 wrapper enabled
    (QUP fw from qupv3fw.elf) for later DP alt-mode work;
  - plug orientation: patch 0007 `qcom-pmic-cc-orientation` reads PM8150B TYPEC_MISC_STATUS on
    cc-state-change/attach-detach IRQs and calls typec_switch_set() on the QMP PHY (graph: pmic@2/cc-orientation
    port <-> phy@88e8000 port@0). CC/PD stay in PMIC hardware mode, so the dev link never flaps.
- Result: `current_speed` super-speed, PC sees cdc_ncm at 5000M (reverse orientation), NCM phone->PC
  ~118 MiB/s (1 GiB in 8.65 s, nc, likely CPU-bound: cpufreq still deferred).
- Open: runtime plug-flip while connected needs a gadget reconnect to retrain (orientation is applied at
  attach, before enumeration, so normal hotplug is fine); NB7 EQ/gain left at power-on defaults.
- FIT: nio-el2-usb3.itb (= nio-el2.itb).
