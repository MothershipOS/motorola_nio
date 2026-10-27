# EL2 / KVM feasibility on nio

Linux 6.18.54 boots to the diagnostic shell, but the tested boot CPU enters at
EL1 and KVM reports `HYP mode not available`. The boot uses `maxcpus=1`, so the
other CPU entry paths are not yet validated with this LTS kernel.

The current evidence and implementation are in
[EL2-offline-results.md](EL2-offline-results.md). The earlier readiness review
is [EL2-review.md](EL2-review.md).

## Firmware evidence

The backed-up `hyp` image is Qualcomm QHEE, an ELF with entry 0x80040000 and a
loadable code/data segment at that address. Strings include
`hyp_manager_launch`, `hyp_make_smc`, `hyp_devcfg_init`, `map_HLOS_for_Hypx`,
and stage-2/PSCI diagnostics. Together with the saved Linux EL1 log, this is
consistent with QHEE retaining EL2 and hosting HLOS at EL1.

Its entry path has a return dispatch where width 2 selects AArch64 EL1h
(SPSR_EL2=0x85), followed by ERET at 0x80040328. On the first initialization
path the target address is an incoming argument; re-entry paths use per-CPU
tables. The real incoming payload address and subsequent ABL/Linux handoff
have not been captured. No supported EL2-release interface has been established.

## Implemented investigation

The analyzer now accounts for the entire executable segment across embedded
data. The original-code QEMU harness originally reached a fatal watchdog request
0xc2000108 after an unsupported register read. A narrow register model now gets
past that fault to 0x42000604 (secure-state query). Nio now supplies the measured
EL1-visible mask 0xf7f and register word 0x60080201. Explicit secure-state replay
plus a PSCI version model advances to SMEM initialization. The bounded SMEM
model, local lock/table writes and deterministic heap PRNG replies now advance
through SMEM. GCC/SMMU and QFPROM models exposed VMID-5 initialization failure
and a later CPU translation fault. Firmware-derived minimum counts and bounded
context controls now resolve that modeled failure. Replaying the measured
command-database pointer reaches SMEM TOC memory assignment `0xc2000c16`.
QHEE's SMMU handlers filter the IDs exposed to Linux; the reconstructed counts
are a hypothesis, not a raw EL2 capture. This progress also depends on the
explicit unsupported-response experiment for IsDeviceNonSecure. See the
[SMMU context results](EL2-SMMU-context-model.md). Four isolated handoff tests
show that SPSR=0x3c9 selects EL2h while leaving SCTLR_EL2.M/C unchanged.
The exact ownership model now advances through all eleven captured SMEM
regions; QHEE constructs the earlier missing SMEM mappings. The VMID 21/22 TZ-subsystem channel at `0x80dc1000` also passes its exact
ownership model. The VMID 21/42 channel, command-database ownership and
hypervisor log sharing also pass. Measured TZ log pointer replay and exact
IMEM publication reach PMIC initialization through eight checked execution
points. Three measured read-only PMIC metadata tables now replay; twelve
checkpoints reach SCM `0xc2000c19` with `[0x0ccf0000,0x0cd00000,2,6,1]`.
That distinct call now has a finite 241-request response/ledger experiment.
With explicit PIL empty-list and late-entry models, main initialization returns
and the exact bridge/allocator PRNG experiments complete the cold path.
Original ERET runs a synthetic RAM probe at EL1 under the original stage-2
mappings. The next complete-path experiment changes only the loaded SPSR
instruction: it selects EL2h, then faults on EL2 stage-1 execute permission
at the probe address with MMU/caches retained. A bounded 124-byte terminal
replacement now clears M/C/I after diagnostic-range cache maintenance and
executes the probe at EL2 under both GCC input states. Read-only page audits
and MMU-switch/fetch checkpoints pass; TCG does not prove physical cache
coherency. All 878 current offline checks across 43 suites pass. See
[selector replay and QUP version boundary](EL2-XBL-selector.md),
[original counter and platform-selection boundary](EL2-XBL-counter.md),
[SEC hold-flag replay and virtual-counter boundary](EL2-XBL-readiness.md),
[original canary store and SEC-main readiness boundary](EL2-XBL-canary-return.md),
[original SEC cache startup and second buffer request](EL2-XBL-cache-startup.md),
[original XBL stack-sizing return](EL2-XBL-stack-return.md),
[TZ buffer and original FIFO contract](EL2-TZ-buffer-contract.md),
[TZ query reply and next buffer request](EL2-TZ-query-reply.md),
[XBL stack query and original QHEE forwarding](EL2-XBL-stack-SMC.md),
[original SEC workspace and stack](EL2-XBL-startup.md),
[TZ entry controls through full QHEE](EL2-TZ-entry-state.md),
[original TZ restore and ERET](EL2-TZ-monitor-restore.md),
[TZ records and argument frame](EL2-TZ-handoff.md),
[original SEC after full cold QHEE](EL2-XBL-prefix.md),
[the original ABL boundary and XBL candidate](EL2-ABL-boundary.md),
[the diagnostic transition](EL2-diagnostic-transition.md),
[full handoff tracing](EL2-bridge-handoff-model.md) and
[the entry control and XBL/ABL inventory](EL2-entry-contract.md).

