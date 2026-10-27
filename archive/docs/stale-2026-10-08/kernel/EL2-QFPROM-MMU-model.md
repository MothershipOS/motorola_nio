# QFPROM replay and the missing SMEM mapping — 2026-10-04

## Result

The bounded QFPROM replay is implemented. Original QHEE reads the captured
word at 0x00784218 and advances to a different failure: an EL2 CPU translation
fault at VA 0x80901010, PC 0x8005ea9c, ESR_EL2 0x96000006. This is a level-2
translation fault, not an uncaptured SMEM byte or device-register fault.

This run still uses the explicit IsDeviceNonSecure unsupported-response
experiment. Without that option, the original query 0xc2000310 remains the
stop. No complete payload handoff, phone EL2 boot or working KVM is claimed.
The diagnostic USB interface was absent during this continuation; no phone
registers, fuses or firmware partitions were written.

## Implementation

`nio-qfprom.c` overlays the 4 KiB page at 0x00784000. Only a 32-bit read at
0x00784218 succeeds. All writes, other widths and other offsets fail. This
is a read-only replay device, not a QFPROM programming interface.

`run_qemu.py --qfprom-sample` validates the successful exact command and a
single 32-bit result from the existing captured manifest, and records its
SHA-256. The measured value is zero. Replaying a postboot EL1-visible word at
EL2 remains an assumption. The original firmware image is unchanged.

## Why SMEM is unmapped

A read-only debugger inspection stops at the first failing descriptor in the
initialization loop. At 0x8006781c the descriptor at 0x800a2984 is
`[5, 32, 36, 0, 0]` and the return code is 4. The SMMU path reports VMID 5
unsupported. The caller converts this into an initialization failure and
branches from 0x80065c70 to cleanup at 0x80065d48. The SMEM mapping routine
at 0x8005f8b8, normally called at 0x80065cc8, is skipped on this path.

At the subsequent failing SMEM load, QHEE's own CPU MMU state is:

| Register / entry | Value |
| --- | --- |
| TTBR0_EL2 | 0xb7700000 |
| TCR_EL2 | 0x8081351c |
| SCTLR_EL2 | 0x8100f |
| L1 entry covering QHEE/SMEM, at 0xb7700010 | 0xb7701003 |
| L2 entry covering 0x80901010, at 0xb7701020 | 0 |
| L2 entry covering SMEM TOC 0x80aff230, at 0xb7701028 | 0 |

The code at 0x80040000 and table memory at 0xb7700000 are mapped. Thus the
fault matches a specific missing mapping, not a generally broken CPU MMU.
No debugger register or page-table writes were used to obtain this evidence.

## Correction: Linux-visible SMMU IDs are filtered

QHEE registers a read handler at 0x8005c1e4 for each SMMU's first 0x2000 bytes
through the call at 0x8005a960. That handler treats offsets 0x20 and 0x24
specially. The following transformations are present in this exact backed-up
firmware:

- ID0 at 0x8005c3e4..0x8005c3f8: `(raw & 0xcfffff00) | visible_stream_count`.
  This clears stage-2 and nested-translation support bits (29 and 28) and
  replaces the low eight stream-count bits.
- ID1 through function 0x8005c158: subtract the per-SMMU reserved count at
  0x800a7520 from the low eight context-bank-count bits. The upper 24 bits,
  including NUMS2CB, are preserved by this code. They are not cleared here.

The pinned `drivers/iommu/arm/arm-smmu/arm-smmu.h` defines these ID fields.
`test_smmu_view.py` executes the original arithmetic/mask instructions under
QEMU, rather than testing a rewritten Python equivalent. Distinct raw ID0
inputs produce the same visible value. ID1 tests confirm subtraction and
preservation of upper fields. All inputs and reservation counts in these
instruction tests are synthetic examples, not newly measured raw phone IDs.

This establishes why the earlier EL1 capture must not be treated as raw EL2
hardware identity. It does not by itself prove the cause of every failed
VMID association. Initial-zero SMMU control state is also still an assumption.
Earlier GCC/SMMU tests prove bounded reset-path execution; they do not validate
successful access-control initialization or the raw device view.

## Next implementation target

Trace QHEE's context/stream allocation construction, particularly
0x8005d934..0x8005da64 and its inputs. That code builds the visible stream count
at 0x800a7518, reserved context count at 0x800a7520, and reserved stream count at
0x800a7528. Determine the VMID-5 association requirements and source each missing
raw-ID/boot-state field from firmware configuration or an appropriate measured
view. Capturing the same Linux-visible ID registers again cannot invert the
information discarded by ID0's filter.

Only then extend the minimal device model. Keep the current failing replay as
a regression. Do not force an SMEM mapping, return success from VMID setup, or
choose unmeasured ID bits merely to reach the synthetic payload. Resolving the
real incoming payload/boot-chain contract and recovery remains necessary for
physical KVM; see [KVM-PLAN.md](KVM-PLAN.md).

## Reproduce and validate

Take the full command in [EL2-GCC-MMU-model.md](EL2-GCC-MMU-model.md), add:

```sh
--qfprom-sample reports/nio-gcc-mmu-checkpoint-20260928/manifest.json \
--nonsecure-query-unsupported \
--out kernel-work/out/qhee-qfprom
```

Use one `--out` argument, replacing the earlier output directory. Then:

```sh
python3 tools/hyp_re/test_qfprom.py
python3 tools/hyp_re/test_smmu_view.py
python3 tools/hyp_re/inspect_qhee_mmu.py
```

The inspector requires `gdb-multiarch` and reuses a locally generated run
manifest. It checks the pinned firmware, stops at the failure, and reads the
physical page tables via QEMU's debugger. It does not access USB.

Validation: 182 existing regression checks rerun successfully, 25 new QFPROM
checks, seven original-instruction SMMU-view checks, and four debugger-state
checks: **218 checks total**. These are offline model/investigation checks.
Build and input hashes are in the reports. Key evidence:

- `reports/qhee-offline/qfprom-tests.json`
- `reports/qhee-offline/smmu-view-tests.json`
- `reports/qhee-offline/qfprom-mmu-inspection/inspection.json`
- `reports/qhee-offline/smmu-view-disassembly.txt`
- `reports/qhee-offline/qfprom-milestone.json`
