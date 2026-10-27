# CPU0 EL2 entry investigation — 2026-10-06

The complete modeled cold path now tests the SPSR-only change, rather than
only an extracted dispatch slice. It selects EL2h but fails the first probe
instruction fetch. The immediate obstacle is QHEE's EL2 stage-1 execute
permission and retained MMU/cache state. Physical Linux/KVM remains unproven.

## Full-path differential experiment

`run_qemu.py --handoff-experiment spsr-el2h` changes exactly one instruction in
the emulator's loaded copy of the pinned QHEE code:

| Address | Original | Loaded experiment |
| --- | --- | --- |
| `0x800401d8` | `0xd28010a5`, SPSR value `0x85` | `0xd2807925`, SPSR value `0x3c9` |

The original backup, ELF metadata and embedded digest are untouched. This is
not a flashable firmware image. The option requires the full bridge/PRNG
models and explicit synthetic probe target `0x90000000`. The tracer recomputes
the expected loaded bytes from the original pinned firmware and checks both
the metadata and actual loaded file before starting QEMU.

All preceding initialization requests and the first seven bridge checkpoints
match the original-code run. Both GCC initial-state experiments (`off`, `on`)
complete the same 241 PMIC mappings, bridge creation and PRNG replies. QHEE
has enabled its CPU MMU by the final handoff in both runs.

| Observed point | Original | SPSR experiment |
| --- | --- | --- |
| Before ERET at `0x80040328` | SPSR `0x85` | SPSR `0x3c9` |
| SCTLR_EL2 / HCR_EL2 | `0x8100f` / `0x80080005` | Same |
| Immediately after ERET | PC `0x90000000`, EL1h | PC `0x90000000`, EL2h |
| First instruction fetch | PC advances to `0x90000004` | EL2 vector `0x80093200` |
| ESR_EL2 / FAR_EL2 | No exception | `0x8600000e` / `0x90000000` |
| Normal run outcome | Probe prints `EL1`, exits cleanly | QHEE fatal watchdog request |

The EL2 instruction abort is a level-2 permission fault. Read-only walks show
TCR_EL2=`0x8081351c`, TTBR0_EL2=`0xb7700000` and a level-2 descriptor
`0x50000090000705` for the probe: execute permission is denied. QHEE's own
code has a separate executable level-3 descriptor `0x10000080040787`.
The probe's original stage-2 descriptor `0x100000900004fd` permits the
successful stock EL1 fetch. EL2 stage-1 permissions and guest stage-2
permissions must be evaluated separately.

SCTLR_EL2 retains M/C/I enabled. Selecting EL2 with SPSR alone cannot provide
the required Linux entry environment. The immediate payload also receives
zero in every x0–x30 register; it does not receive a Linux DTB argument.

## Pinned XBL and ABL inventory

`bootchain.py` validates the backup hashes and parses bounded ELF, firmware
volume, FFS, section, TE and PE32+ structures. It expands the ABL LZMA-guided
volume with explicit output, memory and recursion limits. It deliberately
does not expand XBL's compressed DXE volume. Saved instruction candidates
come from aligned executable-section sweeps, not recovered control flow.

| Image | Container evidence | Contained executable |
| --- | --- | --- |
| XBL | ELF64; firmware volume at `0x9fc00000` | AArch64 TE SEC; address-derived entry `0x9fc0cc50` |
| ABL | ELF32; firmware volume at `0x9fa00000` | AArch64 PE32+ `MotoBootModule`, preferred base zero; runtime address unknown |

The first branch at the XBL volume base targets the contained SEC entry.
This is static address agreement, **not a capture of QHEE's incoming x0**.
ABL's ELF32 wrapper does not make its contained module AArch32.

The pinned SEC entry checks x0. Its x0-zero branch reaches startup at
`0x9fc0cd80`. The following conditional path is present in that startup:

1. Mask IRQ/FIQ, call the current-EL M/C/I-disable helper, invalidate the
   instruction cache and invalidate the current-EL TLB.
