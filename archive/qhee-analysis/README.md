# Offline QHEE analysis for nio

> **Historical (2026-10-08):** QHEE is no longer in the boot chain (u-boot now runs as the hyp, see
> `ARCHITECTURE.md`). The `kernel/EL2-*.md` / `KVM-PLAN.md` notes linked below were archived to
> `backups/stale-docs-20261008.tar.gz`; extract it from the project root to follow the links.

Tools for understanding the EL1/EL2 handoff in the backed-up Qualcomm hyp image.
They do not access the phone. Current findings and limits are recorded in
[EL2 offline results](../../kernel/EL2-offline-results.md).

## Commands

Run from the project root:

```sh
python3 tools/hyp_re/qhee.py
python3 tools/hyp_re/analyze.py --json reports/qhee-offline/sweep.json
python3 tools/hyp_re/analyze.py --around 0x800401d8
python3 -m unittest discover -s tools/hyp_re -p test_analysis.py -v
python3 tools/hyp_re/run_qemu.py
python3 tools/hyp_re/test_handoff.py
python3 tools/hyp_re/hyp_patch.py
```

- `qhee.py`: bounds-checked ELF64/AArch64 loader; BSS reads return zeroes.
- `analyze.py`: whole-segment, alignment-preserving linear sweep. Reports byte
  coverage and candidate instruction sites; it does not prove reachability.
- `run_qemu.py`: original code with a synthetic EL3 entry and probe payload.
  Captures QHEE logs and classifies 0xc2000108 as a fatal watchdog request.
  An optional register model resolves its root cause and advances to the
  secure-state query 0x42000604. Explicit captured-response replay plus a PSCI
  version model advances to SMEM target-info initialization. The optional sparse
  SMEM and bounded PRNG models now reach gcc_mmu_tcu_clk; none implements TZ.
- `test_handoff.py`: four extracted-code models test return-level selection and
  SCTLR M/C behavior. These omit intermediate QHEE code and are not a full boot.
- `hyp_patch.py`: dry-run by default. `--out NEW_PATH` creates an exclusive
  offline copy, never overwrites an existing file or the backup tree. The SPSR
  edit leaves embedded integrity metadata stale: **output is not flash-ready**.

Dependencies: Python Capstone, GNU aarch64-linux-gnu-gcc, and project-local QEMU
in `kernel-work/emulation/root/usr/bin/qemu-system-aarch64`. The wrapper supplies
its local library path. Ubuntu package versions/hashes are recorded in
`kernel-work/emulation/packages.lock.json`. Run manifests include tool hashes.

## Established limits

The AArch64 dispatch selects EL1h using SPSR=0x85. Changing it to 0x3c9 reaches
EL2h in the isolated tests but does not clear MMU/cache state. Initial entry
arguments survive on the cold path; later entries use per-CPU tables. The real
payload identity, full TZ contract, cache teardown and secondary CPU behavior
remain unresolved. No compatible EDL recovery route has been verified.

Do not infer acceptance of an edited hyp image from `secure=no`, or assume a
stock alternate slot will recover a failure before ABL/fastboot.

## Secure-monitor follow-up

[Detailed evidence and commands](../../kernel/EL2-secure-monitor.md).
`build_qemu_model.py` builds pinned upstream QEMU with the optional
`nio-soc-version`, `nio-smem` and `nio-gcc-mmu` devices. `test_secure_call.py` checks the former's access rules and
the original firmware's before/after behavior. `run_qemu.py` accepts `--qemu`,
`--soc-hw-version`, `--devcfg`, `--secure-state-sample`, `--psci-version`,
`--out` and `--trace` for explicit model inputs. Replay is disabled by default.
`test_replay.py` validates register preservation, rejection of unsupported call
contracts and invalid samples, and original-firmware progress to the SMEM fault.
Watchdog and unknown services always stop. Secure-state replay is explicitly an
assumption that a captured EL1 response equals what an EL2 caller would receive.

Phone collectors (outside this offline directory): `capture_nio_scm.py` reads
the two fixed diagnostic queries, optionally the SoC register; `capture_nio_smem.py`
reads bounded SMEM layout metadata. Neither writes firmware or SMEM registers.

## SMEM and heap initialization

[Current results and full reproduction command](../../kernel/EL2-SMEM-model.md).
`smem.py` validates captured blocks and produces a snapshot plus byte-validity
map. `nio-smem` overlays the whole reserved region: uncaptured holes fault.
`--smem-sample` enables captured reads. Version publication, RLOCK backing,
mutex 9 and RAM-table writes require their separate explicit switches.
`--prng-word` supplies deterministic bytes only for three observed heap-init
requests, never for other buffers. `test_smem.py` and `test_prng.py` verify
these limits and the new original-firmware execution boundary.