Pinned XBL has an AArch64 TE SEC entry at `0x9fc0cc50`, matching its volume's
first branch. SEC contains an EL2-specific startup path. The compressed ABL
MotoBootModule is AArch64 PE32+ despite its ELF32 container. These static
findings do not establish QHEE's actual incoming target or a complete later
boot at EL2.

XBL's APPSBL table row configures `0x9fc00000`, whose first branch targets
SEC. The modeled cold QHEE path now executes that original SEC prefix at
EL2 through VBAR setup, under both GCC inputs, with a stock EL1 control.
SEC rewrites HCR_EL2 to `0x10`; later register/service setup remains open.
The earlier indirect callback slot is descriptor configuration, not a secure
transfer. A separate later `0x82000114` SMC passes a fixed `0x80716100` buffer
of size `0xe00`; its actual contents and bootstrap dispatch are unmeasured.
Original TZ selectors/frame instructions now prepare candidate x0/x1/x2/x3
from synthetic records, and a monitor slice copies them into the next context.
Prepared SPSR `0x89` and SCR `0x504` are frame values, not captured incoming
controls. Original monitor restore/ERET now enters EL2 under those inputs:
SPSR=0x89, software SCR=0x505, SCTLR_EL2=0 and supplied HCR preserved.
Those controls now pass full QHEE and the original SEC prefix with both
HCR/GCC inputs. QHEE retains DAIF=0x80 through initialization; a new finite
terminal masks all DAIF before maintenance within the same 124-byte range.
Actual bootstrap inputs remain open. The original ABL preparation and AArch64 launch blocks preserve EL2 in isolated
tests, with CPU MMU/cache on/off and masked/unmasked DAIF inputs. They clear
M/C/I and forward seeded arguments, but do not independently mask D or test
earlier UEFI/ABL initialization and optional hypervisor services.

These results do not validate a complete firmware-to-Linux EL2 handoff. Kernel
configuration alone cannot reclaim an exception level retained by firmware.

## Corrections to the initial hypothesis

- A blank or stub hyp is not a validated route on this particular device.
- `secure=no`, engineering state and CID DEAD do not prove that XBL accepts
  arbitrary, unsigned or integrity-inconsistent firmware.
- The code SHA-384 digest is embedded at file offset 0x1138. The current
  instruction experiment leaves it stale and is not flash-ready.
- A structurally valid ELF is not evidence of lower recovery risk: the modified
  code can still fail before ABL provides fastboot.
- Stock slot B does not establish automatic fallback after such a failure.
- No compatible EDL programmer/recovery path has been verified.
- Replacing two register clears with a zero write to SCTLR_EL2 is not a reviewed
  MMU/cache teardown. Initial MMU enablement is conditional, not unconditional.
- The eight other ERET candidates have not all been control-flow classified.
- A successful KVM milestone requires guest execution, not only `/dev/kvm` or
  KVM_CREATE_VM.

