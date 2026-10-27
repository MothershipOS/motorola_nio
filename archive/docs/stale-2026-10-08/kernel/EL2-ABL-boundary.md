# Original ABL kernel-launch boundary — 2026-10-06

The pinned Motorola ABL preparation and AArch64 launch instructions preserve
EL2 in an isolated emulator test. They clear M/C/I and forward the seeded
DTB-pointer token in x0, with x1–x3 zero. This narrows the later boot-chain
question: this terminal boundary does not inherently drop an EL2 caller to
EL1. It does not prove the earlier UEFI/ABL stages can execute at EL2.

## Pinned instruction evidence

The compressed `MotoBootModule` is mapped from the original ABL backup with a
bounded PE32+ loader. The synthetic base is `0x90000000`; the real runtime
base remains unknown. All 1,242 DIR64 relocations are applied to the mapped
fixture; bounds, section overlap, relocation types/targets and overflow are
checked. The twelve inspected instruction windows remain byte-for-byte
original. Neither firmware backup nor executable instructions are patched.

All addresses below are module RVAs, not physical phone addresses.

| Boundary | Pinned evidence |
| --- | --- |
| Boot-services shutdown | Call at `0x61c00` to `0x5e140`; that routine calls a boot-services function at offset `0xe8` after obtaining a memory map |
| Platform preparation | Call at `0x61c08` to `0x5e2e0` |
| Preparation routine | Original mask/cache/translation helpers, with current-EL register selection |
| AArch64 launch block | `0x61da0..0x61db8` |
| Final transfer | `blr x8` at `0x61db4`, without an ERET in that block |
| Arguments | x8=`[x23-0x70]`, x0=`[x23-0x58]`, x1–x3 zero |

