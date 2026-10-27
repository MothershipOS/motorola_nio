# Run 01 — calibrate SDI ramdump on a known kernel panic (2026-10-07)

Armed `emmc_dload=1`, `sysrq=1`; triggered `echo c > /proc/sysrq-trigger`.

Result: device panicked and **rebooted back to Android** (recoverable, non-destructive).
A **fresh** `Raw_Dmp!` was written to the `ramdump` partition (first-1MB sha changed
`320390b0…` → `93e8ad5b…`). `RST_STAT.BIN = 0x00000003`.

Findings:
- SDI offline rawdump channel WORKS and is cheap/repeatable. TOC format confirmed; full
  region table extracted via `parse_rawdump.py toc`.
- `CD_STRCT.BIN` is **all-zero even after a real panic** → the AP CPU register context is
  NOT stored there on this device. (So the earlier stale dump's zero CD_STRCT was not the
  tell we hoped.)
- OCIMEM references `kernel_panic.txt` / `kernel_log.txt`: for an **EL1 kernel** panic the
  captured artifact is the Linux panic log (in DDR), not a register struct.

Implication for the hyp (EL2) fault:
- A hyp fault happens before Linux, so there will be **no kernel_panic.txt**. The ramdump
  would still snapshot all DDR/IMEM, but extracting the EL2 fault state requires locating
  **QHEE's own hyp log / TZ diag** in the DDR image (address TBD from the SMEM/hyp-log
  analysis), which is materially harder than reading a Linux log.
- Therefore **bisect (flash → boot/no-boot → EDL-recover)** is the more reliable primary
  signal; ramdump mining of the hyp log is a secondary, deeper option.
