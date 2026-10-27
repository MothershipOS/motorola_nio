SDX55 modem firmware for the nio host (`/lib/firmware/qcom/sdx55m`). The SDX55 is flashless: the host feeds it
everything (kernel: `motorola_nio/kernel/patches/0025`-`0027`; host: `mship-modem`, contract `mothershipOS/docs/contracts/mship.modem-1.md`).
Proprietary: the blobs stay local, `SHA256SUMS` lists them.

| Files | From | Used by |
|---|---|---|
| `sbl1.mbn` | `modem_a` image, `/image/sdx55m/` | BHI (mhi_pci_generic's firmware) |
| `apps.mbn`, `qdsp6sw.mbn`, `tz.mbn`, `hyp.mbn`, `aop.mbn`, `sec.elf`, `devcfg.mbn`, `apdp.mbn`, `acdb.mbn`, `mdmddr.mbn`, `multi_image*.mbn`, `xbl_cfg.elf` | `modem_a` image, `/image/sdx55m/` | Sahara boot images (mhi_sahara; image ids in `dist/rootfs/etc/modprobe.d/mothership-modem.conf`) |
| `efs1.bin`..`efs3.bin` | `modem_a` image | not used: placeholders (`IMGEFS- DUMMY`). The real NV is the phone's `mdm1m9kefs1/2/3_a` partitions, read raw by mhi_sahara |
| `modem_pr/` | `modem_a` image, `/image/modem_pr/` | TFTP `/readonly/firmware/image/modem_pr/...` (MCFG configurations by software order) |
| `fsg/` | the phone's `fsg_a` partition (ext4) | TFTP `/readonly/vendor/fsg/...` (`mcfg_sw/mbn_sw.dig`, carrier configurations `nio/superj/...`; the `*.img.gz` are factory EFS3 images per board) |

No identifiers in any of it: the same files are on every nio (the IMEI and calibration live only in the NV
partitions). Install: copy the directory to `/lib/firmware/qcom/sdx55m` on the phone.

Debugging: the modem's own log (F3 messages over DIAG, `/dev/wwan0qcdm0`) is QShrink 4: hashes, no text. The
strings are in `/image/sdx55/qdsp6m.qdb` of the `modem_a` image (a zlib stream from offset 0x40; lines
`<hash>:<ss_mask>:<ssid>:<line>:<file>:<string>`).

State on the phone: `/var/lib/mothership/modem/readwrite` (the modem's own TFTP files), `/var/lib/mothership/modem/efs-backup`
(each NV partition as it was before `mship-modem` first wrote it).
