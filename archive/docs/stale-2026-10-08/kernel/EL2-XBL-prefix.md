# Original XBL/SEC prefix after cold QHEE — 2026-10-06

The full modeled QHEE cold path now enters the original XBL firmware volume
at the configured `0x9fc00000` candidate and executes SEC's early startup
through vector-base setup. With the bounded EL2 terminal experiment, SEC
retains EL2. The unchanged QHEE control reaches the same prefix at EL1.
Both results reproduce with GCC clock inputs initially off and on.

This joins two original firmware stages in the emulator. It remains a
synthetic entry-contract experiment, not a captured phone boot or a complete
UEFI/ABL/Linux boot. Physical KVM is still unproven.

The current milestone adds original TZ monitor restore/ERET fixtures:
**788 checks across 33 suites**. See [full QHEE entry controls](EL2-TZ-entry-state.md),
[the secure restore](EL2-TZ-monitor-restore.md)
and [TZ dataflow and argument-frame limits](EL2-TZ-handoff.md).
The 764-check evidence below records this earlier SEC-prefix milestone.

## Loaded bytes and bounds

`run_qemu.py --payload-address 0x9fc00000 --prepare-only` loads exactly the
pinned XBL ELF segment `[0x9fc00000,0x9ff00000)`: 3 MiB, filesz=memsz, original
R/W/X flags. Other XBL segments are not loaded. The FV and SEC instructions
remain byte-for-byte original. The loader checks the firmware pin, segment
bounds and the configured entry's original branch to `0x9fc0cc50`.

The synthetic EL3 input remains explicit: x0=`0x9fc00000`, x1=2 (AArch64),
x2=0 (cold path). QHEE then clears x0–x3 before ERET, so SEC takes its
zero-x0 startup path. These are assumptions, not measurements of the actual
TZ-to-QHEE arguments.

The named `el2-xbl-mmu-off` experiment changes only the loaded QHEE copy:

1. Change the original SPSR-selection instruction to select masked EL2h.
2. Replace the original 124-byte terminal block with the bounded cache/MMU
   transition, retaining ERET at `0x80040328`.

The replacement differs from the earlier diagnostic stub only in its two
payload-range instructions. It cleans QHEE image/BSS and the original 3 MiB
FV to PoC, performs instruction-cache maintenance/barriers, clears only
SCTLR_EL2 M/C/I and zeroes x0–x3. It uses no stack, allocation, external call
or page-table edit. The original 4 KiB diagnostic variant still compiles to
its previously recorded byte hash.

Before disabling translation, the tracer audits all 1,355 pages in the two
clean ranges: 587 QHEE pages and 768 FV pages. Every page has an identity
Normal-memory mapping. The FV pages are execute-never under the original
EL2 tables; disabling the MMU makes the subsequent physical fetch possible.
TCG does not validate physical dirty-cache or SM8250 system-cache behavior.

Firmware backups and embedded integrity metadata are unchanged. No signed or
flashable firmware image is produced.

## Executed original SEC prefix

The tracer runs the full cold QHEE initialization and its finite SCM/MMIO
models, observes the terminal transition, then performs normal instruction
steps across ERET and the original FV branch. It continues through these
original SEC checkpoints without changing guest registers or memory.

| Boundary | EL2 experiment | Unchanged QHEE control |
| --- | --- | --- |
| After QHEE ERET | PC `0x9fc00000`, EL2h | Same PC, EL1h |
| After first FV instruction | PC `0x9fc0cc50`, no EL2 fault | Same PC, no EL2 fault |
| SEC startup | `0x9fc0cd80`, x0=0 | Same zero-x0 path |
| After current-EL M/C/I helper | SCTLR_EL2=`0x8000a` | EL1 M/C/I off; SCTLR_EL2 retained |
| CurrentEL read | x0=8 | x0=4 |
| Common startup path | `0x9fc0ce7c` | Same common path |
| SCTLR_EL1.WXN | Set to `0x800000` from the synthetic zero initial value | Same |
| EL2 HCR helper | HCR_EL2 changes `0x80080005` → `0x10` | Helper skipped; HCR retained |
| After VBAR setup | PC `0x9fc0ceb4`, VBAR_EL2=`0x9ff8c000`, still EL2h | Same PC, still EL1h |

