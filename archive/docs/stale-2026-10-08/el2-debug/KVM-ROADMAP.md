# KVM on nio (SM8250) — milestone roadmap

Target architecture (decided from runs 01–08 + prior-art survey):

```
XBL → QHEE(stock, all its init) → OUR SHIM (eret HLOS→EL2, identity-mapped)
      → EL2-native loader (edk2-msm / u-boot-qcom, flashed to abl)  → Linux kernel @ EL2 → KVM
```

Rationale: QHEE owns EL2 and runs the HLOS as an EL1 stage-2 guest (run 05/07), so KVM
requires displacing QHEE's *demotion*, which our C shim already does mechanically (run 08:
HLOS reaches `UEFI Start` at EL2). Stock Moto ABL is EL1-built and face-plants at EL2, so
we replace it with a loader that *expects* EL2 (the Renegade/edk2 or Linaro u-boot stacks
run at EL2 on hypervisor-less Qualcomm by default). Secure boot is off on this unit, so
flashing custom hyp/abl is viable; every failure is EDL-recoverable.

Validation loop for every milestone: build → flash slot B via fastboot (or EDL) → observe
on the UART probe (`el2-debug/uart/monitor.py`) → recover via `unbrick/edl_usb.py`. Slot A
stays untouched stock. Use `run_in_background cat >> live.log` for one-shot captures.

---

## M0 — Infra baseline  ✅ (done this session)
Probe GUI that never blocks the port; build/flash/EDL-recover loop; on-device EL2 inspection
(`--mode handoffdump/faultdump/ptdump`) and the C shim path (`--mode shim`). QHEE's EL2 model
fully mapped (TTBR0_EL2=0xbb800000, VTTBR=0xbb808000, VBAR=0x80093000).
**Exit:** reproducible flash→observe→recover. ✔

## M1 — Shim lands the HLOS at EL2 with usable memory  ✅ (done, runs 08–10)
Achieved: the C shim (`el2-debug/shim/`, `--mode shim`) builds its own EL2 identity map (64×1GB
blocks: 0-2GB Device, 2GB+ Normal RWX), repoints TTBR0_EL2, flips SPSR→EL2h. Stock UEFI then runs
a large chunk of DXE **at EL2** with Normal memory (no alignment/translation fault). It dies only
because **stock UEFI self-demotes to EL1** (`mrs scr_el3` @0x9fc02068, undefined at EL2) — proving
stock UEFI can't yield EL2. ⇒ proceed to M3 (replace the loader); M1 shim is the EL2 entry under it.

### (historical) M1 — Shim lands the HLOS at EL2 with usable memory
Make a payload run at EL2 past the point stock ABL currently dies (`UEFI Start`+reset, run 08).
- **M1a — Confirm the fault.** Shim + patch real EL2 vectors (VBAR_EL2=0x80093000) to dump
  ESR/ELR/FAR of the post-`UEFI Start` fault. Expect EC 0x25 + alignment IFSC ⇒ MMU-off/Device
  memory is the cause.
- **M1b — Identity map instead of MMU-off.** In the shim, keep `SCTLR_EL2.M=1` and instead add
  identity 2 MB block entries to QHEE's EL2 stage-1 L2 (`0xbb801000`) covering the 2–3 GB window
  (and peripherals/other GBs as faults dictate), so EL2 runs with Normal cacheable memory.
  (We can read/write those tables from the shim; run 07.)
**Exit:** an EL2 payload executes arbitrary C with Normal memory (proven by M2), i.e. the
alignment/Device-memory class of fault is gone.

## M2 — Minimal "hello at EL2" payload (de-risk the handoff, no ABL/loader yet)
Before any big loader, prove *our* control at EL2: shim erets to a tiny payload (ours, placed
in RAM/a cave or as a stub HLOS) that confirms `CurrentEL==2` and prints it over UART, then
parks (WFI / PSCI-off secondaries). Isolates "shim + identity map + EL2 execution" from
loader complexity.
**Exit:** UART shows our code running at `CurrentEL=2` with a working stack and Normal memory.

## M3 — EL2-native loader on the `abl` path
Replace stock ABL with a loader that expects EL2.
- **M3a — Pick/port.** Start from Linaro **u-boot-qcom** (cleaner) or **edk2-msm** (Renegade);
  add an SM8250/nio target (close to existing SM8250 boards). Confirm the abl partition is not
  signature-enforced here (hyp wasn't).
- **M3b — Chainload.** Flash it to `abl_b`; XBL loads it as APPSBL; QHEE erets to its entry;
  our shim flips that to EL2+identity-map. Get the loader to its console/prompt at EL2.
- **M3c — Peripherals under the loader at EL2.** UFS/eMMC storage, USB (so we can load images),
  console. These are the real risks: SMMU/DMA with QHEE's stage-2 setup vs loader-at-EL2.
**Exit:** loader reaches an interactive prompt at EL2 and can read the boot image from storage.
**Fallback:** if a full loader at EL2 is too heavy, write a minimal EL2 kernel-launcher (load
boot.img from a partition we specify, set up DT, jump to kernel) — we already boot RAM kernels.

## M4 — Linux kernel entered at EL2
- Loader launches our 6.18 kernel; add early-boot instrumentation (print `CurrentEL` in
  `head.S`/`init_el2`) to confirm entry EL == 2. Ensure the loader doesn't demote to EL1.
- Clear SMP/PSCI: secondary CPUs must also come up at EL2 (the shim already flips EL1h
  handoffs; verify secondaries route through it or are handled by the kernel's EL2 path).
**Exit:** kernel boots to userspace/adb with `CurrentEL==2` on the boot CPU (and all CPUs).

## M5 — KVM functional
- `CONFIG_KVM=y` (verify in the 6.18 config); confirm **VHE** engaged (A76 supports it) and
  `/dev/kvm` present.
- Smoke test: run a trivial guest (kvmtool/`lkvm run` or qemu-kvm with a tiny kernel) to prove
  vCPU entry/exit, stage-2 for the guest, GICv3 vGIC, and the arch timer work.
**Exit:** a guest VM executes under KVM on the nio.

---

## Cross-cutting (tracked across M1–M5)
- **SMMU / DMA (UFS):** QHEE configured stage-2 SMMU contexts (VMID 3, identity). With the HLOS
  at EL2 (not a guest), verify device DMA still lands; if not, set the relevant SMMU contexts to
  bypass/identity in the shim. Storage DMA is the single most likely boot-blocker.
- **TZ / SMC:** QHEE mediated EL1→EL3 SMCs (HCR_EL2.TSC). At EL2 the chain calls EL3 directly;
  confirm PSCI (CPU_ON/OFF), RPMB/crypto, and any boot-critical SMCs still work. Map QHEE's
  EL2↔EL3 SMC interface offline (emulator is still fine for static RE).
- **Recovery discipline:** slot A untouched stock; only ever flash slot B hyp/abl; EDL restore
  proven. A bad `abl` loses fastboot but EDL still recovers.
- **Decision point after M1/M2:** if the identity-map shim gets *stock* ABL all the way to the
  kernel at EL2 "for free," M3 (custom loader) may be unnecessary — test stock once with the
  identity map before committing to the loader port.

## Prior art to lean on
- Renegade / **edk2-msm**, **edk2-sdm845** — custom EDK2 UEFI replacing abl (they boot at **EL1**;
  we add the EL2 piece they lack). Linaro **u-boot-qcom**. TravMurav/**slbounce** (EL/TZ boundary).
  These give the loader to put *after* the shim; none of them solve EL2/KVM alone.