## Minimal GCC/SMMU path

[Evidence, limitations and reproduction](../../kernel/EL2-GCC-MMU-model.md).
`--gcc-mmu-clocks off|on` enables bounded clock/power controls and SMMU aperture
guards. `--smmu-ids` requires the active-device capture; `--smmu-control` enables
only the observed reset/configuration register families. `--qcom-timer` supplies
the delay counter. There is no DMA translation. `test_gcc_mmu.py` has 88 checks.

`--nonsecure-query-unsupported` explicitly tests the firmware's error branch
for IsDeviceNonSecure; it is disabled by default and returns no security-state
answer. `test_replay.py` now has 20 checks including this contract. Both initial
clock states reach the query, or the QFPROM boundary with the failure experiment.
The [KVM plan](../../kernel/KVM-PLAN.md) tracks the remaining physical EL2 and
guest-execution gates.

## QFPROM and CPU translation follow-up

`--qfprom-sample` enables `nio-qfprom`: one measured read-only word, guarded
inside its 4 KiB page. `test_qfprom.py` has 25 checks. With the explicit query
failure experiment, original QHEE reaches a VMID-5 initialization failure and
then an EL2 translation fault on unmapped SMEM. `inspect_qhee_mmu.py` reproduces
four read-only debugger-state checks; it requires gdb-multiarch.

`test_smmu_view.py` executes seven original-firmware instruction cases proving
that ID0/ID1 are filtered before Linux sees them. Synthetic test vectors are not
raw phone measurements. See [the findings and next target](../../kernel/EL2-QFPROM-MMU-model.md).

## Context-bank and command-database follow-up

`--smmu-firmware-counts` derives a minimum-count hypothesis from the pinned
QHEE descriptors, checking projection to the captured Linux-visible IDs.
`--smmu-contexts` enables bounded control storage, zero-initialized context
registers and immediate TLB completion; it requires `--smmu-control`.
`--cmd-db-sample` replays only the measured word at `0x0c3f000c`, guarded by
`nio-cmd-db-pointer`. Unknown accesses still abort; DMA is not implemented.

`test_smmu_contexts.py` has 25 checks; `test_cmd_db.py` has 21. With these
options and the explicit IsDeviceNonSecure failure experiment, original QHEE
passes VMID-5 setup and stops at SMEM TOC memory assignment `0xc2000c16`.
There is no reply model for that call. See the
[full evidence and reproduction](../../kernel/EL2-SMMU-context-model.md).

## Exact SMEM ownership transitions

`--smem-toc-assign` enables one checked TOC ownership transition;
`--smem-partition-assign` adds ten pinned captured SMEM regions. Both are
optional. The handler validates the pinned caller and complete argument
buffers, commits a per-region ledger and rejects stale ownership or unknown
requests. Initial VMID-3 ownership and successful TZ replies are assumptions;
the model does not enforce CPU/DMA access or write QHEE buffers/page tables.

`test_smem_assign.py` has 63 checks. `inspect_assign_mem.py --manifest PATH
--skip N --out DIR` reads the selected original-firmware request, ledger and
SMEM CPU mappings. With the new switches, original QHEE completes eleven SMEM
assignments and stops on the unlisted page `0x80dc1000` for VMIDs 21/22. See
[contracts, evidence and limits](../../kernel/EL2-SMEM-ownership-model.md).

## VMID 21/22 TZ-subsystem channel

`--tz-channel-assign` enables only the `0x80dc1000`/4 KiB transition from
VMID 3 to 21/22, both RW, with its own ledger. It requires the common pinned
contract via `--smem-toc-assign`. It does not implement the secure channel's
contents, protocol or access enforcement. `test_tz_channel.py` has 30 checks.
Original QHEE then stops on the adjacent VMID 21/42 channel. See
[firmware role, implementation and validation](../../kernel/EL2-TZ-channel-model.md).

`--tz-channel-21-42-assign` separately enables the second channel at
`0x80ddc000`/8 KiB, VMIDs 21/42; it requires `--tz-channel-assign`.
`test_tz_channel_21_42.py` has 30 checks, including full-width VMID-42 masks,
independent state and both original-QHEE clock paths. The next request is
command-database ownership. See
[second-channel evidence](../../kernel/EL2-TZ-channel-21-42-model.md).


