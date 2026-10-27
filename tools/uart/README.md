# HW UART on the nio (XT2125-4 / SM8250) — what we know

Confirmed working 2026-10-07. The hardware serial console is reachable and already
carries the Qualcomm boot log before our hyp runs, so it is a live out-of-band channel
that survives the reset-to-EDL which erased the DDR breadcrumb in `../runs/03`.

## The port

| Property | Value |
|----------|-------|
| SoC block | QUPv3 wrap1 S4, GENI "debug UART" — `uart12: serial@a90000` (mainline `qcom,geni-debug-uart`) |
| MMIO base | `0x00a90000`, size `0x4000` |
| Clock | `GCC_QUPV3_WRAP1_S4_CLK`; IRQ `GIC_SPI 357` |
| Android-side device | `a90000.qcom,qup_uart` (seen in `/sys/.../devices`); `msm_geni_serial` |
| DTS alias | `serial0 = &uart12`, `stdout-path = "serial0:115200n8"` (our `sm8250-motorola-nio.dts`) |
| Line settings | **115200 8N1**, no flow control |

## Host side

| Property | Value |
|----------|-------|
| Adapter | FTDI FT232 (`0403:6001`), enumerates as `/dev/ttyUSB0` |
| stty | `stty -F /dev/ttyUSB0 115200 raw -echo cs8 -cstopb -parenb -crtscts clocal` |
| Backup capture | Saleae Logic Pro 8 (`21a9:1005`) also on the bench |

Note: `/dev/ttyUSB0` is shared with the EDL/qcserial path (the 9008 QDLoader also binds
ttyUSB0). They are not used at the same time — EDL only appears after a brick/force-EDL.

## What the UART actually shows (proven)

A full normal boot was captured to `stock-boot-115200.bin`
(26537 bytes, sha256 `2e4ab09f763f24bae9d6c184c7176580163b94313b18aa2980194b012fe20548`,
one `adb reboot`). The Qualcomm XBL/UEFI log comes out in the clear:

```
Format: Log Type - Time(microsec) - Message - Optional Info
S - QC_IMAGE_VERSION_STRING=BOOT.XF.3.2-00354-SM8250-1
S - Secure Boot: Off
S -     65473 - PBL, End
B -     79361 - SBL1, Start
B -    950959 - QHEE Image Load, Start
D -     13085 - QHEE Image Loaded, Delta - (444216 Bytes)   <- our hyp partition
B -    972614 - OEM_HYP Image Load, Start
B -    981551 - APPSBL Image Load, Start                     <- ABL/fastboot
B -   1018791 - SBL1, End
UEFI Start     [ 1238]  (UEFI Ver 5.0.220503.BOOT.XF.3.2-00354-SM8250-1)
...
Exit EBS        [13461] UEFI End                             <- handoff out of UEFI
```

Key facts this establishes:

- **The UART is configured and clocked by PBL/SBL1, long before QHEE (hyp) is loaded.**
  "QHEE Image Load" is logged over this same port, i.e. the serial block is already up
  when our modified partition is read in. A consumer at/after the hyp stage does not need
  to bring the UART up — only to use it (if the firmware leaves it configured).
- **`Secure Boot: Off`** on the UART log independently corroborates the engineering-unit
  finding in `kernel/EL2-hypb-nonboot-cause.md` (`secure=no`).
- The XBL log is the Qualcomm "Sahara/boot" format (`B/D/S` lines, microsecond timestamps);
  UEFI/ABL switches to `[ms]`-bracketed lines.

## Reach vs. the EL2 problem (why this matters, and the open question)

- The EL2 hyp fault happens at the QHEE→HLOS handoff, i.e. **after** "QHEE Image Load" and
  around/after the ABL (APPSBL) stage. The UART is demonstrably alive through that whole
  window on a *stock* boot.
- Unlike the DDR/crashdump breadcrumb (`../runs/03`), serial output leaves the phone as it
  is emitted, so it is not lost by the fault's reset-to-EDL.
- **Open / unproven:** whether the firmware leaves UART12 configured at the exact moment
  QHEE runs its handoff (the stock log proves the stage is reached, not the register state
  at the instant of the eret). That is the one thing an instrumented boot would confirm.

## Printing to this UART from modified hyp (WORKS — run 04, 2026-10-07)

A modified `hyp_b` prints to this UART from **EL2 at QHEE entry** (between `SBL1, End`
and `UEFI Start`) and still boots. Build with
`motorola_nio/archive/el2-debug/build_uart_marker.py --mode uart --base 0xa90000`. Three things were required:
1. **Correct base**: `0x00A90000` (`movz x9,#0xa9,lsl#16`) — NOT `0xa900<<16`=`0xA9000000`.
2. **One-shot guard**: QHEE entry runs on every CPU power-on; only cold-boot CPU0 may
   touch the UART (its clock is gated at runtime → a secondary CPU would hang the bus).
3. **GENI reset before TX**: cancel→abort the SE, re-assert FIFO mode + TX packing, then
   `UART_START_TX`. See `motorola_nio/archive/el2-debug/runs/04-uart-breadcrumb-working.md` for the full recipe,
   register offsets, and the `--mode delay|probe|readproto` safe-diagnostic technique.

## Reproduce a capture

```sh
stty -F /dev/ttyUSB0 115200 raw -echo cs8 -cstopb -parenb -crtscts clocal
cat /dev/ttyUSB0 > capture.bin &   # or: timeout 75 cat ...
adb reboot                         # or power-cycle
strings -n4 capture.bin | less
```
