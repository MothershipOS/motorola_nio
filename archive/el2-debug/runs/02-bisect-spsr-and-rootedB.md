# Run 02 — SPSR-only bisect + rooted slot-B clone (2026-10-07)

## Bisect #1: SPSR-only candidate
Built flash-ready single-change variants with `el2-debug/build_bisect.py`
(validated: rebuilding 'combined' reproduces the known candidate sha256
`fbdc0fbf…` exactly, so the variants are exact subsets).

- `hyp_b_spsr_only.img` (sha `e61deadc…`): stock + SPSR EL1h→EL2h @0x800401d8 + hash.
- `hyp_b_teardown_only.img` (sha `e68a7369…`): stock + MMU/cache teardown block + hash.

Flashed **SPSR-only** to slot B, set active B, cold-booted:
**Result → pre-ABL fault (device dropped to EDL 9008).**

Conclusion: **the SPSR EL1h→EL2h change ALONE is sufficient to brick the boot.**
Returning the handoff ERET to EL2h (against QHEE's EL1-guest MMU/stage-2 state) faults
before ABL; the MMU/cache teardown block is not required to trigger it. (teardown-only
not yet tested — next.)

## Recovery observation (loop automation)
After the SPSR-only fault the phone **auto-entered EDL (05c6:9008, normal PBL Sahara
image mode)** with no manual button combo — consistent with `emmc_dload=1` arming
download-on-crash. Recovered by firehose-restoring stock hyp_b (`unbrick/fh.py
--attach --phase restore-hypb`). This makes the bisect loop nearly hands-free
(flash → boot → auto-EDL on fault → firehose restore), to be re-confirmed per run.

## SDI dump capture (partial)
Attempted to firehose-`read` the ramdump partition (LUN4 LBA 28616699) after the fault,
but `fh.py read_sectors` has a raw-mode framing bug (returned 63775/65536 bytes, no
`Raw_Dmp!` magic). Not pursued further this run. Open: fix `read_sectors`, and confirm
whether a pre-ABL hyp fault even writes a fresh SDI dump to storage (calibration run 01
showed CD_STRCT empty for an EL1 panic, so hyp-fault dump utility is still unproven).

## Slot B is now a rooted clone of A
Per user request, cloned A's boot chain → B (root, via `dd` by-name, each sha-verified):
`boot`, `dtbo`, `vendor_boot`, `vbmeta`, `vbmeta_system` (A → B). Set active B, booted:
**B now boots with root** (`uid=0 magisk`, slot `_b`). hyp_b is stock.
Effect: hyp experiments on B now boot into a rooted, known-good userspace (root available
to read `/dev/kvm`, CurrentEL, logs, and the ramdump partition). A remains the untouched
safe fallback. B's original boot-chain partitions are in the 2026-09-27 backup if needed.

## Bisect #2: teardown-only (added 2026-10-07)
Flashed `hyp_b_teardown_only.img` (SPSR left stock EL1h; only the masked MMU/cache
teardown block changed) to slot B, booted:
**Result → pre-ABL fault; Qualcomm crashdump screen; SDI wrote a fresh `Raw_Dmp!`**
(fingerprint `08a0a7e4…`, RST_STAT=3), then rebooted to fastboot (no crash-loop).

Conclusion: **BOTH single changes independently brick the boot.** The masked teardown
breaks even the normal EL1 handoff — so that block is load-bearing (it is not a safe
no-op to mask). The combined candidate therefore had two independent faults.

Dump mining outcome: `CD_STRCT` is empty even for this SDI-caught crash; the obvious
small regions (OCIMEM/DDR_DATA/CD_SHIMM) hold no QHEE-range PC; the `CrashDMP`/`CRASH!!!`
strings are an AOP/RPMh message-label table, not a crash record. Extracting the EL2 fault
registers needs the full Qualcomm ramdump parser (msm_dump_table → per-CPU context in DDR)
or an in-hyp breadcrumb. Deferred in favor of offline construction.

Recovery: crashdump → fastboot; restored stock hyp_b, set active A, booted A (rooted). Clean.