## Command database, diagnostic logs and initialization tail

`--cmd-db-assign` adds the exact 128 KiB read-only assignment to eight VMIDs.
`--hyp-log-share` adds the exact VMID-4 to VMID-3 R / VMID-4 RW log assignment.
Both are optional ledgers, with no TZ/DMA enforcement. They require the prior
ownership switches; unknown calls still stop.

`--tz-log-sample PATH` guards the IMEM page and replays the captured pointer at
`0x146bf720`. `--imem-publications` separately allows the exact one-shot early
QHEE log pointer/size publication at `0x146bfb30`. Unknown reads/writes abort.
`trace_init_tail.py --manifest PATH --out DIR` records eight read-only GDB
checkpoints, stopping before the first PMIC APID-table read. Assignment
inspection also records bounded candidate stack frames.

New suites: `test_init_assign.py` (54), `test_tz_log.py` (28), and
`test_init_tail.py` (8). Total with prior tests/debugger checks: 477 passing.
The trace now reaches `0x80060d40`, reading `0x0c440900`. The phone's 512-word
APID table has been captured; its replay is the next step. See
[contracts, evidence, reproduction and limits](../../kernel/EL2-init-tail-trace.md).


## Read-only PMIC metadata and next SCM call

`--pmic-arb-sample PATH` replays exactly 512 APID words; `--pmic-owner-sample
PATH` separately adds 512 owner words; `--pmic-secondary-sample PATH` adds
256 secondary mapping words. Later options require the preceding options.
`pmic.py` validates captures before creating bounded binary snapshots for
`nio-pmic-arb`. Only aligned 32-bit reads of the enabled tables succeed;
unknown accesses and every write abort. No PMIC transactions are implemented.

`trace_init_tail.py --through-pmic-tables` records eleven checkpoints;
`--through-pmic-scm` records twelve, ending before SCM `0xc2000c19`. The new
call has scalar arguments `[0x0ccf0000,0x0cd00000,2,6,1]`; the later finite
response experiment is described below.
`test_pmic.py` has 96 checks and `test_pmic_trace.py` seven; total regression
count at that milestone was 580. See [evidence and reproduction](../../kernel/EL2-PMIC-metadata-model.md).

## Finite PMIC mappings and late initialization

`--pmic-region-map` assumes acceptance of exactly 241 pinned VMID2 RW
channel mappings, in order, with a separate additions ledger. It requires the
pinned PMIC captures and preceding log models. `--pil-empty-region-list` adds
an explicit unmeasured zero-length PIL reply. `--imem-ready-publication` permits
the exact final IMEM pointer publication, after the earlier log publication.
`--handoff-prng` adds three exact ordered late PRNG writes using the fixed test
word. Each option is independently enabled, reports its assumptions and rejects
unexpected inputs. These models implement neither physical TZ enforcement nor
cryptographic entropy.

`trace_init_tail.py --through-main-return` records main-init return and stops
at the first late PRNG call. `--through-late-scm` records sixteen checkpoints,
all 241 mapping requests, the final additions ledger and late PRNG outputs.
The next stop is SCM `0xc2000c1e`, shared-memory bridge creation; its four
arguments are packed scalar operands. The bridge reply and payload ERET were the next target at that milestone;
the follow-up below now covers them. Stack return addresses are distinguished from executed checkpoints.

`test_late_init.py` adds 62 contract checks; `test_late_init_trace.py` adds 14
differential/provenance checks. That milestone had 656 passing checks. See
[scope, assumptions and reproduction](../../kernel/EL2-late-init-model.md).

## Complete original cold handoff

`--shm-bridge-handle UINT64` models one exact bridge-create response with a
nonzero synthetic opaque handle. `--bridge-prng-word UINT64` separately supplies
one exact allocator PRNG write, after bridge creation. They do not enforce TZ
accesses or supply entropy. Changed inputs, repeated creation and delete calls
remain terminal.

`--payload-address 0x90000000` sets the explicit synthetic incoming x0 target
and loads a semihosting RAM probe. Original QHEE completes its cold path and
runs this probe at EL1; the original default target `0x40400000` instead faults
on its first fetch under the existing stage-2 execute permissions. No firmware
code or page-table edit is required for the successful RAM-target run.

`trace_bridge_handoff.py` observes eight bridge/late-entry checkpoints, the
handle in the original bookkeeping record, the model ledgers and stage-2 walks.
It executes two normal instruction steps across ERET to distinguish selecting
the payload PC from successfully fetching its first instruction. It makes no
debugger edits. Calls are captured at the particular SMC PC `0x80041aa0`.

