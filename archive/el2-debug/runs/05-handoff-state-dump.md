# Run 05 — EL2 handoff-state dump over UART (2026-10-07)

Captured the QHEE→HLOS handoff state live over the hardware UART, from a modified hyp that
hooks the instruction just before the `eret` (`0x80040324`, the last `mov x30,xzr`), prints,
then continues — **no SPSR flip, boots normally**. Build:
`el2-debug/build_uart_marker.py --mode handoffdump`. Raw capture: `uart/handoff-dump-20261007.txt`.

```
== HANDOFF ==
ELR_EL2 =0x00000000a16cd1dc     <- ABL/HLOS entry
SPSR_EL2=0x0000000000000085     <- EL1h (normal), I masked
HCR_EL2 =0x0000000080080005     <- RW=1, VM=1 (stage-2 ON), TSC=1, PTW  (varies 0x…5/0x…7)
SCTLR_E2=0x000000003048180f     <- M=1,C=1,I=1,SA,WXN : EL2 MMU IS ON
TGT[0..8]=97ffff8b 97ffffe8 14000001 9400002b 940000b7 94000012 58000ee8 d61f0100
== END ==
```

ABL entry disassembly (`0xa16cd1dc`): `bl;bl;b;bl;bl;bl; ldr x8,[lit]; br x8` — a normal
bl-chain + trampoline.

## Why this matters — two corrections to the prior model

1. **EL2 MMU is ON at the handoff** (`SCTLR_EL2.M=1`, `0x3048180f`). `EL2-entry-findings.md`
   concluded M=0 / MMU-off from the offline emulation (TTBR0_EL2 literal = 0). On the real
   device it is ON. The offline model was wrong here.
2. **QHEE runs the HLOS as a stage-2 VM guest** (`HCR_EL2.VM=1`, `RW=1`, `TSC=1`). QHEE is a
   true type-1 hypervisor holding EL2; the HLOS (ABL→UEFI→Linux) is its EL1/EL0 guest under
   stage-2 translation.

## Why the SPSR→EL2h flip faults to EL3 (run 04), explained

With EL2 stage-1 MMU on and the guest running under stage-2, `ELR_EL2=0xa16cd1dc` is a guest
address, not something mapped executable in QHEE's EL2 stage-1. Eret-ing to EL2h makes the core
fetch that address at EL2 (QHEE's stage-1, no stage-2) → instruction abort, routed to **EL3**
(secure monitor), which resets — never reaching QHEE's EL2 vectors (run 04 patched all 12; none
fired). So instrumenting QHEE's EL2 vectors can't capture this fault, and making *ABL* run at
EL2 is a dead end regardless: ABL is a guest.

## Implication for KVM

KVM needs **Linux** at EL2. Here EL2 is permanently owned by QHEE, with the whole HLOS as a
stage-2 guest. The route is not "flip the ABL handoff" but to displace/stub QHEE as the EL2
owner so TZ hands EL2 to Linux — which earlier notes flag as XBL/TZ-rejected (hard brick). The
handoff-dump channel is now the tool to study QHEE's own EL2 setup (TTBR0_EL2, VTTBR_EL2,
VTCR_EL2, the stage-1/stage-2 tables) by extending the dumper to print those regs.

## Tooling / method notes

- `--mode handoffdump` is non-destructive (no flip); prints several times per cold boot (QHEE's
  handoff path runs more than once) — all identical target. No one-shot needed; the path is not
  hit on secondary-CPU runtime resume, so the runtime-gated-UART hang does not occur.
- **FT232 wedging**: heavy USB cycling left the FT232 in an I/O-error state (`OSError: [Errno 5]`
  on open, stale node) — captures silently died. Clear it without root via a USBDEVFS_RESET
  ioctl on `/dev/bus/usb/<bus>/<dev>` (pyusb/raw); physical replug also works. This was the cause
  of several "no output / phone looks dark" dead ends in runs 04–05.
- Backgrounded shell `cat` captures die when the tool call returns; only a run_in_background
  process or the GUI (`el2-debug/uart/monitor.py`) persists as the single reader.
