# Camera (OV64B through CAMSS)

> Bring-up log moved from the old PORT-NOTES diary (2026-10-08..12); dated entries are as written then.
> Paths were updated to the current repo layout.

## Camera bring-up (2026-10-11)
Sensors (stock vendor /lib64/camera sensormodules, copied to motorola_nio/firmware/nio-camera/):
main OV64B (64 MP, AF actuator + GT24 EEPROM), ultrawide OV16A10, depth OV02B1B, front OV16A1Q, front S5K4H7.
No mainline or public vendor driver exists for any of them. Mainline has sm8250 camcc, CCI and CAMSS (raw RDI
capture, no hardware ISP -> libcamera software ISP later).

### Stage 1 ✅ main camera powered and identified
- Power: WillSemi WL2864C 7-ch LDO on i2c15 @0x29, chip-select gpio100 (high), vin1 = L1C 1.8 V, vin2 = BOB.
  Kernel patch 0008 adds `wl2864c-regulator` (register layout from Motorola's GPL driver,
  kernel-work/reference/wl2864c). Rails for cam0 (stock cam-sensor@0): LDO1 dvdd 1.1 V, LDO3 avdd 2.8 V,
  LDO5 vaf 2.8 V, LDO7 dovdd 1.8 V (LDO7 is shared vio).
- Sensor cam0: CCI0 (ac4f000) master 0 = i2c-20, MCLK2 gpio96 (`cam_mclk`, CAM_CC_MCLK2_CLK 24 MHz),
  XSHUTDOWN gpio93 active low, CSIPHY2 (stock csiphy-sd-index 2). CCI0 bus: 0x0c (AF), 0x21/0x22 (OV64B),
  0x58 (EEPROM, starts "2002").
- `ov64b` bring-up driver: DOVDD->AVDD->DVDD->MCLK->reset release, chip id 0x300a = 56 64 42.
  Boot log: "OV64B detected at 0x21 (mclk 24000000 Hz)". keep_power=1 leaves it on for poking with i2c-tools.
- Sensormodule .bin = QTI Chromatix "Parameter Parser V2.0.0": symbol table of 0x48-byte entries
  {ffffffff, 0, offset u64, size u64, index u64, name[40]} pointing into a data blob (regSetting ->
  slaveAddr/registerData/delayUs ...). Needs a decoder to get the init/mode register tables (stage 2).

### Next stages
2. Decode the sensormodule (power sequence, init + mode register tables, CSI lane count / link frequency,
   exposure/gain registers) -> ov64b streaming (v4l2 subdev: one binned mode first, exposure/gain/vblank controls).
3. CAMSS: csiphy2 endpoint, CSID + VFE RDI capture of RAW10 via media-ctl/v4l2-ctl; verify a frame.
4. libcamera (software ISP) on the host -> usable images; then the other four sensors and the AF actuator.

### Stage 2a ✅ sensormodule format decoded (motorola_nio/archive/prototypes/camera/chromatix.py)
Full format description in the tool's docstring. `chromatix.py summary <bin>` -> motorola_nio/firmware/nio-camera/SENSORS.txt
(all five modules decode consistently); `chromatix.py ctable <bin> <prefix> <mode>` emits cci_reg_sequence tables.
OV64B (main): id 0x300a = 0x5664(42); x/y out 0x3808/0x380a, VTS 0x380e, HTS 0x380c, exposure 0x3500 (24-bit,
lines, min 8), analog gain 0x3508 (16-bit, real*256 per realToRegGain "256", 1.0x..15.94x); stream 0x0100=1/0,
group hold 0x3208=00 / 10,a0. Power-up: MCLK 24 MHz +1 ms, RESET low +1 ms, VAF, VANA, VDIG, VIO +1 ms,
RESET high +4 ms. Six modes, all RAW10 4-lane, VT clock ~115.2 M lines-units/s:
  0 9248x6944 10 fps (1996.8 Mb/s/lane) | 1 4624x3472 2x2 30 fps + PDAF vc1 576x428 (1699.2 Mb/s/lane)
  2 6016x3384 crop 30 | 3 3840x2160 2x2 60 | 4 1920x1080 4x4 120 (1699.2) | 5 1280x720 4x4 240
  init = 2815 writes (starts 0x0103=1 soft reset), mode 1 = 319 writes -> drivers/media/i2c/ov64b_regs.h.
  CFA enum 0 for all OmniVision parts (CamX BAYER_BGGR — confirm on the first raw frame).