`test_bridge.py` adds 41 contract checks; `test_bridge_trace.py` adds 15
differential/CLI checks. Outcome classification also checks semihosting output
and requires a clean exit without a firmware fault. All 713 checks pass. See
[scope and reproduction](../../kernel/EL2-bridge-handoff-model.md).

## Complete-path EL2 experiment and boot-chain inventory

`--handoff-experiment spsr-el2h` changes only the loaded SPSR instruction,
after validating the original pinned image and expected word. It requires the
bridge PRNG option and RAM probe target. Original backups and firmware image
integrity metadata are untouched; this does not create a flash candidate.
The complete cold path selects EL2h but faults at its first probe fetch:
EL2 stage-1 permissions deny execution while MMU/cache state remains enabled.
The tracer now verifies loaded bytes/metadata and records EL2 stage-1 walks.

`bootchain.py` validates pinned XBL/ABL and extracts bounded TE/PE images,
including ABL's LZMA-guided inner volume. XBL's contained AArch64 SEC entry
is `0x9fc0cc50`; it has an EL2 startup branch. The compressed ABL module is
AArch64. Instruction sweeps and fixed SEC windows are static evidence, not a
complete control-flow proof or capture of the real QHEE target.

`test_entry.py` adds eight test cases; `test_bootchain.py` adds fifteen.
That milestone had 736 passing checks across 26 suites.
See [evidence, limitations and next implementation gates](../../kernel/EL2-entry-contract.md).

## Executable EL2 diagnostic transition

`--handoff-experiment el2-diag-mmu-off` also replaces the original 124-byte
terminal register-clearing block. It uses CTR-based VA cache-clean loops for
the bounded QHEE/probe ranges, instruction-cache maintenance and barriers,
then clears only SCTLR_EL2 M/C/I, zeroes x0–x3 and executes ERET at the
original address. The entire replacement occupies original executable code;
it adds no allocation, stack use, external call or page-table edit.

Both GCC initial-state runs now print `EL2` and exit cleanly. The tracer checks
masked entry and all 588 identity/Normal-memory page mappings, then observes
the SCTLR write and successful EL2 fetch. TCG does not prove physical dirty-cache
or system-cache behavior, and the diagnostic supplies no Linux DTB or firmware
service takeover.

`test_transition.py` adds eight cases. That milestone had 744 checks
across 27 suites; run `check_all.py --out reports/qhee-offline/transition-regressions`.
See [transition bounds, evidence and remaining gates](../../kernel/EL2-diagnostic-transition.md).

## Original ABL boundary and XBL entry candidate

`abl_contract.py` extracts the pinned MotoBootModule and maps PE32+ sections
with bounded DIR64 relocations. Inspected instruction windows remain original.
`run_abl_boundary.py` executes its preparation routine and final AArch64 launch
block in isolation. EL1/EL2 × CPU MMU/cache off/on × DAIF masked/unmasked all
pass. It preserves the caller's EL, clears M/C/I and forwards seeded arguments;
it masks A/I/F while preserving D. These tests do not execute earlier UEFI,
BootLinux's caller, ExitBootServices or optional hypervisor service calls.

`xbl_target.py` records the pinned ten-row configuration table. APPSBL has a
configured-address field `0x9fc00000`, branching to SEC `0x9fc0cc50`. Its
callback uses an indirect interface slot; subsequent tracing below resolves
its successful initialization to descriptor configuration. This is a static
entry candidate, not a captured QHEE target.

`test_abl_boundary.py` adds eight cases, including eight execution subcases;
`test_xbl_target.py` initially added five. That milestone had 757 checks across 29 suites.
See [contracts, exact evidence and next gates](../../kernel/EL2-ABL-boundary.md).

## Original XBL/SEC prefix after full cold QHEE

`--payload-address 0x9fc00000 --prepare-only` prepares the pinned original
3 MiB XBL FV as the payload. This target requires fixture-only mode; execute
with `trace_bridge_handoff.py --xbl-prefix`. The tracer checks payload bytes,
metadata and loader addresses, then runs the full cold path and original SEC
prefix through `0x9fc0ceb4`. QEMU is terminated while paused at that boundary,
before vector-table stores, BSS clearing or platform services.

`--handoff-experiment el2-xbl-mmu-off` selects masked EL2h and the finite
QHEE/FV clean ranges. The original SEC prefix retains EL2 but writes HCR_EL2
to `0x10`. Stock QHEE is the EL1 control. Both GCC input conditions pass;
the EL2 clean-range audit covers all 1,355 identity/Normal-memory pages.