2. Test CurrentEL. EL1 and EL2 both branch to `0x9fc0ce7c`; the separate EL3
   path is not taken by an EL2 entry.
3. At EL2, pass `0x10` to the HCR_EL2-write helper at `0x9fc182f4` and choose
   VBAR_EL2 through the current-EL vector helper.

The M/C/I helper preserves other SCTLR bits, writes SCTLR_EL2 at
`0x9fc17f20` on its EL2 branch, then uses DSB/ISB. Its presence does not
establish prior cache cleaning to the point of coherency. This path proves
that SEC contains EL2-aware code; the complete UEFI/ABL path has not been
executed or established as compatible with EL2. Later modules can still
change the exception level, trap configuration or firmware service contract.

Existing `reports/nio-boot-attempt-4/logfs/Log01.txt` records QHEE loading
before UEFI starts. It does not record the incoming target, width or arguments.
No fresh phone access or boot-chain register capture occurred in this work.

## Next implementation gates

1. Establish the real XBL/TZ-to-QHEE target and argument contract, then trace
   the UEFI/ABL kernel-launch path and required QHEE services. Treat the SEC
   address as a candidate until the actual incoming contract is established.
2. Build an emulator-only terminal transition in verified executable,
   identity-mapped memory. Account for its code, stack, vectors and memory
   reservations before changing MMU state. Validate cache cleaning and
   instruction coherency, DAIF, HCR/SCTLR, timers and the post-transition fetch.
   A debugger page-table/register override is not an implementation.
3. Validate a small EL2 diagnostic first. Then meet the pinned Linux
   `Documentation/arch/arm64/booting.rst` contract: MMU off, kernel clean to
   PoC, interrupt masks and the required timer/GIC state, with physical DTB
   in x0 and x1–x3 zero. Verify the intervening firmware preserves this path.

Firmware acceptance and restoration independent of ABL remain separate
hardware-test gates. No hyp/XBL write is authorized or performed by these
offline experiments. After a recoverable physical EL2 boot, the acceptance
test is actual execution of one tiny KVM guest on CPU0.

## Reproduction and evidence

From the project root:

```sh
python3 tools/hyp_re/test_entry.py
python3 tools/hyp_re/bootchain.py
python3 tools/hyp_re/test_bootchain.py
python3 tools/hyp_re/check_all.py
```

All 736 checks across 26 suites pass: the previous 713 plus eight entry
test cases and fifteen boot-chain test cases. Subcases additionally cover
both clock inputs, stock/changed loaded code, exact ledgers, fetch outcomes,
CLI dependencies and tampered trace inputs. Malformed-container tests cover
bounds, truncated LZMA, FV checksum and invalid TE/PE entries.

- `kernel-work/out/qhee-entry-tests/{off,on}-{stock,spsr-el2h}/manifest.json`:
  complete commands, model assumptions, original/loaded code hashes and stops.
- Their `trace/manifest.json`: read-only checkpoints, ledgers, EL2 stage-1
  walks, stage-2 walks and two normal instruction steps across ERET.
- `reports/qhee-offline/bootchain-static/manifest.json`: pinned container and
  extracted-image hashes, bounded instruction candidates and SEC windows.
- `reports/qhee-offline/entry-regressions/results.json`: all suite results.
- `reports/qhee-offline/entry-contract-milestone.json`: aggregate evidence
  hashes and scope of this milestone.

All earlier model assumptions still apply, including replaying EL1 postboot
captures at cold EL2, synthetic query/mapping/ownership replies, an empty PIL
list and deterministic PRNG data. No physical TZ enforcement, changed-image
acceptance, Linux-at-EL2 execution or physical KVM result is inferred.

Follow-up: [the bounded diagnostic terminal transition](EL2-diagnostic-transition.md)
now executes the probe at EL2 with M/C/I off and unchanged page tables.
The 736-check report above records this earlier control/inventory milestone;
the current diagnostic-transition aggregate has 744 passing checks.
