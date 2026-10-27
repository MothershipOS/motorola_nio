> **SUPERSEDED (run 06):** the "caught at EL3" conclusion here is WRONG — it came from patching 0x80040330 instead of the real VBAR_EL2=0x80093000. The fault IS taken at EL2; see runs/06.

# Run 04 — working UART breadcrumb from modified hyp (2026-10-07)

**Result: a modified hyp prints to the hardware debug UART from EL2, at QHEE entry,
and the phone still boots normally.** This gives the out-of-band channel run 03 needed
(it survives the EL2-fault reset-to-EDL, unlike the DDR breadcrumb).

```
B - 1170559 - QHEE Image Load, Start     <- XBL loads our hyp_b
B - 1238269 - SBL1, End                  <- XBL hands off
HYP3                                      <- OUR hyp, printed from EL2 on uart12
UEFI Start [ 1458]                        <- normal boot continues; Android boots (slot _b)
```

## What made it work (three bugs, found in order)

1. **Per-CPU entry → must be one-shot.** QHEE's entry (`0x80040000`, hooked at the
   `nop` `0x80040040`) runs on *every* CPU power-on, not just cold boot. A plain marker
   hung SMP bring-up (secondary CPUs poking the UART). Fix: a one-shot flag byte in the
   hyp image (DDR; MMU off ⇒ Device/uncached ⇒ visible to all CPUs) so only the first
   cold-boot CPU0 touches the UART. Proven the hook runs on cold CPU0 via a delay-test
   variant (a ~10s busy-wait at entry shifted `UEFI Start` from `[1238]` to `[69402]`).

2. **The GENI TX needs a full reset first.** Mirroring the kernel's `poll_put_char` is
   not enough: XBL leaves a TX command state that makes a fresh `UART_START_TX` never
   complete. Must run the cancel→abort sequence (`M_GENI_CMD_CANCEL`/`ABORT` to
   `SE_GENI_M_CMD_CTRL_REG`), then re-assert FIFO mode + TX packing, before transmitting.

3. **THE blocker: a base-encoding bug.** The stub loaded the UART base as
   `movz x9, #0xa900, lsl #16` = **`0xA9000000`** — 256× too high, a bogus address, not
   the UART. Correct is `0x00A90000` = `movz x9, #0xa9, lsl #16`. Every earlier silent
   attempt (and v1's secondary-CPU hang = bad-address abort) was this. The builder now
   computes the base load from `--base` (`hi=base>>16`, `movk` the low half), so it can't
   recur.

## Confirmed facts

- **uart12 @ `0x00A90000` (QUPV3 WRAP1_S4) is XBL's debug console** and is clocked at QHEE
  entry (XBL logs over it right up to `SBL1, End`). It is the `se12_2uart` Moto's ABL
  references. (`0x988000`/uart2 is *not* in Moto's abl-sink; a write there just stalls
  ~45s — not the console. `0x998000`/uart6 = Moto `se6_4uart`, untested, not needed.)
- A diagnostic that reads a clocked SE register and scales the cold-boot busy-delay by the
  value (`UEFI Start` timestamp = readout) is a safe way to probe hyp state with no working
  UART and no bus-hang risk — `el2-debug/build_uart_marker.py --mode {delay,probe,readproto}`.

## The working breadcrumb (minimal GENI poll-TX from EL2, MMU off)

base `x9 = 0x00A90000`. For each byte (TX_TRANS_LEN=1, packing 8bpw/4x8):
```
reset:   M_CMD_CTRL=CANCEL; poll M_IRQ[CANCEL_EN] else ABORT+poll; clear
config:  DMA_MODE_EN&=~1 (FIFO); BYTE_GRAN=0; TX_PACKING_CFG0=0x4380e CFG1=0xc3e0e
send:    clear M_CMD_DONE; TX_TRANS_LEN=1; M_CMD0=UART_START_TX<<27; TX_FIFOn=ch; poll M_CMD_DONE
```
Offsets (SE base): STATUS 0x40, FW_REVISION_RO 0x68, BYTE_GRAN 0x254, DMA_MODE_EN 0x258,
PACKING_CFG0/1 0x260/0x264, TX_TRANS_LEN 0x270, M_CMD0 0x600, M_CMD_CTRL 0x604,
M_IRQ_STATUS 0x610 (DONE b0, CANCEL_EN b4, ABORT_EN b5), M_IRQ_CLEAR 0x618, TX_FIFOn 0x700.

## Build / flash / watch

```sh
python3 el2-debug/build_uart_marker.py --mode uart --base 0xa90000 --out el2-debug/hyp_b_marker.img
# slot B is the rooted experiment slot; keep A stock. Set B active each time (A/B
# rollback flips to A after watchdog-tripping boots, e.g. the long delay-test).
fastboot set_active b && fastboot flash hyp_b el2-debug/hyp_b_marker.img && fastboot reboot
# watch el2-debug/uart/monitor.py (GUI) or live.log for HYP3 between SBL1,End and UEFI Start
```
Final marker image sha256 `28207b31…`. Recovery unchanged (`unbrick/edl_usb.py`); a
non-faulting marker boots, so no EDL needed for these.

## Next (the actual goal)

Now we can SEE EL2 state at the QHEE→HLOS handoff. Next: extend the stub to dump the EL2
fault registers (ESR/ELR/FAR_EL2) over this UART when the SPSR-EL2h candidate faults —
the capture run 03 couldn't exfil because reset-to-EDL wiped DDR. UART survives that.
