# nio userdata backup — handoff (2026-10-08, ~15:30)

Goal: back up nio `userdata` (sde27, 97.04 GiB = 25 x 4 GiB chunks, Android FBE-encrypted, barely
compressible) to the NAS, verify everything, THEN wipe userdata and use it as the mothershipOS volume.
The user has approved the wipe **only after** all 25 chunks are verified.

## Where the chunks are
| Chunks | Location | State at 15:20 |
| --- | --- | --- |
| 21–24 | NAS `<nas>:<backups>/mothershipOS-backups/nio-userdata-20261008/userdata.NNNN.img.zst` | verified, listed in `userdata.manifest` |
| 10–20 | PC staging `/media/buzz/36AF16E209FE6F65/nio-backup-stage/userdata.NNNN.img` (+ `.sha256` = sha256 computed while receiving) | being uploaded by `dual_backup.py run` (single uploader, ~9 MB/s, deletes each after NAS verify) |
| 0–9 | microSD card (now in the PC), folder `nio-backup/userdata.NNNN.img` + `.img.sha256` (sha256 computed ON THE PHONE while writing) | not yet copied |
| metadata | same NAS folder `metadata.img.zst` | verified (needed together with userdata to restore) |

Manifest line format: `idx raw_sha256 zst_sha256 raw_len`. Chunk i covers bytes [i*4GiB, (i+1)*4GiB) of
sde27 (dd bs=4M skip=i*1024 count=1024); chunk 24 is 1.04 GiB.

## Update ~15:40
The user stopped all background jobs, including the `dual_backup.py run` uploader. Chunks it had
finished are on the NAS and in the manifest (and were deleted from the PC stage). The chunk it was
uploading is a partial `userdata.NNNN.img.zst.part` on the NAS: delete any `*.part` there and re-upload.
Remaining PC-staged chunks are still in `nio-backup-stage/` with their `.sha256`. The SD card is now in
the PC (find its mount with lsblk; folder `nio-backup/`). The user approved wiping userdata on the
nio once ALL 25 chunks are verified (manifest complete + phone re-read match).

## Remaining steps (in order)
1. Let the PC-staged uploads finish (or speed up: ssh `-c aes128-gcm@openssh.com` + 3 parallel; the
   PC is on Wi-Fi and the NAS sshd pins one ARM core with chacha20).
2. Card: `python3 tools/nio-el2/dual_backup.py ingest userdata <NAS_DIR> --from <card mount>/nio-backup`
   (checks each chunk against the phone-written sha256, uploads zstd, verifies on NAS, appends manifest).
   Add `--delete` only to remove the chunk files from the card afterwards; the user's own files on the
   card (DCIM, Music, ...) must not be touched.
3. Confirm the manifest has all 25 indices 0..24.
4. Re-read on the phone: for each i, `dd if=/dev/sde27 bs=4M skip=$((i*1024)) count=1024 | sha256sum`
   must equal the manifest raw_sha256 (backup_chunked.py has a 4-at-a-time loop for this).
5. Optional end-to-end: on the NAS, `zstd -dc userdata.NNNN.img.zst | sha256sum` == raw_sha256 for each.
6. Only then wipe: `blkdiscard /dev/sde27` (or mkfs directly) on the phone and create the mothershipOS
   filesystem. Double-check the device is PARTNAME=userdata first.

Restore (same phone only, together with metadata.img):
`for i in $(seq -w 0 24); do zstd -dc userdata.00$i.img.zst; done | dd of=/dev/<userdata> bs=4M`

## Update ~16:25 — userdata WIPED
User relaxed the wipe condition to "all chunks verified somewhere on this PC/NAS". Verified at ~16:20:
card 0–9 vs phone-written .sha256, PC stage 10–20 vs receive-time .sha256, NAS 21–24 zst vs manifest — all 25 OK.
`blkdiscard /dev/sde27` (PARTNAME=userdata, 203504856 sectors) done; reads back as zeros. No filesystem yet
(phone has no mkfs). The phone can no longer be re-read, so **the card and PC-stage copies are now the only copies
of chunks 0–20 until they are on the NAS — do not delete them unverified.**
- PC stage 10–20: uploading via scratchpad `par_upload.py` (3 parallel, aes128-gcm, ~4–5 MB/s total over Wi-Fi);
  it deletes each local chunk only after NAS sha256 match + manifest append. If it died: rm NAS `*.part`, rerun
  `dual_backup.py ingest userdata <NAS_DIR> --from <stage> --delete`.
- Card 0–9 (`/media/buzz/android/nio-backup/`): not uploaded yet → `dual_backup.py ingest ... --from /media/buzz/android/nio-backup`.

## super backup (2026-10-08 ~17:56)
Full `super` (sde25, 12 GiB = 25165824 sectors) copied to the PC:
`/media/buzz/36AF16E209FE6F65/nio-super-backup-20261008/super.img`, sha256
`3a2de003ebde88f4466d0d3024927f6953d99f5ff5fb28abc8035690ecfdebc8` — matches the phone-side re-read
and a from-disk re-hash. LP metadata parses (system/system_ext/product/vendor/odm for slots a+b).
Only copy is on the PC (not yet on the NAS). Plan: shrink super -> 8 GiB host root, grow userdata backwards.

## sde GPT edited (2026-10-08 ~18:10) — super shrunk, userdata grown
4K-sector LUN sde (30746624 LBAs). Changed entries only (indices/numbers unchanged):
| # | name | start LBA | end LBA | size |
| 25 | mship-root (was super; type -> Linux fs 0fc63daf…) | 32768 | 2129919 | 8 GiB |
| 26 | pad4 (moved, 96 LBAs) | 2129920 | 2130015 | 384 KiB |
| 27 | userdata (start moved back, 1 MiB aligned) | 2130176 | 28616698 | 101.04 GiB |
Primary (LBA1-2) and backup (LBA 30746619/30746623) written, read back, kernel re-read OK.
Old/new sectors: `backups/gpt-sde-20261008-mship/`. Revert = write old-head LBA1-2 and old-tail LBA251/255
(of the 256-LBA tail) back. Stock Android on slot A no longer boots (super gone); full super image on the PC.
Neither partition has a filesystem yet (mship-root still contains old super bytes).

## Formatted (2026-10-08 ~18:20)
- sde25 `mship-root`: ext4, LABEL=mship-root, UUID 2ae142eb-b306-40eb-bbc3-ed339ef55e61, -m 1 (7.8G usable)
- sde27 `userdata`: ext4, LABEL=mship-data, UUID f54661a8-3294-492b-8315-1977de3d46ce, -m 0 (98.9G usable)
Both mount cleanly from the 6.18 EL2 host; both empty. Formatted from an ubuntu-base chroot in /ub (tmpfs).
