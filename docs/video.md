# nio hardware video decode (Venus / iris2) at EL2

**Status: working (2026-10-19).** Hardware decode runs on our u-boot→Linux@EL2 boot without the
stock Qualcomm hypervisor (QHEE). Verified: the `qcom-venus` driver registers a
`qcom-venus-decoder` and a `qcom-venus-encoder` V4L2 node, advertises
H.264 / HEVC / VP9 / VP8 / MPEG-2, and a real **3840×2160 H.264** clip decodes to NV12
(no HFI errors, no reset). The `/dev/videoN` index is **not stable across boots** (decoder and
encoder race to register) — resolve by `/sys/class/video4linux/video*/name`, not a fixed index.

## The problem it solves

The stock bring-up programs a secure-SID register block at `0x0aac2000` (Venus wrapper +
`0x2000`) that is hardware-access-controlled to the stock hypervisor's bus identity. From our
EL2 those writes are silently dropped, and releasing the Venus CPU without them causes an
instant, diagnostic-silent SoC reset. Every route to program that block from our EL2 was ruled
out (power, the full register-interface clock tree incl. the QMIP AHB clocks, CPU identity,
MMU memory type, every SCM/MEM_ASSIGN path, and the reset emits nothing even on the hardware
UART). See the `nio-venus-el2-wall` memory notes for the full dead-end log.

## The solution: non-secure (no-TZ) bring-up

Mainline brings Venus up on sc7180/sc7280 **without** TrustZone, via a `video-firmware` DT
subnode (`drivers/media/platform/qcom/venus/firmware.c`: a subnode makes the driver set
`use_tz=false`, load the firmware itself with `qcom_mdt_load_no_init`, map it for the firmware's
own SMMU stream, and release the core — never touching the secure-SID block). sc7280 is
`iris2_1`, the same core family as our sm8250 `iris2`.

Two pieces make it work on the nio:

1. **A non-secure firmware blob.** The Motorola stock `venus.mdt` (from the `modem` partition)
   is the signed secure PAS build and hard-resets the SoC on core release. We use the upstream
   Qualcomm reference blob instead — linux-firmware `qcom/vpu-1.0/venus.mbn`
   (VIDEO.VPU.1.0-00119), staged in `motorola_nio/firmware/nio-venus/venus.mbn` and installed as
   `/usr/lib/firmware/qcom/sm8250/nio/venus-vpu.mbn`. Same iris2 core, entry `0x0f500000`, but
   loaded non-secure it does not make the fatal secure access.

2. **The firmware's SMMU stream IDs.** On core release the apps SMMU (GR0 `0x15000000`) reports
   the firmware's fetch SID in the global fault syndrome. The nio firmware fetches with SIDs
   `{0x2102, 0x2502}`, so the `video-firmware` subnode maps `<&apps_smmu 0x2102 0x400>` (mask
   `0x400` covers both; disjoint from the codec data streams `0x2100`/`0x2500` the main node
   owns). The sc7180/sc7280 "base + 0x42" convention (`0x2142`) is **wrong** for the nio — it
   faults on `0x2102`.

## Bring-up (boot-time, current)

Baked into the booted DTB: the Venus node in `motorola_nio/boot/nio-el2.dts` is `status = "okay"`
with `firmware-name = "qcom/sm8250/nio/venus-vpu.mbn"` and the `video-firmware { iommus =
<&apps_smmu 0x2102 0x400>; }` subnode. The matching maintained source is the `&venus` stanza in
`motorola_nio/kernel/dts/sm8250-motorola-nio.dts`. The firmware ships in the host
initramfs (`motorola_nio/boot/initramfs.json`). Venus now probes automatically at boot — verified: no
overlay module, `qcom-venus-decoder` node present, 4K H.264 decodes.

Runtime overlay (`motorola_nio/kernel/dts/overlays/nio-venus-notz.dts`, applied with
`insmod nio_of_overlay.ko firmware=nio-venus-notz.dtbo`) is kept for iterating without reflashing
the FIT. The decoder is the `qcom-venus-decoder` V4L2 node (index varies per boot — resolve by
name). Diagnostic aid: venus module param `mship_notz_stop=4` releases the core and watches the
apps-SMMU GFSR for the firmware's first faulting SID instead of letting the SoC reset (use it if
the SIDs ever change on a firmware update).

## Exposing the decoder to the PixelOS VM (virtio-media)

The guest gets the host Venus decoder through **virtio-media** (crosvm `--v4l2-proxy` → guest
`virtio-media.ko` → a V4L2 decoder node inside Android), per the generic device-brokering plan — no
phone-specific driver in the guest image.

Done 2026-10-19:
- **Host crosvm**: built with the `media` cargo feature (`host/gpu/build-crosvm.sh`,
  `--features …,media`; needed `BINDGEN_EXTRA_CLANG_ARGS=-I/usr/include/aarch64-linux-gnu` so
  `v4l2r`'s bindgen finds `sys/time.h`). The installed `/opt/mship-gpu/bin/crosvm` now has
  `--v4l2-proxy`.
- **Launcher**: `pixelOS_16_VM/launcher/mship-vm-pixelos-crosvm` passes
  `--v4l2-proxy=/dev/<qcom-venus-decoder>` (resolved by name) when using our crosvm
  (`MSHIP_VM_VIDEO=true`, default).
- **Guest driver**: `mothershipOS/guest/drivers/virtio_media/virtio-media.ko` built against the guest GKI
  kernel; `pixelOS_16_VM/image/mk-crosvm-initrd.sh` injects it into the guest ramdisk when present
  in `pkg/`.

Remaining (not yet done):
- **Android Codec2 V4L2 component** in the PixelOS guest so the media framework actually routes
  decode through the virtio-media V4L2 node (the ChromeOS `libv4l2_codec2` / a `c2.v4l2.*`
  component), plus its `media_codecs` XML and SELinux. Without this the node exists in the guest
  but apps still fall back to SW codecs.
- End-to-end verification: boot the VM with the media-enabled crosvm + injected module, confirm the
  guest enumerates the V4L2 decoder, then a 4K clip in-guest.

## Productization TODO

- [done 2026-10-19] Boot-time: Venus probes from the base DTB, no runtime overlay.
- [in progress] VM bridge: host + guest-driver plumbing done; Android Codec2 V4L2 integration remains.
- Encoder node registers too but is untested.
