# Run 03 — vector-breadcrumb attempt + EDL robustness (2026-10-07)

## Breadcrumb experiment outcome
Built a flash-ready candidate = SPSR-flip + an EL2 **sync-vector** handler (overwriting
VBAR_EL2+0x200 = 0x80093200) that stores ESR_EL2/ELR_EL2/FAR_EL2/SPSR/SCTLR_EL2/CurrentEL
to DDR scratch 0x90000000, then chains to QHEE's real handler (0x8004126c). Handler
assembled with aarch64-linux-gnu-as; candidate built with el2-debug/build_bisect-style surgery.

v1 (handler SPIN) → hung at EL2, suppressed the crashdump (no exfil).
v2 (handler CHAIN to QHEE) flashed+booted → target faulted at EL2 → **device reset to EDL
(mode 0), NOT a storage crashdump**. So DDR 0x90000000 is NOT captured anywhere readable:
the EL2-target-fault recovery path on this device is a reset-to-EDL that does not dump DDR.

**Conclusion: DDR + crashdump exfil does not work for this fault.** The handler runs, but the
registers can't be recovered. Next exfil must survive a reset-to-EDL:
  - UART out from the handler (write regs to the debug UART MMIO; capture with the Saleae), or
  - write the breadcrumb into a flash partition the firehose can then read (needs a storage
    path from EL2 — hard), or
  - find whether a *different* fault class (e.g., forcing the teardown-style QHEE-internal
    fault) yields a storage crashdump that DOES capture DDR.

## EDL robustness learnings (important for the whole loop)
- The qcserial /dev/ttyUSB path races the PBL's one-shot Sahara HELLO; unreliable.
- **Raw libusb (pyusb) is the reliable transport** → `unbrick/edl_usb.py`. BUT:
  - On a *running firehose*, DO NOT call `set_configuration()` — it disconnects it (errno 19).
    Attach = get_active_configuration + claim_interface only.
  - After Sahara DONE_RESP, **fully drain the firehose hello burst** (read until ~2s silence)
    before the first command, or writes time out (errno 110) because the firehose is blocked
    sending.
  - Endpoints: OUT 0x01, IN 0x81, mps 512.
- A **wedged "zombie" EDL** (writes return errno 110, no HELLO) only clears with a real SoC
  reset. The PBL emits HELLO **once per boot**; USB reset/replug does NOT re-trigger it.
  Force reset from EDL = **Power + Vol-Down held ~15-20s** (PMIC reset; Power alone is ignored
  in EDL). The device then reboots, faults into a *fresh* EDL with a clean HELLO (maxlen=0x400).
- USB link quality matters: a flaky cable/hub gave truncated HELLOs (maxlen=0); a good cable
  on a rear port fixed it.

Recovery used: `unbrick/edl_usb.py` (raw-USB) to load the firehose + restore stock hyp_b.
Final state: slot A, both hyp stock, rooted, normal boot.