Others: OV16A10 / OV16A1Q id 0x300b = 0x1641, same OmniVision register map; OV02B1B 1-lane 1600x1200
(8-bit register map, id 0x03 = 0x2b); S5K4H7 SMIA map (id 0x0000 = 0x487b, 3264x2448 4-lane).

### Stage 2b ✅ OV64B streams (sensor side)
- `drivers/media/i2c/ov64b.c` (patch 0008, now incl. ov64b_regs.h): v4l2-cci, subdev state API, runtime PM
  (autosuspend 1 s), stock power order (MCLK, RESET low, VANA/VDIG/VIO, RESET high). Mode 4624x3472 SBGGR10,
  4 lanes, LINK_FREQ 849.6 MHz, PIXEL_RATE 679.68 MHz, HBLANK 896 (HTS 5520 px) RO, VBLANK (VTS 4102 default,
  0x380e), EXPOSURE (0x3500, 8..VTS-32), ANALOGUE_GAIN (0x3508, 0x100..0xff0 = 1x..15.9x), rotation 90 /
  orientation back from DT. Stream on = soft reset (+5 ms) + 2815 init + 319 mode writes + ctrls + 0x0100=1
  (0.35 s). Endpoint: data-lanes 1-4, link-frequencies 849600000 (no remote yet).
- DT: the sensor needs `power-domains = <&camcc TITAN_TOP_GDSC>` — without it cam_cc_mclk2_clk is
  "stuck at off" whenever CCI is runtime-suspended.
- Bring-up aid: `echo 1 > /sys/kernel/debug/20-0021/stream` runs the real stream-on path without a bridge.
  Verified: registers read back as programmed; sensor frame counter 0x483f advances 30-31/s (= 30.02 fps);
  black-level stats at 0x40d0.. change live. Stream off -> runtime suspended.
- Next (stage 3): CAMSS csiphy2 <-> cam0 endpoint, CSID/VFE RDI, capture one RAW10 frame and check the CFA.

### Stage 3 ✅ RAW10 frames through CAMSS (CSIPHY2 -> CSID0 -> VFE0 RDI0 -> /dev/video0)
- DT: camss okay, vdda-phy = L5A 0.88 V, vdda-pll = L9A 1.2 V, port@2 endpoint clock-lanes 7 / data-lanes 0-3
  <-> cam0 endpoint (same wiring as the RB5 vision mezzanine: CSIPHY2 + MCLK2).
- Pipeline (motorola_nio/tools/camera scripts used on the phone): media-ctl -l csiphy2:1->csid0:0, csid0:1->vfe0_rdi0:0;
  SBGGR10_1X10 on all pads; v4l2-ctl /dev/video0 pBAA (stride 5792 @ 4624).
- **Kernel patch 0009 (upstream CAMSS bug on sm8250):** camnoc_axi_src was never scaled (name not in
  vfe_match_clock_names), so the camera NoC ran at 19.2 MHz -> VFE bus CCIF violation on WM23 (bus 0xaa64 bit 23,
  bus irq0 bit 30, CSID RDI status bit 18), no buf-done. Data reached CSID fine (pkts counter, 0 ECC/CRC).
  With the fix: camnoc 300 MHz, 4624x3472@30.00 fps and 1920x1080@120 fps capture reliably, every run.
- Debug registers that helped: CSID0 = VFE0 base 0xacb4000 + 0x1200; CSI2 RX total pkts 0x160, ECC 0x164,
  CRC 0x168, RDI0 cfg 0x300 / irq status 0x40 (raw, mask 0); VFE bus base +0xaa00: irq status 0x28,
  CCIF violation 0x64, overflow 0x68, image-size violation 0x70; RDI0 = WM23 at bus+0x200+23*0x100.
- ov64b: second mode (stock mode 4, 1920x1080 4x4 binned 120 fps, no PDAF VC) selectable with
  ov64b.mode_idx=1 (cmdline, or param + rebind).
