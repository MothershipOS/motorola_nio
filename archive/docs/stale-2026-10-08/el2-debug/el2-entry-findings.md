> **CORRECTION (2026-10-07, run 05 — measured on real hardware via UART handoff dump):**
> At the QHEE→HLOS handoff `SCTLR_EL2 = 0x3048180f` → **EL2 MMU is ON** (M=1,C=1,I=1), and
> `HCR_EL2 = 0x80080005` → **VM=1 (stage-2 ON)**, RW=1, TSC=1. The "MMU OFF (M=0)" conclusion
> below is an OFFLINE-MODEL ARTIFACT and is WRONG on-device. `ELR_EL2=0xa16cd1dc` (ABL entry),
> `SPSR_EL2=0x85` (EL1h). QHEE runs the HLOS as a stage-2 guest; the EL2h-flip abort goes to
> EL3 (run 04). See `el2-debug/runs/05-handoff-state-dump.md`.

# The QHEE→HLOS handoff and what a valid EL2 entry actually requires (2026-10-07)

Disassembled the real cold-handoff in stock QHEE (`backups/.../hyp_b.img`, entry 0x80040000).
This corrects earlier assumptions.

## The handoff (stock)

Early EL2 setup (0x80040000–0x80040130):
- `vbar_el2 = 0x80040330` (QHEE's EL2 vectors), `mair_el2`, stack `sp = [0x80040338]=0x801f7000` minus per-CPU offset.
- `ldr x4,[0x800a6418]` → **0** → `cbz` **skips** `ttbr0_el2`/`tcr_el2` and skips `orr x5,#4(C)`/`orr x5,#1(M)`.
- `sctlr_el2 = x5 = 0x8100A` → **M=0, C=0**, I=1(bit12), WXN=1(bit19), SA, A.
  **⇒ QHEE executes at EL2 with the MMU OFF (flat physical), data cache off, I-cache on.**
- `hcr_el2=0`, `sctlr_el1=0`, `cptr_el2=0x33ff`, `cnthctl_el2=3`, GICv3 `icc_sre_el2=9`.

Handoff tail:
- `msr elr_el2, x21` (0x800401bc) → **x21 = HLOS/ABL entry (a physical address)**.
- dispatch on `x22`: ==2 → `x5=0x85` (SPSR EL1h) at **0x800401d8**; ==1 → EL1 variant (0x93/0xb3).
- `hcr_el2 |= 0x80080000` (RW=EL1-is-AArch64, TSC).
- `msr spsr_el2, x5` (0x80040210).
- `0x800402b0..0x80040324`: **zero x1–x30** (x0 keeps the boot arg from the stack). This is GPR
  sanitisation, **not** MMU/cache teardown (earlier notes mislabelled it).
- `eret` (0x80040328) → HLOS at **EL1h**, MMU off, PC=x21(PA), x0=boot arg.

## Consequences for the experiments (both bisect failures explained)

- **SPSR-only (0x85→0x3c9) faults** — but NOT because of translation. MMU is already off, so
  PC=x21(PA) is fetchable at EL2 just as at EL1. The HLOS target *starts executing at EL2* and
  faults for **EL2-vs-EL1 execution** reasons (candidates: it takes an exception into QHEE's
  `vbar_el2`; it reads `CurrentEL`/does EL1-assuming setup; SP_EL2 vs SP_EL1 selection; a trap via
  `cptr_el2`/`cnthctl`/`hstr`). Exact cause unconfirmed — no fault registers captured yet.
- **teardown-only faults too** — the candidate replaced the GPR-zeroing block with a
  "mask + clear SCTLR_EL2.M/C/I" sequence. But M/C are **already 0**, so that sequence is both
  unnecessary and, as written, broke even the EL1 path (buggy/clobbering replacement, and any
  cache toggling here is a hardware coherency hazard TCG doesn't model). i.e. it damaged a
  load-bearing block for no benefit.

## So the earlier model was wrong twice
1. EL2 MMU is **off**, not on — there is no "QHEE EL2 map that fails to cover the target".
2. No MMU/cache teardown is needed before the eret; the only required change to land the HLOS
   target at EL2 is the SPSR EL1h→EL2h flip. It still faults, so the problem is the **EL2
   execution contract of the target**, not the mapping.

## What a valid EL2 entry requires (revised)

Flipping SPSR is necessary but not sufficient. The HLOS target was written to run at EL1; at EL2
it must not trap/except before it establishes its own environment. To make progress we must first
**see the actual fault**, then satisfy it. Concretely:

1. **Capture the EL2 fault** (next experiment): QHEE's `vbar_el2 = 0x80040330` and the MMU is off,
   so a tiny patch to the EL2 sync-exception vector can store `ESR_EL2`/`ELR_EL2`/`FAR_EL2`/`SPSR`
   to a fixed **physical** scratch address (DDR we can read back from Linux, or the `ramdump`
   partition's DDR window). Flash the SPSR-only variant, boot, fault → vector logs regs → recover →
   read them. This gives the exact fault class and faulting PC inside the target.
2. **Satisfy the contract** per the captured fault, e.g.: set/adjust `cptr_el2`/`cnthctl_el2`/
   `hstr_el2` so the target's early instructions don't trap to EL2; ensure a valid `SP_EL2`;
   point `vbar_el2` at a handler that can continue; and decide whether the *target itself* needs
   patching (ABL assumes EL1) or whether EL2 must be handed off further down the chain.
3. **Bigger picture:** the KVM goal needs **Linux** at EL2, not ABL. ABL→Linux is a longer chain;
   making ABL run at EL2 is only the first hop. The real entry contract to design is the final
   kernel handoff, which the offline harness (`tools/hyp_re/run_qemu.py`,
   `trace_bridge_handoff.py`) models — validate any construction there before flashing.

## Device/loop notes
- Iteration is cheap now: flash variant → boot → fault → (auto-EDL or crashdump→fastboot) →
  firehose/fastboot restore → read scratch. Slot B is a rooted clone for experiments; A is the
  untouched fallback. Build variants with `el2-debug/build_bisect.py` (extend it for new patches).
- `fh.py read_sectors` raw-mode framing bug still open (needed if reading DDR scratch via EDL
  instead of via Linux root).