Further static XBL tracing resolves the successful interface initializer and
slot `0x48` to a 20-byte descriptor copy. It is not the secure transfer. The
separate later SMC at `0x1482c50c`, called from `0x14817acc`, has ID
`0x82000114` and fixed buffer `0x80716100`/`0xe00`. Buffer contents and
TZ-to-QHEE setup remain unresolved.

`test_xbl_prefix.py` adds five cases, including four cold execution subcases
and tamper rejection. `test_xbl_target.py` adds two interface/SMC cases.
That milestone had 764 checks across 30 suites; run
`check_all.py --out reports/qhee-offline/xbl-prefix-regressions`.
See [exact bounds, results and next steps](../../kernel/EL2-XBL-prefix.md).

## Original TZ boot records and handoff frame

`tz_handoff.py` pins TZ and inventories its early input-buffer chain, selectors
and monitor dispatch. It executes original target-selection/frame instructions
with explicitly synthetic CPU0 records, a frame pointer and a stack. A second
independent original monitor fixture confirms the first four context arguments.
QHEE-present AArch64 records prepare target `0x80040000` with x0=`0x9fc00000`,
x1=2, x2=x3=0. The absent control selects APPSBL directly.

Prepared SPSR=`0x89` and SCR=`0x504` are raw frame values. Execution stops
before context-stack setup and before the monitor's ELR/HCR/SPSR/SCR handling.
There is no full TZ startup or ERET; actual records and the bootstrap SMC
bridge remain unknown. Width and version controls demonstrate that record
contents change the prepared contract. No instruction patches are used.

`test_tz_handoff.py` adds seven cases. That milestone had **771 checks across 31 suites**; run `check_all.py --out reports/qhee-offline/tz-handoff-regressions`.
See [dataflow, assumptions and next steps](../../kernel/EL2-TZ-handoff.md).

## Original TZ monitor restore and ERET

`tz_monitor.py` executes the original context-layout initializer, SMC handler,
dispatch, context preparation, secure save, register restore and ERET with a
synthetic saved SMC frame. It enables only the optional `nio-tz-fixture-ram`
backing; `run_qemu.py` never enables that device. Original translated code
bytes and loaded file-backed RAM are checked against pinned TZ.

QHEE-present records reach `0x80040000` at EL2h, SPSR `0x89`, software
SCR `0x505`, SCTLR_EL2=0 and HCR preserved. Three diagnostic MRS instructions
confirm CurrentEL, DAIF and SCTLR before termination while paused. The absent
control reaches APPSBL at EL1 and sets HCR.RW. This fixture executes neither
QHEE initialization nor the XBL bootstrap.

CPU controls cover Cortex-A55 and captured CPU0 MIDR fields replayed on that
TCG model. Unsupported Cortex-A76 is a checked original-code terminal loop,
not patched around. Context-SP, zeroed frame/context fields and other initial
state remain explicit assumptions.

`test_tz_monitor.py` adds seven tests, including eight successful execution
combinations and one terminal control. That milestone had **778 checks across 32 suites**; run `check_all.py --out reports/qhee-offline/tz-monitor-regressions`.
See [controls, exact bounds and remaining gates](../../kernel/EL2-TZ-monitor-restore.md).

## TZ-derived entry controls through full QHEE

`--entry-state-model` keeps the earlier `synthetic-masked` default and adds
`tz-frame-hcr-zero` / `tz-frame-hcr-rw`. The finite profiles pin original TZ
frame/instruction evidence and seed SPSR=0x89, software SCR=0x505, SCTLR_EL2=0
and the selected HCR. Actual bootstrap inputs, EL2 SP, other CPU state and
secure-service replies remain assumptions. No TZ monitor is executed in this
full-QHEE fixture. Diagnostic target overrides are recorded explicitly.

Derived profiles automatically enable read-only initial entry inspection in
`trace_bridge_handoff.py`; `--inspect-entry` also checks the earlier default.
Original QHEE retains only I masked through its cold path. New terminal
experiments `el2-diag-masked-mmu-off` / `el2-xbl-masked-mmu-off` mask all DAIF
before maintenance, using the same 124-byte range and original ERET address.
Earlier stub bytes remain unchanged, and the CLI rejects their unmasked-input
combination. Mapping and mask checkpoints cover the transition.

