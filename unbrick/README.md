# Unbricking the nio (Motorola XT2125-4, SM8250 / Snapdragon 870)

Dedicated, self-contained recovery kit for this phone. **Proven 2026-10-06**: it
recovered a hard-brick caused by flashing a modified `hyp_b` (EL2/KVM experiment).

- Tool: `mship-dev edl` (crates/mship-dev/src/edl.rs) — Sahara loader upload + Firehose client (read / digest /
  program / guarded hyp_b restore). Raw USB by default (usbdevfs: bypasses the flaky qcserial path; attaches a
  running firehose without set_configuration and drains its hello first); `--port /dev/ttyUSBn` for serial.
- Loader: `images/prog_firehose_ddr_SM8250.elf` (local recovery set, untracked: loader, stock hyp_a/hyp_b,
  manifest.json, GPT heads; recovery never needs the network)
  (sha256 `f128fe48d187c77c78b66211907fd793349a3808c1a2953d9c4918e21971a06e`).
- Every other stock image (full read-only backup of 2026-09-27): NAS
  `<nas>:<backups>/mothershipOS-backups/pc-backups-20261012/nio-firmware-20260927T163534Z/` (sha256 list in `../SHA256SUMS` there).

---

## 1. Recognise the situation

Flashing a bad **hyp / xbl / tz / abl / devcfg** to the active slot bricks the phone
so it **does not enumerate** as fastboot or adb. On this SoC the boot order is
`PBL → XBL → (loads tz, hyp) → ABL(fastboot)`, so a bad **hyp** faults *before* ABL
runs — fastboot never comes up and there is nothing to "catch". A periodic **white
status-LED blink while holding Power+Vol-Down** means PBL is alive → EDL is reachable.

Do **not** just hold Power+Vol-Down forever — that only holds the SoC in reset. The
recovery channel is EDL.

## 2. Enter EDL (Qualcomm 9008)

1. Phone fully off and **unplugged**.
2. Hold **Vol-Up + Vol-Down together**.
3. **Plug the USB cable into the PC while still holding both.** Release after it enumerates.

Verify on the host:
```
lsusb | grep -i 05c6:9008      # Qualcomm HS-USB QDLoader 9008
ls -l /dev/ttyUSB0             # qcserial binds it; no extra driver on Linux
```
If the Sahara state ever gets wedged (repeated partial handshakes), **replug** for a
clean session. A USB-reset ioctl tends to drop this device *out* of EDL — prefer a replug.
A fresh enumeration emits a spontaneous Sahara HELLO (v2, mode 0); `mship-dev edl` relies on that.

## 3. The loader (why we don't run Moto's flasher)

The Moto `blankflash` package (`blankflash_rebuild_nio_retail_S1RTS32.41-20-16-1-2.zip`,
mirror: https://mirrors-obs-1.lolinet.com/firmware/lenomola/2021/nio/blankflash/)
bundles a Linux `qboot` + `singleimage.bin`. **Running `qboot`/`blank-flash.sh` rewrites
the bootloader** from `singleimage.bin` — on a dev phone that risks an anti-rollback (ARB)
hard-brick. We do NOT run it.

Instead we use **only the signed firehose loader** embedded in `singleimage.bin`
(64-bit SM8250 ELF at byte offset **571136**, `BOOT.XF.3.2-00310-SM8250`, 716224 bytes).
It runs in RAM and writes nothing by itself, so ARB is irrelevant. It is already
extracted and saved at the loader path above. To re-extract/verify from a blankflash (the ELF ends at
716224 bytes):
```
dd if=singleimage.bin of=firehose.elf bs=4096 iflag=skip_bytes,count_bytes skip=571136 count=716224
sha256sum firehose.elf   # must print f128fe48d187c77c78b66211907fd793349a3808c1a2953d9c4918e21971a06e
```

## 4. UFS partition map (4096-byte sectors)

| LUN | Linux dev | Role       | Key partition |
|-----|-----------|------------|---------------|
| 1   | sdb       | Boot A     | xbl_a         |
| 2   | sdc       | Boot B     | xbl_b         |
| 3   | sdd       | System A   | **hyp_a @ LBA 1184, 2048 sectors (8 MiB)** |
| 5   | sdf       | System B   | **hyp_b @ LBA 1184, 2048 sectors (8 MiB)** |

Full per-partition device nodes + sizes + sha256 are in
`images/manifest.json`.
Stock hyp digest (both slots): `F69538BF…0240D8B2`.

## 5. Recover

Set a shell var for brevity:
```
BK=images      # or a copy of the NAS folder for partitions other than hyp
LOADER=$BK/prog_firehose_ddr_SM8250.elf
```

**Read-only probe** (prove firehose + read hyp_a/hyp_b digests and the hyp_b GPT entry):
```
mship-dev edl --loader $LOADER --probe
```

**Restore the broken partition** — example for `hyp_b` (the proven fix):
```
# dry run first (no write):
mship-dev edl --loader $LOADER --restore-hyp-b $BK/hyp_b.img
# then commit:
mship-dev edl --loader $LOADER --restore-hyp-b $BK/hyp_b.img --commit
```
`--restore-hyp-b` refuses any image that is not exactly 8 MiB and the known stock hash,
and re-reads the digest after writing to confirm. Use `--attach` (and drop `--loader`)
to talk to an already-running firehose instead of re-uploading.

**Reboot out of EDL:** the firehose `<power value="reset" />` (sent by the verify step),
or simply replug and power on.

### Restoring a different partition
Only hyp_b has a guarded restore. For another partition, `mship-dev edl --loader $LOADER --program LUN START NUM IMG`
with LUN/start/num from `manifest.json` + the per-LUN GPT in `$BK/gpt-sd*-head.bin` (`--digest LUN START NUM`
checks it afterwards). **Only ever restore the partition you broke.** Do NOT touch
`xbl*/abl*/tz*/devcfg*` unless that is specifically what is damaged — and never run
Moto `qboot`/`singleimage`.

## 6. Verify recovery
```
adb wait-for-device
adb shell getprop ro.boot.slot_suffix     # which slot booted
adb shell getprop ro.bootmode             # normal
```

## 7. What NOT to do
- Don't run `qboot` / `blank-flash.sh` / flash `singleimage.bin` (rewrites bootloader; ARB risk).
- Don't write `xbl/abl/tz/devcfg` over EDL unless that exact partition is the damage.
- Don't attempt the A/B active-slot switch here — it is GPT attribute-bit surgery and is
  **not** implemented in `mship-dev edl`. Restoring the broken partition is simpler and safer. If
  you genuinely need `setactiveslot`, use Bjoern Kerler's `edlclient` with this loader.

## Confirmed recovery — 2026-10-06
Modified `hyp_b` → no USB/fastboot (hyp faults before ABL). EDL 9008 → uploaded this
firehose → `program` stock `hyp_b` to LUN5/1184/2048 → digest verified stock → phone
booted normally on slot B (Android 16, adb authorized). No bootloader partition written.
hyp_a verified stock throughout.