Routine names and the DTB interpretation correlate with the related public
[BootLinux implementation](https://github.com/SHIFTPHONES/android_bootable_bootloader_edk2/blob/72958bcc265c5d38c1c1ecdf567d88a73c549a81/QcomModulePkg/Library/BootLib/BootLinux.c#L976).
That source is context, not the Motorola vendor tree or a source/binary
identity proof. Its commit and downloaded-file hash are recorded separately.
The exact instructions and addresses above come from the pinned nio image.

## Isolated execution, not a full boot

`run_abl_boundary.py` executes the original preparation routine and final
launch block with synthetic EL3 setup, PE base, identity page tables, stack,
boot-parameter frame and diagnostic payload. It does **not** execute the
BootLinux caller, ExitBootServices, optional VM service calls, earlier UEFI
modules or QHEE. The DTB argument is a pointer token, not a Linux DTB.

Eight combinations pass: EL1/EL2 × CPU MMU/cache off/on × DAIF masked/unmasked.
These are CPU MMU states, distinct from the earlier GCC clock-input tests.
Each run executes unchanged ABL code and exits cleanly after the diagnostic.
Five read-only checkpoints observe fixture entry, original preparation entry,
preparation return, original BLR and payload entry. One normal instruction
step proves execution after arrival at the payload.

| Observation | Result |
| --- | --- |
| Exception level | EL1 remains EL1; EL2 remains EL2 through preparation and launch |
| M/C/I initially enabled | Original helpers clear all three bits |
| M/C/I initially disabled | They remain disabled |
| Other SCTLR bits | Preserved |
| Stack and HCR | Preserved across preparation |
| Launch x0 | Seeded `0x93000000` DTB-pointer token |
| Launch x1–x3 | Zero despite nonzero fixture seeds |
| Payload PC | Matches the original BLR's x8 target; first instruction executes |
| Initially fully masked DAIF | Remains fully masked |
| Initially unmasked DAIF | A/I/F become masked; D remains unmasked |

The final point matters for Linux preparation: the helper preserves the debug
mask bit. It does not establish all required DAIF masks independently of its
entry state. The actual earlier firmware state remains unmeasured.

The preparation chain includes cache set/way maintenance, current-EL cache
disables and current-EL MMU disable/TLBI. QEMU TCG does not model physical
dirty-cache or SM8250 system-cache coherency. Successful instruction execution
and cleared control bits do not prove physical kernel/DTB coherency.

## Earlier XBL target candidate

The pinned XBL configuration table at `0x14884690` has ten records with stride
`0x88`, followed by a terminator. Record 9 at `0x14884b58` has name `APPSBL`,
image ID 9, callback `0x14817b14` and configured-address field `0x9fc00000`.
The instruction at that configured address branches to SEC `0x9fc0cc50`.
This strengthens **`0x9fc00000` as a candidate entry**, separate from the
contained SEC address. It remains a static configuration field, not a capture
of QHEE's incoming x0 or its width/other arguments.

The callback searches the same table using stride `0x88` and image ID 9. Its
later wrapper transfers through a runtime interface pointer with `br x1` at
`0x14817c14`; the pointer is loaded from an interface slot at offset `0x48`.
At this milestone, the slot value, secure-side path and TZ-to-QHEE register
setup had not been resolved. The [subsequent prefix milestone](EL2-XBL-prefix.md)
traces the successful initializer to a descriptor-copy slot, correcting its
earlier possible-secure-interface interpretation. A separate later SMC is
recorded there; its secure-side setup remains open.

## Remaining blockers and next work

1. At this milestone: trace the runtime interface and TZ-to-QHEE argument setup. A narrow
   emulator test of the original XBL/SEC prefix at the configured candidate
   can follow, with synthetic entry arguments reported explicitly.
2. Establish earlier UEFI/ABL EL2 behavior and required hypervisor services.
   ABL contains GetVmData and an optional hypervisor-UART SMC path (`0x86000000`
   in the inspected caller). Their behavior after handing EL2 away from QHEE
   is not covered by this terminal-boundary test. Do not assume every EL1
   service call can be issued unchanged from EL2.
3. Validate real kernel/DTB placement, physical cache handling, full DAIF,
   timer/GIC/SCR/PSCI state and reservations against the pinned Linux boot
   contract. Then establish acceptance/recovery for a concrete hardware test.

This does not require adding unrelated device emulation or declaring a full
UEFI emulator mandatory for every firmware diagnostic. The purpose of the
bounded tests is to resolve specific handoff questions. Physical Linux is
still last verified at EL1 on October 5, without `/dev/kvm`; no phone action
or early-firmware partition write occurred in this work.

## Reproduction and evidence

```sh
python3 tools/hyp_re/xbl_target.py
python3 tools/hyp_re/test_xbl_target.py
python3 tools/hyp_re/test_abl_boundary.py
python3 tools/hyp_re/run_abl_boundary.py --entry-el 2 --initial-mmu on --initial-daif masked
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/abl-boundary-regressions
```

At this milestone **757 checks across 29 suites passed**: the earlier 744 plus eight ABL and
five XBL cases. The ABL execution case covers all eight state combinations.
Static loader tests cover relocation values, malformed mapping/relocation
bounds, overlap and unsupported relocation types. XBL checks cover the pinned
table/branch, unresolved interface boundary, read bounds and pin rejection.
Current results are in [EL2-XBL-prefix.md](EL2-XBL-prefix.md): 764 checks across
30 suites, including original SEC execution after full modeled cold QHEE.

- `reports/qhee-offline/abl-boundary-static/`: original instruction windows,
  PE mapping metadata and pinned public source context.
- `reports/qhee-offline/xbl-target-static/`: table records, original callback
  windows and configured entry branch.
- `kernel-work/out/abl-boundary-tests/el{1,2}-{off,on}-{masked,unmasked}/`:
  exact commands, mapped PE/source hashes, normal-run output and checkpoints.
- `reports/qhee-offline/abl-boundary-regressions/results.json`: all suite results.
- `reports/qhee-offline/abl-boundary-milestone.json`: aggregate evidence hashes
  and the limits of this milestone.