`test_tz_entry_state.py` adds ten tests covering twenty derived-input execution
cases, a default control, pin/metadata/CLI guards and unchanged SCM ledgers.
That milestone had **788 checks across 33 suites**; run
`check_all.py --out reports/qhee-offline/tz-entry-regressions`.
See [results, exact variant and next boundaries](../../kernel/EL2-TZ-entry-state.md).

## Original SEC workspace and temporary stack

`trace_bridge_handoff.py --xbl-startup` extends the pinned original SEC path
through vector filling, SIMD BSS clearing and SP=0x9ffd0000. It terminates
QEMU while paused at 0x9fc0cf28 before the stack-sizing call. The earlier
`--xbl-prefix` retains its 0x9fc0ceb4 boundary; the flags are mutually exclusive.

`run_qemu.py --xbl-workspace-sentinel` requires original XBL and `--prepare-only`.
Two finite 0xa5-filled RAM loaders and 16-byte guards verify actual original
stores. Sentinel files, loaders and metadata are checked before execution.
No original SEC bytes or debugger-visible guest state are edited.

`test_xbl_startup.py` adds nine tests with ten EL1/EL2 startup executions and a
legacy-prefix control. That milestone had **797 checks across 34 suites**; run
`check_all.py --out reports/qhee-offline/xbl-startup-regressions`.
See [exact ranges, controls and next service boundary](../../kernel/EL2-XBL-startup.md).

## Original XBL stack query, routing and QHEE forwarding

`--xbl-stack-smc` extends the read-only original SEC trace to 0x9fc284dc
before its first stack-source query. Original stack frames, empty cache and
zero-selector dispatch are checked; complete x0–x7 are recorded.
`--inspect-xbl-smc-route` takes one normal original SMC step, then pauses before
its destination vector instruction. EL1 traps into original QHEE; EL2 enters
the synthetic EL3 vector. Neither supplies a secure response.

`--inspect-xbl-qhee-forward` requires stock EL1 and routing inspection. It
executes the original QHEE trap handler to its first pinned SMC or XBL return.
All stock controls forward the query unchanged at 0x80041cbc. Earlier prefix
and startup bounds remain available; wrong-level combinations are rejected.
The terminal diagnostic clears x0–x3 only, and inherited x5/x6 differences
remain explicit in the captured service request.

`test_xbl_stack.py` adds nine tests: ten query/routing cases, five original
handler traces and two earlier-boundary controls. That milestone had **806 checks
across 35 suites**; run
`check_all.py --out reports/qhee-offline/xbl-stack-regressions`.
See [exact registers, bounds and next TZ gate](../../kernel/EL2-XBL-stack-SMC.md).

## Original TZ query slices and exact reply

`tz_query.py` executes pinned argument/registry slices through validation and
separately seeds the original marshaller/callback. It derives successful status
zero and availability zero for `0x02000602`, with positive availability and
malformed-argument controls. Per-case captured x0–x13 reproduce the result;
the one-scalar callback never dereferences inherited x6. Policy/accounting,
context switching and original monitor return are outside these bounded slices.

`run_qemu.py --xbl-query-reply` opts into one exact synthetic EL3 reply derived
from those original slices. It requires prepared original XBL and bridge PRNG,
checks the captured call sites/arguments and has a one-shot ledger. No entropy
or XBL buffer is written. `trace_bridge_handoff.py --xbl-stack-buffer` validates
reply metadata and stops at `0x9fc28468` before XBL's `0x02000a01` eight-byte
buffer SMC. The earlier mutually exclusive boundaries remain available.

`test_tz_query.py` adds nine tests with ten full-QHEE/XBL cases, sixteen
synthetic reply contracts and an earlier-query control. That milestone had **815 checks
across 36 suites**; run
`check_all.py --out reports/qhee-offline/tz-query-regressions`.
See [original reply, assumptions and next buffer gate](../../kernel/EL2-TZ-query-reply.md).

## Original TZ buffer validation and PRNG FIFO slices

`tz_buffer.py` executes the original typed decode and two-argument marshaller
through the buffer handler's pointer-check boundary. It records both checker
fronts, original overflow/page rounding, file-backed PRNG selection and the
first state/clock dependencies. Those runtime checks remain pending.

An independently seeded original FIFO loop consumes exactly four synthetic
samples and four ready reads, performs pair filtering/XOR and copies exactly
eight bytes with intact guards. Explicit ownership/setup/release/cache joins
let original handler/return marshalling derive status zero and byte count eight;
short output stops at the original error logger. Every join is recorded. No
new EL3 reply is enabled, secure policy proved or physical entropy supplied.

