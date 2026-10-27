# nio: shortest path to a working KVM guest

## Hardware experiment update — 2026-10-06

The user explicitly authorized creating and flashing EL2 firmware. A complete
pinned QHEE container with the masked EL2/XBL transition and repaired code hash
was built, checked and flashed to **inactive hyp_b**. Slot A remains selected. Rooted Android readback verified the exact candidate in B and the unchanged original in A.
Four candidate-packaging checks and nine bounded XBL startup checks passed.
The old statements that no early-firmware flash was authorized are superseded.

The next meaningful gate is **boot authentication and actual EL2 retention**,
not more unrelated peripheral tracing. The preserved OEM signature is stale;
fastboot write success does not prove boot acceptance. Before selecting B for
a boot trial, resolve independent recovery and define the observable result
and restoration sequence. Pre-ABL failure can remove fastboot. No candidate
boot or physical KVM success is claimed by inactive-slot staging.

See `reports/nio-el2-firmware-20261006/README.md` for the exact bytes, backup,
flash result and verification. Full system and KVM acceptance criteria below
remain unchanged.

Updated 2026-10-06. Immediate goal: the physical phone runs Linux at EL2 and
executes a tiny AArch64 guest on one KVM vCPU, with a checked result returned
to userspace. Android, Ubuntu, CPU pooling and device sharing follow this gate.

## Where we are

| Gate | Status | Evidence / remaining work |
| --- | --- | --- |
| Boot our Linux reliably | Done, CPU0 | Linux 6.18.54 diagnostic RAM boot; USB shell and ramoops work |
| Establish why KVM is absent | Done | Linux starts at EL1; QHEE owns EL2; KVM reports HYP unavailable |
| Reproduce observed CPU0 cold path offline | Done under explicit assumptions | Finite MMIO/SCM models cover the observed cold path; real cold TZ replies and environment remain unverified |
| Reach the complete stock payload handoff offline | Done under explicit assumptions | Original cold path executes ERET at 0x80040328 and runs a semihosting RAM probe at EL1; no firmware code patch or page-table edit |
| Determine real payload and boot-chain entry contract | Partial static and bounded execution evidence | Full modeled QHEE now executes original SEC prefix at the configured 0x9fc00000 candidate and retains EL2 through vector/BSS/stack-query setup; its first SMC enters the modeled EL3 vector, while stock QHEE forwards the query unchanged. Original TZ query slices now derive an exact reply; both paths advance to the next eight-byte buffer SMC under an explicit synthetic return model. Original buffer/PRNG slices derive its success/count reply from finite FIFO fixtures, with ownership/setup/cache assumptions. Exact replay now lets original XBL return from stack sizing and adjust SP at both EL1 and EL2; original cache startup now completes at both levels. A separately guarded second fixture reply lets original XBL store its canary and enter SEC main; one measured postboot flag replay now exits SEC's hold loop and executes CNTVCT_EL0 and its fixed-frequency conversion, then reaches the platform-selection read at 0x01fc8004 with translation still off. Repeated postboot phone reads return zero; exact one-shot replay now lets original SEC select/store its descriptor and reach the QUP wrapper-version read at 0x00ac0004. That read faults in the model. Cold-entry/EL2 equality remains unverified. Cold flag state/publisher and actual Linux contract remain open. Isolated ABL launch also preserves EL2. Original TZ monitor restores/ERETs under synthetic records; its derived entry controls now pass the full QHEE and SEC-prefix matrix. Actual bootstrap/records and intervening stages remain unverified |
| Implement an EL2 handoff compatible with Linux | Diagnostic transition works offline; Linux contract open | Bounded terminal variants now mask DAIF before maintenance and run an EL2 probe with M/C/I off from TZ-derived entry controls; real target, cache behavior, DTB and firmware services remain unverified |
| Establish acceptance and recovery for changed early firmware | Open | Backup images exist; XBL acceptance and independent pre-ABL recovery are unverified |
| Execute a guest with KVM on the phone | Open | No /dev/kvm on the current EL1 boot |

