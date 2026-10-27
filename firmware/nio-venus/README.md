# nio Venus (iris2) video firmware — non-secure

`venus.mbn` is the upstream Qualcomm reference Venus firmware for SM8250 (iris2),
version **VIDEO.VPU.1.0-00119**, taken verbatim from linux-firmware:

- linux-firmware path: `qcom/vpu-1.0/venus.mbn` → symlink → `qcom/vpu/vpu20_p4.mbn`
- upstream: https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/qcom/vpu/vpu20_p4.mbn

**Why this and not the Motorola stock `modem`-partition `venus.mdt`:** the stock blob is the
signed secure PAS build and only runs through TrustZone's secure bring-up, which needs the
secure-SID register block (`0x0aac2000`) that our u-boot→Linux@EL2 cannot write (see the
`nio-venus-el2-wall` notes / `docs/video.md`). This upstream single-`.mbn` is loaded
**non-secure** via the driver's no-TZ path (`video-firmware` DT subnode), so the secure-SID
step is never needed. Same iris2 core, same HFI6xx, entry `0x0f500000` as the stock blob.

Shipped in the host initramfs as `/lib/firmware/qcom/sm8250/nio/venus-vpu.mbn` (`motorola_nio/boot/initramfs.json`).