All DAIF masks remain set along the EL2 prefix. The stock control starts
with QHEE's original SPSR=`0x85`; it is not a fully masked Linux entry test.
Both GCC inputs produce the same modeled service-call sequence and ledgers:
241 PMIC assignments, one bridge creation/PRNG request, three late PRNG
requests and one PIL empty-list query. Those replies remain model assumptions.

The HCR write matters: SEC is not simply passing QHEE's controls onward.
In particular, RW/VM/TSC are no longer set in `0x10`. Current EL2 execution
continues in AArch64; lower-EL state and later handoff must be checked in the
subsequent initialization. This observation alone does not prove a later
transition to EL1 or establish the Linux EL2 contract.

QEMU is terminated while paused at the final checkpoint. The fixture-only
mode prevents an unbounded normal run of the original startup. The prefix
stops before vector-table stores, BSS clearing, stack initialization and
platform services. Pinned SEC literals identify the next workspace:
vector base `0x9ff8c000`, BSS base `0x9ff90000`, BSS size `0x40000`.
These locations are outside the loaded FV and its clean range; no claim is
made that their initial contents, ownership or physical cache state match
the phone.

## Correction: the earlier indirect XBL branch configures an interface

The previous milestone left the slot used by `br x1` at `0x14817c14`
unresolved and described it as a possible secure interface. Further pinned
static dataflow resolves a successful initializer path:

1. Initializer `0x14827648` constructs object `0x148b67a0`, placing vtable
   `0x1488b9f0` at object+8, then calls setter `0x14826ee4`.
2. The setter stores that object at global `0x148b6270`; getter `0x14826f34`
   returns the global to the APPSBL wrapper.
3. Vtable+`0x48` at `0x1488ba38` contains `0x14827850`.
4. That function branches to `0x148278cc`, which configures a 20-byte
   descriptor by copying from `0x1488bb70` to `0x1488bb48`.

This path does **not** transfer to TZ. It is conditional static evidence;
executed initialization and the live pointer are not captured.

A separate later routine at `0x14817908` copies `0xe00` bytes from incoming
context+`0x18` to fixed buffer `0x80716100`, performs cache maintenance and,
on its inspected success branch, invokes the generic SMC wrapper at
`0x14817acc`. The call is x0=`0x82000114`, x1=`0x22`,
x2=`0x80716100`, x3=`0xe00`, x4–x7=0. The actual SMC instruction is
`0x1482c50c`. Its service semantics, populated buffer and secure-side dispatch
are not established by these windows. It is the next concrete secure-side
boundary to trace; do not substitute the descriptor-copy branch for it.

## Next steps toward CPU0 KVM

1. Trace TZ's handling of the later `0x82000114` call and the fixed buffer,
   tying actual QHEE target/width/cold arguments to the XBL configuration.
2. Extend only the required SEC startup boundaries beyond the current stop:
   establish workspace and register initialization before modeling any
   needed firmware service. Check where later UEFI/ABL code resets HCR or EL.
3. Select the smallest diagnostic transition that can reach the desired
   hardware boundary. Validate kernel/DTB cache placement, masks, timer/GIC,
   SCR/PSCI and reservations for a Linux handoff. Establish changed-image
   acceptance and recovery independent of ABL before an early-firmware test.
4. On physical EL2 Linux, require `/dev/kvm` and a checked one-vCPU guest run
   before resuming Ubuntu/Android and shared-resource work.

## Reproduction and evidence

```sh
python3 tools/hyp_re/test_xbl_target.py
python3 tools/hyp_re/test_xbl_prefix.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/xbl-prefix-regressions
```

All **764 checks across 30 suites pass**. The five new prefix cases include
four full cold-path execution combinations, exact transition/range guards,
original FV pinning, fixture-only CLI rules, and rejection of tampered payload
metadata, bytes or loader address. Two additional XBL static cases distinguish
the interface configuration from the later fixed-buffer SMC.

- `reports/qhee-offline/xbl-target-static/manifest.json`: bounded original
  table, interface/SMC windows and SEC workspace literals.
- `kernel-work/out/qhee-xbl-prefix-tests/{off,on}-{stock,el2}/`: fixture
  manifests, original FV bytes, generated GDB scripts and read-only traces.
- `reports/qhee-offline/xbl-prefix-regressions/results.json`: suite results.
- `reports/qhee-offline/xbl-prefix-milestone.json`: verified evidence hashes
  and limits of this milestone.

Physical Linux was last verified on October 5 at EL1 without `/dev/kvm`.
This milestone performed no phone access or firmware partition write.