The current milestone has 878 passing checks across 43 suites: the earlier
869 plus nine selector/descriptor/QUP-boundary tests. See [selector replay and QUP version boundary](EL2-XBL-selector.md),
[original counter and platform-selection boundary](EL2-XBL-counter.md),
[SEC hold flag and virtual-counter boundary](EL2-XBL-readiness.md),
[original canary store and SEC readiness boundary](EL2-XBL-canary-return.md),
[original SEC cache startup and canary request](EL2-XBL-cache-startup.md),
[original XBL stack-sizing return](EL2-XBL-stack-return.md),
[TZ buffer validation, FIFO and reply contract](EL2-TZ-buffer-contract.md),
[TZ query reply and next buffer request](EL2-TZ-query-reply.md),
[XBL query and QHEE forwarding](EL2-XBL-stack-SMC.md),
[original SEC workspace and stack](EL2-XBL-startup.md),
[TZ entry controls through full QHEE](EL2-TZ-entry-state.md),
[original TZ restore and ERET](EL2-TZ-monitor-restore.md),
[TZ records and argument frame](EL2-TZ-handoff.md),
[original SEC after cold QHEE](EL2-XBL-prefix.md),
[the original ABL boundary and XBL candidate](EL2-ABL-boundary.md),
[the executable EL2 diagnostic](EL2-diagnostic-transition.md),
[full cold-handoff evidence](EL2-bridge-handoff-model.md) and
[the SPSR-only control and static boot-chain inventory](EL2-entry-contract.md).
These are offline results; physical EL2 handoff and KVM execution remain open.

## Scope before a firmware test on the phone

We need a narrow CPU0 boot-chain experiment, not a complete SM8250 model or
finished Linux device support. GPU, multicore guests, Ubuntu/Android and device
sharing are outside the first firmware-test scope.

Three substantial work packages remain for a useful EL2-transition test:

1. **Establish the real entry contract.** The observed original CPU0 cold path
   now reaches its synthetic payload at EL1 under the documented models.
   Stop adding unrelated device models. Original SEC now retains EL2 through
   vector/BSS/temporary-stack setup, but rewrites HCR_EL2 to 0x10. Original TZ slices now
   select QHEE and prepare the candidate target/width/cold arguments from
   synthetic records. The original monitor restores and ERETs under those inputs.
   Its derived SPSR/SCR/SCTLR controls now pass the full QHEE and SEC-prefix
   matrix with both HCR and GCC inputs. The bounded terminal explicitly masks
   DAIF before cache/MMU teardown. Original SEC now overwrites sentinel-filled
   vectors/BSS and establishes its stack. Its dispatcher now reaches the
   0x02000601 query; the EL2 SMC enters the synthetic EL3 vector, and the
   original stock QHEE handler forwards the query unchanged. Original TZ argument,
   registry and marshaller slices derive status/availability zero without
   dereferencing inherited x6. An exact one-shot synthetic reply advances both
   paths to the eight-byte `0x02000a01` buffer call. Original buffer slices
   now reach both pointer-check boundaries and the selected PRNG backend. A
   finite FIFO fixture yields eight bytes and a successful count reply under
   explicit ownership/setup/cache assumptions. An exact one-shot offline reply
   now lets original XBL return from stack sizing and adjust SP to `0x9ffcfd00`,
   stopping before the next helper at `0x9fc0cf38`. The stock buffer forwarding
   call changes x7 to 3 at `0x80041aa0`; the model checks this distinct contract.
   Original helper `0x9fc17b90` now executes set/way invalidation; the next
   calls enable I/D at the existing EL while leaving translation off. The
   canary initializer reaches a second eight-byte SMC at `0x9fc28468`,
   SP=`0x9ffcfce0`. Stock QHEE clears
   inherited x6 and sets x7=3. A separately guarded second fixture reply now
   lets original XBL store the canary, unwind SP, and call SEC main with
   workspace base `0x9ff90000` and size `0x3fd00`. The trace stops before
   the first flag load `0x9fc0e37c` at `0x146bf944`. Two read-only postboot
   phone checks now capture `0x3a6506a5`; original SEC waits only while the
   word equals `0x55444247`. An exact one-read replay under an explicit
   postboot-to-entry equality assumption now exits that loop, executes the
   no-op hook, copies the canary into the platform frame and stops before
   `CNTVCT_EL0` at `0x9fc2bb48` in the earlier trace. The new trace executes
   that read, verifies the original fixed-19.2MHz conversion and result store,
   then passes the SIMD load and 40-byte descriptor copy. Its next dependency
   is uint32 `0x01fc8004` at PC `0x9fc2a150`; one instruction step aborts at
   the current EL. Two read-only phone checks return zero. Exact one-shot selector replay
   now selects descriptor `0x9fc356e0`, stores its pointer, matches ID `0x1c200`
   and reaches the QUP wrapper-version uint32 read at `0x00ac0004`. That
   access aborts at the current EL. Postboot wrapper AHB clocks are disabled;
   the serial driver has no runtime-PM resume path here. Next prepare a
   fixed version-read diagnostic using balanced clock-framework references,
   capture its value, then add only that exact replay. Entry/EL2 equality
   remains an assumption. QEMU advertises 62.5MHz, so
   converted counter values do not prove physical timing. The
   flag publisher, cold state, policy and monitor return remain unverified.
   Trace the bootstrap bridge from XBL
   0x82000114 to TZ pointers separately.
   Actual records and the intervening UEFI/ABL/Linux contract remain unknown.
