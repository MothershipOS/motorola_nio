# EL2 bring-up debugging — channels & log possibilities (nio / XT2125-4, SM8250)

Goal: find out *why* a modified hyp (EL2 transition) faults before ABL, and iterate
toward a hyp that hands EL2 to the downstream path. The phone gives **no console** by
default and a bad hyp faults **before ABL**, so we need an out-of-band way to see the
fault. This folder collects the options, their reach, and the working loop.

Context: secure boot is NOT enforced on this engineering unit (`secure=no`,
`secure_hardware=0`) — proven by booting a stock-code hyp with a corrupted signature
(`kernel/EL2-hypb-nonboot-cause.md`). So we can freely flash modified hyp and iterate;
every failed boot is EDL-recoverable (`unbrick/`).

## Debug / log channels

| # | Channel | Reach (can it see a pre-ABL hyp fault?) | Cost | Notes |
|---|---------|------------------------------------------|------|-------|
| 1 | **SDI offline ramdump** (`Raw_Dmp!` → `ramdump` partition) | **Yes** — TZ/SDI snapshots memory + CPU context on crash | Low (armed: `emmc_dload=1`) | Read via root (now) or firehose `read` in EDL. Parser: `parse_rawdump.py`. Needs validation that CPU context is actually populated (the stale on-partition dump had a zeroed `CD_STRCT`). **Primary channel.** |
| 2 | **Flash/EDL bisect** | Indirect — boots/doesn't-boot per change | Low | Doesn't see registers, but localizes the faulting change (SPSR-only vs MMU-teardown-only vs combined). Uses the fast flash → fail → EDL-recover loop. |
| 3 | **In-hyp breadcrumbs** | Yes | Medium | Since we can flash arbitrary hyp, write checkpoint markers + captured regs to a persistent region (IMEM/`ramdump`-reachable DDR) before/at the transition, then read it post-crash. Only worthwhile if (1) can't capture the context region. |
| 4 | **UART console** (`uart12`@`0xa90000`, 115200 8N1) | **Yes, PROVEN reachable** — XBL already logs over it *before* QHEE loads, and it survives the fault's reset-to-EDL | Hardware (have it) | FT232 on `/dev/ttyUSB0`; full stock boot captured. Open: whether firmware leaves UART12 configured at the hyp handoff instant. See `uart/README.md`. Best "live" view. |
| 5 | **logfs partition** (`/dev/block/by-name/logfs`, sde18) | ABL-stage only | Low | ABL/UEFI log; a hyp fault is *before* ABL, so this won't hold the hyp fault. Useful once we get past hyp. Read via root/Magisk. |
| 6 | Firehose `read`/`getsha256digest`/`program` | n/a (storage only) | Low | Not a boot debugger (no `peek`/`poke` on this SM8250 build). Role: fast flash + readback + reading the ramdump partition in EDL. |

### What won't work
- Firehose can't single-step the boot or read DDR/registers live (no `peek`/`poke`).
- `/proc/last_kmsg`, pstore, Linux ramoops: only capture **Linux** (EL1) state — useless for a hyp fault that happens before Linux.
- A/B fallback: XBL faults before committing, so it does not auto-switch slots.

## SDI ramdump format (decoded)

Partition `ramdump` (sde28) starts with `Raw_Dmp!`. After a header, a table of 0x40-byte
entries:

```
entry + 0x00  u64 offset   # byte offset of this region's data within the partition
entry + 0x08  u64 size     # region size in bytes
entry + 0x10  u64 base     # physical base address in the SoC (0 for synthetic regions)
entry + 0x20  char name[]  # e.g. OCIMEM.BIN, CD_STRCT.BIN, DDRCS0_0.BIN
```

Regions of interest for a crash: `CD_STRCT`/`CD_BTDDR`/`CD_BTIMM`/`CD_SHIMM` (core-dump
structures), `OCIMEM` (on-chip mem, dump table + cookies), `RST_STAT` (reset status),
`DDRCS0_*` (DDR, large). `parse_rawdump.py` lists the TOC and extracts regions by name.

## The debug loop (proposed, being validated in this folder)

1. **Calibrate** (safe): arm dload, trigger a known kernel panic (`sysrq-c`, recoverable),
   capture the fresh `Raw_Dmp!`, and find where a *populated* CPU context lands + confirm we
   can read the panicking CPU's PC. Ground-truth with a crash we know is EL1.
2. **Capture the hyp fault:** flash an EL2 candidate → boot → fault → read its rawdump →
   extract CPU0's EL2 context (`ESR_EL2`/`ELR_EL2`/`FAR_EL2` or equivalent saved regs).
3. **Bisect:** SPSR-only vs MMU-teardown-only candidates to localize the faulting change.
4. **Fix & iterate:** correct the EL2 entry contract (exec-map ERET target under EL2
   stage-1; set `VBAR_EL2`/`SP_EL2`/`HCR_EL2`/`SCTLR_EL2`), reflash, repeat.

Results of each run are logged in `runs/` (created as the loop executes).
