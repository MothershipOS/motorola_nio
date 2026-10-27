# Run 10 — M1c: EL2 + own identity map works; stock UEFI hangs at EL2 (2026-10-07)

M1c shim (`el2-debug/shim/shim.c` + `shim_entry.S`, `--mode shim`/`shimdbg`): at the handoff,
build our OWN EL2 stage-1 identity map (64×1GB blocks at 0x800a5000: 0-2GB Device, 2GB+ Normal
RWX), repoint `TTBR0_EL2`, clear `SCTLR_EL2.WXN`, flip SPSR EL1h→EL2h, eret. QHEE tables untouched.

## Result: identity map WORKS; UEFI starts at EL2 then HANGS

```
QHEE Image Load (444216 B)  → SBL1, End  → UEFI Start [1266]   <- UEFI running at EL2
   ... no further UEFI output ...
motorola_wdog_dump Begin, wdog_status: 1   <- WATCHDOG (hang, not a fault)
BL error can't be recovered, entering blank mode!!!  -> EDL
```

- **No EL2 fault** (`EL2FAULT=0`): our EL2-vector capture did NOT fire — so UEFI did not take a
  synchronous abort. The identity map fixed run 08's Device-memory/alignment fault and run 09's
  unmapped-write fault. **UEFI executes at EL2 with Normal cacheable memory.**
- **CORRECTION (UEFI's own exception dump, captured on screen):** UEFI did NOT silently hang —
  it ran a large chunk of DXE at EL2 (printed full RAM map: cs0 0x80000000+0x3b800000, cs1
  0x180000000+4GB, "CPU Cores: 8", multithread lib, ASLR/DEP on), then took ONE exception:
  `Synchronous Exception at 0x9FC02068`, `SPSR=0x200000C9` (EL2h confirmed),
  `ESR=0x02000000` → **EC=0x00 (Unknown/UNDEFINED instruction), IL=1, ISS=0** (FAR stale).
  UEFI's `DefaultExceptionHandler` then `ASSERT`ed (`DefaultExceptionHandler.c +295`) and halted
  → watchdog. So it's a single instruction at `0x9FC02068` (LR `0x9FC0267C`) that is undefined
  at EL2 but would be fine at EL1 — not a systematic wall at `UEFI Start`.
- Incidental: DRAM = `0x80000000`–`0x280000000` (8 GB: cs0 4 GB @0x80000000, cs1 4 GB
  @0x180000000). TZ's `backup_tz log` carried a bogus pointer `0x42445953` ("mot_in_ddr_range
  FAIL") — a crash symptom, not the cause.

## The faulting instruction (memread probe, `--mode memread` @0x9fc02040) — DECISIVE

Disassembly at the fault PC:
```
0x9fc02064: ret
0x9fc02068: mrs   x0, scr_el3          <<< undefined at EL2 (EC=0) -> the fault
0x9fc0206c: orr   x0, x0, #0x400       ; SCR_EL3.RW = 1
0x9fc02070: msr   scr_el3, x0
0x9fc02074: msr   hcr_el2, x0 (0x80000000)
0x9fc0207c: msr   cptr_el2 ; msr cpacr_el1 ; msr sp_el1 ; msr elr_el3
0x9fc0209c: msr   spsr_el3, #0x3c5 (EL1h) ; isb ; eret     ; drop to EL1
0x9fc020ac: mrs   x4, currentel ; cmp #4(EL1) ; cmp #8(EL2) ...   ; EL dispatcher
```
This is **UEFI's own startup EL-transition code — it demotes itself to EL1** via SCR_EL3/
ELR_EL3/SPSR_EL3 + `eret`. Normally QHEE enters UEFI already at EL1, so this path is a no-op
(`currentel==EL1 -> ret`). Our shim enters at EL2, so UEFI runs its drop-to-EL1 path and the
`mrs x0, scr_el3` (EL3-only register) is undefined at EL2 -> EC=0 fault.

## VERDICT — stock UEFI cannot yield EL2; M3 (replace the loader) is required

Stock Moto UEFI is **hard-wired to demote to EL1** (it actively erets itself down and then runs
EL1-assuming code: sp_el1, cpacr_el1, ...). So the kernel it launches will always be at EL1 —
there is no patching stock UEFI into keeping EL2 (its whole startup + body assume EL1). This is
hard, instruction-level proof for the roadmap's M3 decision: **replace stock ABL/UEFI with an
EL2-native loader** (u-boot-qcom / edk2-msm), exactly as the Renegade/edk2 projects do. The M1c
shim (EL2 + identity map) is the correct EL2 entry to put *under* that loader.

## Interpretation — M1 is achieved; the wall is stock ABL/UEFI at EL2

M1's goal (land the HLOS chain at EL2 with a usable memory map) is **done**: the chain reaches
UEFI and runs it at EL2. The remaining blocker is that **stock Motorola ABL/UEFI is EL1-built and
hangs in early init at EL2** — exactly the risk flagged in the roadmap. Likely causes (not
distinguishable from UART, UEFI stopped logging): it reconfigures EL1 MMU/vectors that are inert
at EL2 and then wedges, or its first post-start SMC/PSCI to EL3 (previously mediated by QHEE)
hangs when called directly from EL2.

Fighting stock UEFI at EL2 is a dead end (we can't instrument it and it won't log). This matches
the prior-art finding: Renegade/edk2 projects *replace* ABL rather than coerce it.

## Decision: proceed to M3 (EL2-native loader), skip trying to fix stock ABL

Per `KVM-ROADMAP.md`, the pass-through shim (M1c) is the EL2 entry; the loader after it must be
one that *expects* EL2. Next: flash an EL2-native loader (u-boot-qcom / edk2-msm, SM8250 target)
to `abl_b`, let XBL load it as APPSBL, our shim flips it to EL2 + idmap, and it launches the kernel
at EL2. The M1c shim is reusable as-is under a custom loader.

(Optional, cheaper first probe before the full loader port: build a tiny EL2-native payload
ourselves — M2 — flashed where ABL loads, that just confirms `CurrentEL==2` and a working identity
map by printing over UART, to validate the shim→payload contract independent of UEFI.)

## Status
Shim(dbg) M1c on slot B; boots → UEFI hang → watchdog → EDL. Phone in EDL. Shim verified correct
(entry in asm `shim_entry.S`; `build_l1_idmap` C, frameless). `build_uart_marker.py` modes: shim,
shimdbg (+ the dump/probe modes).