2. **Produce and verify a minimal CPU0 candidate.** Select the transition point,
   preserve required firmware services and validate MMU/cache, interrupt/timer,
   reservation and entry-register behavior. The first hardware payload can
   be a small diagnostic; complete Linux/KVM guest execution can follow it.
3. **Establish firmware acceptance and independent recovery.** Determine
   embedded integrity/signature requirements and a restoration route that
   works without ABL/fastboot. Existing backups, slot B and engineering mode
   do not establish this. This work can progress alongside the offline trace.

A diagnostic firmware change can precede full Linux handoff if its concrete
purpose, bounded change, image acceptance and recovery are established. We
should not treat completion of the entire emulator as a universal prerequisite
for any firmware experiment. The present plan traces the CPU0 path to reduce
uncertainty in the intended EL2 change; acceptance/recovery remain separate
hardware-test gates. No early-firmware flash is authorized by model work.

There is no defensible completion percentage or calendar estimate yet: the
remaining boot-chain contract and recovery questions dominate uncertainty.
After handoff is reached, stop adding unrelated hardware models and focus on
the smallest recoverable experiment.

## Step 1 — observed cold path closed offline

Continue from the measured execution boundary. Implement only exact reads,
control transitions and call contracts reached on this path, with unknown
operations stopping. Keep measurements separate from model assumptions.

Firmware-derived SMMU counts, bounded context controls and the measured
command-database pointer resolve the modeled VMID-5 failure. The optional
exact ownership ledger now accepts the original QHEE requests for all eleven
captured SMEM regions. QHEE constructs the previously missing header/global
SMEM mappings itself. The ledger is bookkeeping, not TZ or DMA enforcement;
initial ownership and successful TZ replies remain explicit assumptions.

Both entries in the TZ-subsystem channel table now pass: `0x80dc1000`/4 KiB
for VMIDs 21/22 and `0x80ddc000`/8 KiB for VMIDs 21/42. Each has independent
reader/writer state; SMEM ownership remains intact. The exact command-database
transition at `0x80860000`/128 KiB and the VMID-4 log sharing transition also
pass. Measured TZ log pointer replay plus the exact early IMEM log publication
advance through both log mappings. Eight read-only checkpoints confirm the
path to PMIC initialization. The captured APID, owner and secondary mapping
tables replay read-only. The finite 241-request VMID2 mapping model now
completes PMIC initialization. With separately enabled PIL empty-list, ready
publication and late-PRNG experiments, sixteen checkpoints confirm main-init
return and reach SCM `0xc2000c1e` inside the next helper. Its exact one-shot
bridge model and bounded allocator PRNG reply now advance through the final
ERET. A RAM probe at `0x90000000` runs at EL1 under QHEE's original stage-2
permissions. Unknown requests remain terminal. See [the full trace](EL2-bridge-handoff-model.md).

This path still requires the explicit IsDeviceNonSecure unsupported-response
experiment. Capture that fixed query separately if safely exposed by the
diagnostic kernel; an EL1 reply would still not prove the EL2 reply. Raw SMMU
capabilities, real boot-time state and the physical handoff remain unverified.

Exit condition achieved offline: original QHEE reaches the synthetic payload
through its full initialization path, with assumptions listed. This does not
validate the real Motorola entry contract or Linux as that payload.

## Step 2 — establish the actual boot-chain contract

Trace XBL/TZ's incoming target/width/argument contract and the intermediate
UEFI/ABL path to Linux. Determine which components require QHEE services.
Record memory reservations, CPU MMU/cache state, exception routing, GIC/timer
state, stage-2 ownership and PSCI forwarding at the transition.

Static inventory now identifies the XBL volume branch and AArch64 SEC entry
at `0x9fc0cc50`; its startup has an EL2-specific MMU/cache and HCR path.
ABL's compressed `MotoBootModule` is also AArch64 despite its ELF32 wrapper.
These findings are candidates for contract tracing, not proof of the actual
QHEE incoming target or the complete firmware path retaining EL2.

XBL's pinned ten-row configuration table now supplies a stronger static
candidate: APPSBL's configured field is `0x9fc00000`, whose first branch
targets SEC. The earlier interface slot configures a descriptor. The separate later
SMC passes a 0xe00-byte buffer. Original TZ selectors and frame-building
instructions now prepare x0=0x9fc00000, x1=2 and x2=x3=0 from candidate
records, and a monitor slice copies them into the next context. The actual
records remain unverified. Original monitor restore/ERET now enters EL2
with SPSR=0x89, software SCR=0x505 and SCTLR_EL2=0 under those inputs;
HCR retains its supplied value. These controls now pass the full QHEE path
and the original SEC prefix under both HCR/GCC inputs. PSTATE remains 0x89
through cold initialization; the bounded terminal masks DAIF before maintenance.
The earlier 0x3c9 entry remains available as a control. See
[the complete entry-state variation](EL2-TZ-entry-state.md). Original SEC now
clears its BSS and establishes a temporary stack at EL2, with sentinel guards
checked through 0x9fc0cf28. Its stack-sizing dispatcher now reaches the first
SMC with all eight registers captured, and original QHEE forwarding preserves
the stock request. See [the service boundary](EL2-XBL-stack-SMC.md).