`test_tz_buffer.py` adds nine tests, including ten captured-request snapshots,
count/type/size/overflow rejection, FIFO bounds/filtering and original return
marshalling. That milestone had **824 checks across 37 suites**; run
`check_all.py --out reports/qhee-offline/tz-buffer-regressions`.
See [contract, explicit assumptions and next trace](../../kernel/EL2-TZ-buffer-contract.md).

## Exact buffer fixture reply and original stack-sizing return

`run_qemu.py --xbl-buffer-reply` requires query replay and opts into one exact
eight-byte fixture reply. Original TZ slices derive status zero/count eight;
finite FIFO bytes are explicitly not entropy. Call-site/argument/state checks
cover stock forwarding (`0x80041aa0`, x7=3) and direct EL2 (`0x9fc28468`, x7=0),
with one-shot ledger, zero buffer/cache and selector guards.

`trace_bridge_handoff.py --xbl-stack-return` checks derived metadata and follows
original source read, nibble-cache update, frame unwind and SEC SP adjustment.
It stops at `0x9fc0cf38`, SP=`0x9ffcfd00`, before the next helper. Routing and
stock-forwarding inspection now also support the earlier buffer boundary.
Cold calls and later `xbl_forward_calls` are recorded separately.

`test_stack_return.py` adds nine tests: ten full-path cases, 22 synthetic reply
contracts, five original stock forwarding/TZ slice controls and two earlier
routing controls. That milestone had **833 checks across 38 suites**; run
`check_all.py --out reports/qhee-offline/stack-return-regressions`.
See [original stack return, assumptions and next helper](../../kernel/EL2-XBL-stack-return.md).

## Original cache startup and second canary buffer request

`xbl_cache.py` pins eleven original SEC instruction windows and the second
`0x9fc28468` occurrence. `trace_bridge_handoff.py --xbl-cache-startup` requires
the earlier exact query and one-shot buffer reply models. It traces original
set/way invalidation, I/D enabling at the existing EL with translation off,
and the canary source dispatcher. It pauses before replying to the second
eight-byte buffer request; original canary `0xc0c0c0c0` remains untouched.

Geometry checkpoints record QEMU Cortex-A76 CCSIDR/CSSELR reads and original
loop bounds (1,024 plus 8,192 operations); these are not physical cache
measurements or coherency proof. Optional SMC routing and stock forwarding
controls now support this boundary. Original QHEE clears x6 and sets x7=3,
while direct EL2 retains the cache-loop register values. CPSR is normalized
to uint32 to avoid GDB sign extension; stock handler call lists exclude
previous forwarding calls. No second reply model is added.

`test_cache_startup.py` adds nine tests: ten full cases, five stock forwarding
controls, ten separately seeded original TZ slice derivations, negative
metadata/routing gates, and four earlier-boundary controls. That milestone had **842
checks across 39 suites**; run
`check_all.py --out reports/qhee-offline/cache-startup-regressions`.
See [cache startup, captured contract and next step](../../kernel/EL2-XBL-cache-startup.md).

## Second buffer fixture, original canary store and SEC readiness boundary

`run_qemu.py --xbl-canary-reply` requires query and first-buffer replay, and
opts into a separate one-shot second reply. Original TZ slices at the captured
stock/direct-EL2 register contracts derive the count/status and repeated FIFO
bytes. Exact site/SP/argument/cache/ledger/zero-buffer/selector/shifted-cache/
original-canary guards reject malformed or repeated requests. The first
buffer reply remains one-shot; the default gains no second reply. Bytes are
deterministic fixtures, not entropy or production canary randomness.

`xbl_canary.py` pins original canary/main/readiness windows and literals.
`trace_bridge_handoff.py --xbl-canary-return` traces the original second
source load, canary store, stack unwind and SEC-main entry without debugger
writes. It pauses at `0x9fc0e37c` before the four-byte readiness read at
`0x146bf944`. SCTLR/HCR/EL/masks and adjacent canary/workspace guards remain
unchanged. No readiness value is supplied or read.

`test_canary_return.py` adds nine tests: ten full traces, ten pre-second
controls (five stock forwarding), actual TZ slice derivations, 28 synthetic
reply contracts, CLI/metadata rejection and four earlier stops. That milestone had **851
checks across 40 suites**; run
`check_all.py --out reports/qhee-offline/canary-return-regressions`.
See [canary return, readiness dependency and assumptions](../../kernel/EL2-XBL-canary-return.md).

## Measured SEC hold flag through virtual-counter boundary