- motorola_nio/archive/prototypes/camera/raw10view.py: unpack MIPI RAW10 -> quick-look PNG for a given CFA.
- ✅ First real image (reports/camera/ov64b-first-frame.png): CFA confirmed **BGGR** (SBGGR10 correct), black level ~64;
  display needs a 90° counter-clockwise rotation (matches DT rotation = <90>).

### Stage 4 ✅ all five sensors, processed frames, cameras in VMs (2026-10-26)
- **Sensors** (wiring from the stock kona-camera-sensor-mot-nio.dtsi; DT `motorola_nio/boot/nio-el2-display.dts`):

  | Camera | Sensor | CCI bus/master, addr | CSIPHY | MCLK | Reset | Rails (WL2864C) | Modes |
  |---|---|---|---|---|---|---|---|
  | back | OV64B | cci0/0, 0x21 | 2 | MCLK2 gpio96 | gpio93 | LDO3 avdd, LDO1 dvdd 1.1 V, LDO7 | 4624x3472@30, 1920x1080@120 |
  | back 2 (ultrawide) | OV16A10 | cci1/0, 0x10 | 3 | MCLK4 gpio98 | gpio91 | LDO4 avdd, LDO2 dvdd 1.2 V, LDO7 | 4608x3456@30, 1920x1080@60 |
  | depth (mono) | OV02B1B | cci1/0, 0x3d | 4 (1 lane) | MCLK3 gpio97 | gpio99 | LDO4, LDO7 | 1600x1200@30 Y10 |
  | front | OV16A1Q | cci0/1, 0x10 | 1 | MCLK1 gpio95 | gpio109 | LDO4, LDO2, LDO7 | 4608x3456@30, 2304x1728@30, 1080p120, 720p240 |
  | front 2 (ultrawide) | S5K4H7 | cci0/1, 0x2d | 0 | MCLK0 gpio94 | gpio78 | LDO4, LDO2, LDO7 | 3264x2448@30 GRBG |
- Driver `motcam` (patch 0028): one table-driven driver for the four new sensors, everything from the stock modules
  (register tables generated with chromatix.py into motcam_regs.h; exposure/gain/VTS registers, stream sequences,
  power order, CSI-2 timing); every stock mode, chosen by set_fmt (link frequency, pixel rate and blanking follow).
  OV02B1B has 8-bit paged registers (0xfd page, 0xfe=2 latches page 1). Gain codes follow each family's convention
  (the modules have no formula except OV64B's "256"). Subdevs are named after the sensor (`ov16a10 22-0010`).
- **Flash:** PM8150L flash LED (`leds-qcom-flash`), two channels `white:flash`, `yellow:flash`, torch 100 mA each.
- **libcamera** (Ubuntu 0.7, simple pipeline + software ISP on the GPU, `LIBCAMERA_SOFTISP_MODE=gpu`): lists all five,
  processes the four colour ones (the depth sensor's Y10 isn't supported by the GPU debayer). Needs a dma-buf heap:
  the system heap; the CMA heap is left out of the kernel (libcamera prefers it, does not fall back, and 32 MB of
  CMA is too small). 1080p30 from every colour camera; ~0.7-1 CPU core per running camera. Only one camera runs at a
  time (the simple pipeline locks CAMSS's media device).
- First lit frames (torch, the room is dark): correct colours, AE converging; no AF yet (actuators undriven), the
  ultrawide's full-resolution mode shows its PDAF pixels.
- **VMs** (`mship.camera`, `mothershipOS/docs/contracts/mship.camera-1.md`): mship-camera feeds one v4l2loopback node per VM and
  camera (BGRx 1280x720@30), crosvm proxies them with virtio-media. Needed: v4l2loopback in the kernel's extra/
  (with a DQBUF fix for callers that leave `memory` 0), virtio-media patch 0002 + crosvm 0008 (map buffers of devices
  that cannot export dma-bufs), the guest virtio-media driver surviving a session error. Ubuntu: the four cameras are
  V4L2 devices and PipeWire video sources; frames verified in the guest. Android: the external camera HAL patched
  for BGRx (pixelOS_16_VM/patches/hardware/interfaces), Cuttlefish's emulated cameras left out.