The original ABL preparation and final AArch64 launch blocks now pass isolated
EL1/EL2 and CPU MMU/cache on/off tests. They preserve EL2 and forward the
synthetic DTB pointer, but do not cover earlier UEFI modules, BootLinux's caller
or its optional hypervisor-service calls. Preparation preserves the D mask
bit while masking A/I/F; Linux's full DAIF state still needs validation.

Choose the smallest supported route: an actual firmware EL2-release facility
if one can be established, otherwise a narrowly scoped early-boot transition.
Do not assume changing the QHEE SPSR constant is sufficient or that QHEE's
immediate payload is Linux. A replacement loader is an alternative to evaluate
against these contracts, not an already validated shortcut.

Exit condition: an explicit handoff contract, including what Linux receives
and which required firmware services remain available.

## Step 3 — build and validate the CPU0 EL2 transition offline

Use the pinned kernel's `Documentation/arch/arm64/booting.rst` as the contract.
Validate instruction execution and addresses across MMU changes, cache
cleaning/invalidation, exception masking/routing, HCR/SCTLR state, timer access,
DTB arguments and preserved firmware reservations. Test both relevant initial
MMU states. First run a small diagnostic payload, then the kernel entry path.

The SMMUs modeled here translate device DMA. KVM's guest stage-2 translation
uses the CPU MMU. Full device SMMU translation, GPU acceleration and device
passthrough are not prerequisites for a CPU-only KVM smoke test. Required
boot-chain hardware setup must still be preserved or explicitly replaced.

The complete-path SPSR-only experiment now fails on its first EL2 fetch at
`0x90000000`: EL2 stage-1 descriptor `0x50000090000705` denies execution,
while SCTLR_EL2 remains `0x8100f`. The new 124-byte terminal replacement
cleans the bounded diagnostic ranges and clears M/C/I in identity-mapped
executable code. Both GCC input states now run the probe at EL2. The tracer
audits 588 page mappings and the fetch across the MMU change without edits.
Physical cache behavior and the real firmware-to-Linux contract are still
open; establish them before treating this as a Linux handoff. Do not treat
the synthetic SEC address as the real target.

Exit condition: a reviewed transition that meets the Linux boot contract;
not merely an EL2 CurrentEL reading in a synthetic probe.

## Step 4 — establish a recoverable hardware test

Before changing early firmware, establish image integrity/authentication
requirements and a compatible recovery route that works when ABL/fastboot
does not start. Inspect any recovery package's exact operations before use.
Stock slot B and the bootloader's engineering status are not proof of either.

Prefer a temporary boot route if the established firmware contract allows it.
Ordinary `fastboot boot` currently runs after QHEE has already retained EL2;
it cannot by itself replace that earlier handoff.

Exit condition: a concrete candidate, a verified restoration method, and
explicit authorization for any necessary early-firmware partition change.
Current work remains offline modeling and diagnostic reads; no hyp/XBL flash.

## Step 5 — prove KVM on the physical phone

1. Boot Linux at EL2 with CPU0, initramfs, console, timer and watchdog working.
2. Confirm KVM initialization and the expected API via /dev/kvm.
3. Create one VM/vCPU, map a small guest RAM region and initialize AArch64
   registers. Execute a tiny instruction sequence through KVM_RUN and check
   its computed result plus an expected userspace MMIO exit.
4. Add guest timer/interrupt validation, then boot a minimal Linux guest.

Guest execution is the acceptance test. /dev/kvm or KVM_CREATE_VM alone is
insufficient. Use no GPU, UFS passthrough, remote processors or shared DMA in
this first test.

## Step 6 — expand toward the requested system

After CPU0 guest execution: validate secondary CPU EL2/PSCI entry, then
multi-vCPU guests and thermal/power behavior. Bring up an Ubuntu guest before
adding Android's larger hardware requirements. CPU scheduling can share host
cores; memory needs enforced limits and cooperative reclamation. Share host
services through virtual devices. Add each physical-device capability with a
separate ownership and isolation design.

Priority order: EL2 contract → recoverable CPU0 test → one guest execution →
timers/interrupts → multicore → Ubuntu/Android → broader device sharing.