`xbl_readiness.py` pins original hold-loop/platform/counter windows and parses
two identical diagnostic-phone reads of `0x146bf944` (`0x3a6506a5`). Original
SEC waits only for `0x55444247`. Publisher/cold state remain unverified;
postboot EL1-to-modeled-entry/EL2 equality is an explicit assumption. Finite
original poll slices distinguish nonheld, held and synthetic-release behavior.

`run_qemu.py --xbl-readiness-sample reports/nio-sec-flag-20261006/manifest.json`
requires prior canary replay and QHEE IMEM publications. The existing pointer
device separately opts into one four-byte flag read after both publications.
Writes, neighbors, repeated reads and absent prerequisites abort. The wider
unaligned TCG probe consumes the permitted first half and aborts on the
adjacent half; it does not complete an eight-byte transfer. Default behavior
and earlier pointer/publication contracts are unchanged.

`trace_bridge_handoff.py --xbl-readiness` verifies sample/device metadata and
follows the original loop exit, no-op hook and platform frame canary copy,
pausing before `mrs x0, cntvct_el0` at `0x9fc2bb48`. No counter or generic MMIO
model was added. Earlier stops do not consume the flag replay.

`test_readiness.py` adds nine tests: ten full cases, finite poll controls,
15 device contracts, capture/metadata/dependency rejection, current QEMU
build provenance and four earlier stops. That milestone had **860 passing checks across
41 suites**; run
`check_all.py --out reports/qhee-offline/readiness-regressions`.
See [measured flag, assumptions and next counter access](../../kernel/EL2-XBL-readiness.md).

## Original counter conversion and platform-selection read

`xbl_counter.py` pins the original counter/conversion/initialization windows
and verifies eight original-instruction arithmetic slices.
`trace_bridge_handoff.py --xbl-counter` requires the earlier measured flag
and exact replies. It executes CNTVCT_EL0, verifies original conversion at
19.2MHz and its store, follows the SIMD constant load and 40-byte descriptor
copy, and stops before uint32 `0x01fc8004` at PC `0x9fc2a150`.

`--inspect-xbl-next-step` attempts that load once, records its current-EL
data abort and stops before the handler. No general MMIO or timer model is
added. QEMU advertises 62.5MHz; the mismatch is recorded rather than hidden.
Two fixed read-only postboot phone checks return zero for the selector; cold
entry and diagnostic EL2 equality are not established or replayed here.

`test_counter.py` adds nine tests covering ten full profiles, conversion
boundaries/wraparound, original source rejection, SIMD/copy and exact fault
controls, cache/EL/canary/ledger preservation, metadata rejection, current
provenance and four earlier/unstepped controls. That milestone had **869 passing checks
across 42 suites**; run
`check_all.py --out reports/qhee-offline/counter-regressions`.
See [counter dataflow, timing limit and next selector replay](../../kernel/EL2-XBL-counter.md).

## Measured selector replay and QUP version boundary

`xbl_selector.py` strictly parses the repeated captured selector word, pins
original selection/descriptor windows and checks eight original leaf slices.
`run_qemu.py --xbl-selector-sample reports/nio-platform-selector-20261006/manifest.json`
requires prepared original XBL, the existing SoC-version device and measured
readiness. The selector is separately disabled by default, requires a prior
version uint32 read and returns its supplied word once. Writes, repeats,
unsupported widths and neighbors fail; wide unaligned transfers may consume
the allowed first half before aborting at the region end. Aligned wide base
loads are rejected intact, preventing a split-read loophole.

`trace_bridge_handoff.py --xbl-selector` verifies metadata/device command,
executes the original selector load, choice/store and descriptor table lookup,
then stops before `0x00ac0004` at PC `0x9fc220fc`. Optional
`--inspect-xbl-next-step` records one attempted read and its current-EL data
abort, paused before handler execution. Earlier stops do not consume replay.
Local pinned Linux sources identify the next read as QUP wrapper 1 hardware
version; postboot phone wrapper AHB clocks are disabled. A balanced-clock
diagnostic capture is the next task. Cold-entry/EL2 equality is unverified.

`test_selector.py` adds nine tests with ten full profiles, eight selection
slices, 15 device contracts, strict sample/metadata/dependency rejection, four
earlier/default stops, source/build/capture provenance and unchanged firmware.
All **878 current checks across 43 suites pass**; run
`check_all.py --out reports/qhee-offline/selector-regressions`.
See [selector replay, width behavior and next version capture](../../kernel/EL2-XBL-selector.md).