The Samsung-targeted [Qualcomm-HypX research](https://github.com/Qualcomm-HypX-Reversing/emulation)
provides a useful example of an EL3/QEMU investigation. Its target firmware and
patches are not proof of compatibility with nio QHEE.

## Next step

Follow [KVM-PLAN.md](KVM-PLAN.md). The original cold path now reaches its
synthetic payload. Establish the real intervening boot stages and validate a
minimal CPU0 EL2 transition against the complete path, including executable
identity mapping, cache/PoC handling and Linux entry-register requirements.
The diagnostic EL2 fetch now succeeds after a bounded MMU/cache transition;
stop adding unrelated device models. The real UEFI/ABL/Linux path takes priority.
The configured candidate now executes the original SEC prefix at EL2 in the
full modeled cold path, including the original monitor's derived entry-state
variation with both HCR/GCC inputs and an explicit terminal DAIF mask. Its
original vector/BSS stores now replace sentinel RAM with intact guards, and
SP reaches 0x9ffd0000 at EL2. Its stack dispatcher now reaches the 0x02000601
SMC, which enters modeled EL3 directly; the stock EL1 control traps into
QHEE and its original handler forwards the request unchanged. The diagnostic
terminal clears x0–x3 only. Original TZ argument/registry/marshaller slices
now validate both captured requests without dereferencing inherited x6 and
derive a zero status/availability reply. The exact synthetic EL3 replay
advances both paths to the eight-byte `0x02000a01` SMC at `0x9fc28468`.
Original buffer slices reach both pointer-check boundaries and the selected
PRNG backend; finite FIFO fixtures derive its eight-byte output and original
status/count reply, under explicit ownership/setup/cache assumptions. Exact
one-shot replay now lets original XBL unwind stack sizing and adjust SP to
0x9ffcfd00, stopping before the next helper at 0x9fc0cf38. Original stock
buffer forwarding uses 0x80041aa0 and x7=3; both caller contracts are checked.
Original helper 0x9fc17b90 now executes set/way invalidation; subsequent
SEC calls enable I/D at the existing EL while leaving translation off.
The canary initializer reaches the second buffer SMC at 0x9fc28468,
SP=0x9ffcfce0. Stock QHEE clears x6
and sets x7=3. A separately guarded second fixture reply now lets original
XBL store the canary and enter SEC main at the same EL. It stops before
readiness read 0x146bf944 at PC 0x9fc0e37c; no readiness value is supplied
or read at that earlier boundary. Two fixed read-only phone checks now
capture 0x3a6506a5, while original SEC holds only for 0x55444247. An exact
one-read postboot replay under an explicit entry-state assumption now exits
the loop and reaches CNTVCT_EL0 at 0x9fc2bb48. The original no-op hook and
platform canary copy execute. The new trace also executes the counter read
and original fixed-19.2MHz conversion, stores the result, passes the SIMD
load and copies its descriptor. QEMU advertises 62.5MHz: arithmetic is verified,
physical elapsed time is not. The next uint32 read at 0x01fc8004 faults at the
current EL, paused before the vector handler. Two fixed postboot phone reads
return zero. One exact replay under an explicit entry/EL2 assumption now
lets original SEC select/store its descriptor and match its table; the next
read is QUP wrapper hardware version at 0x00ac0004 and aborts at the current
EL. Phone wrapper AHB clocks are disabled postboot, and serial runtime status
is unsupported. Next capture that fixed word through a diagnostic with
balanced clock-framework references before modeling it. Flag publisher/cold state,
physical cache coherency and policy/context switching remain unverified. Trace the bootstrap bridge from XBL's fixed buffer to
TZ entry pointers and actual records.
The real IsDeviceNonSecure reply, cold payload and Linux entry contract, plus
recovery independent of ABL, remain open. CPU0 guest execution takes priority.

No physical firmware or original backup was changed. The SPSR experiment
changes one word in the emulator's loaded code copy; the diagnostic variant
also replaces the terminal block. Neither is flashable.
