# Display: panel via msm KMS at EL2, boot console, host compositor

> Bring-up log moved from the old PORT-NOTES diary (2026-10-08..12); dated entries are as written then.
> Paths were updated to the current repo layout.

## A4 display bring-up (2026-10-11): internal panel driven by msm KMS at EL2
Panel = Tianma NT36672C 6.7" 1080x2520, DSC (slice 540x20, 8bpc, 8bpp, block-pred), video mode, 4 lanes,
90 Hz (h 164/12/56, v 32/10/22). Data from the stock DT node `qcom,mdss_dsi_mot_tm_nt36672c_670_1080x2520_dsc_vid`.
- Kernel patch 0004: `panel-tianma-nt36672c-nio.c` (stock init sequence + PPS, reset 1/10ms 0/1ms 1/10ms) and
  `qcom-pm8150l-lcdb.c` (PM8150L LCDB +/-5.5 V bias: toggles MODULE_EN 0x46 bit7, waits VREG_OK 0x08 bit7;
  voltages left at PMIC defaults 0x13 — encoding unverified, deliberately not written).
  Config: BACKLIGHT_CLASS_DEVICE=y, BACKLIGHT_QCOM_WLED=y, + the two new drivers (=y).
- DT `nio-el2-display.dts` (includes nio-el2.dts, path overrides): mdss/dsi0/dsi0-phy okay; vdda=L9A 1.2V,
  vdds=L5A 0.88V, panel vddio=L1C 1.8V, vsp/vsn=LCDB; reset TLMM gpio75 active-low; WLED5 4 strings,
  OVP 20.5V, boost 1050mA, default 2048/4095; simple-framebuffer disabled.
- Result: `msm-kms` on card1, DSI-1 connected 1080x2520, fbcon 135x157, CRTC active, DSI bit clk 826 MHz,
  pclk 137.7 MHz, LCDB VREG_OK, backlight 2048. One early `DSI PLL(0) lock failed` at probe (before bind), then OK.
- **Visually confirmed**: fb0 colour-bar/gradient/grey-ramp test pattern displays correctly (no artefacts), so upstream
  DSC slice_per_pkt=1 is accepted by the panel (stock uses 2; no patch needed). Backlight sysfs
  (/sys/class/backlight/backlight, 0..4095) accepts writes; actual_brightness follows.
- deploy_fit.sh fixed for the Ubuntu root (busybox wget fallback, no `sha256sum -s`).
- FITs: nio-el2.itb = display build; nio-el2-a2.itb = previous (A2) build.

### A4: boot console on the panel (2026-10-11)
U-Boot env bootargs (`qcom-phone.env`, baked into hyp_b) are serial-only. Rather than reflash hyp_b, kernel
patch 0005 re-adds `CMDLINE_EXTEND` to arm64 (drivers/of/fdt.c appends CONFIG_CMDLINE):
`console=tty0 console=ttyMSM0,115200n8 fbcon=font:TER16x32`. Kernel log goes to the panel and the UART;
ttyMSM0 is listed last so /dev/console (initramfs fallback shell, systemd status) stays on the UART.
fbcon 67x78 (Terminus 16x32); after boot getty@tty1 shows the login prompt. FIT: nio-el2-console.itb
(= nio-el2.itb); previous display build kept as nio-el2-display-v1.itb.

### A4: host compositor = sway (2026-10-11)
sway 1.11 + seatd 0.9.2 + foot, Ubuntu packages. `mship-sway.service` (graphical.target, replaces getty@tty1)
runs sway as user `mship` (groups video/render/input) with XDG_RUNTIME_DIR=/run/mship-wayland,
WLR_DRM_DEVICES=/dev/dri/card1 (card0 is the render-only adreno node), WLR_LIBINPUT_NO_DEVICES=1, seatd backend.
wlroots: atomic KMS on msm-kms, GLES2 renderer on FD650 (via card1 primary node -> freedreno), GBM allocator.
Output DSI-1 1080x2520@90 scale 2, xwayland disabled. Verified across a reboot; grim screenshot shows the bar
and the autostarted foot terminal. Benign log errors: "Failed to parse EDID" (DSI panel), swaybar tray (no user bus).
Files + installer: mothershipOS/host/sway/. Screenshot over ssh:
`su mship -c 'XDG_RUNTIME_DIR=/run/mship-wayland WAYLAND_DISPLAY=wayland-1 grim /tmp/shot.png'`.
Open: no input yet (touchscreen driver not brought up), clock wrong until set from the PC (no RTC/NTP).
