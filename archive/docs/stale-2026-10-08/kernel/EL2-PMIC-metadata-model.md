# PMIC metadata replay — 2026-10-05

Historical 580-check milestone. The follow-up [late-init model](EL2-late-init-model.md)
adds finite PMIC mapping replies and advances to SHM bridge creation.

Original, unpatched QHEE now completes its PMIC metadata scans offline and
reaches a new secure-monitor call, `0xc2000c19`, from the PMIC access-control
path. The call has five scalar arguments:
`[0x0ccf0000, 0x0cd00000, 2, 6, 1]`. No response has been modeled for it.
The complete payload handoff and physical KVM remain open.

## Measured inputs and bounded replay

Three independently enabled captures supply read-only metadata. They do not
issue SPMI commands, modify PMIC registers, or implement ownership enforcement.

| CLI option | Captured words | Address range, inclusive | Evidence |
| --- | --- | --- | --- |
| `--pmic-arb-sample` | 512 APID mapping words, 354 nonzero | `0x0c440900–0x0c4410fc` | `reports/nio-pmic-arbiter-20261005/manifest.json` |
| `--pmic-owner-sample` | 512 ownership words | `0x0c40a700–0x0c40aefc` | `reports/nio-pmic-owners-20261005/manifest.json` |
| `--pmic-secondary-sample` | 256 secondary mapping words, 146 nonzero | `0x0c442300–0x0c4426fc` | `reports/nio-pmic-secondary-map-20261005/manifest.json` |

The owner capture contains values 0 (259 entries), 1 (12), and 4 (241).
All three captures report arbiter version `0x50010000`. Their raw output and
exact commands are retained. The phone remained in diagnostic Linux throughout.
These are EL1 postboot observations; replaying them at cold EL2 remains an
explicit assumption.

The live DT places the APID words in the SPMI core aperture and the owner words
in its configuration aperture. The pinned Linux 6.18.54 source,
`drivers/spmi/spmi-pmic-arb.c`, supplies the v5 APID offset `0x900 + 4*n` and
owner offset `0x700 + 4*n`; its initialization reads both as metadata. The
[upstream driver](https://github.com/torvalds/linux/blob/master/drivers/spmi/spmi-pmic-arb.c)
is the public primary reference for the driver family; the pinned local
source is the evidence used for this device.

The secondary table is outside the DT core aperture. Its exact 256-word bound
comes instead from the original QHEE descriptor at `0x800a4f46`, offset `0xe`,
and the read-only loop at `0x80060d98`. That loop extracts SID/peripheral fields
and updates QHEE's in-memory mapping records. A channel-mapping role is inferred
from this consumer; a definitive public register name has not been established.
No unrelated register aperture was swept.

`pmic.py` validates exact successful read commands, version, row counts,
ordered addresses, uint32 syntax and first-APID consistency. It writes compact
little-endian snapshots for `nio-pmic-arb.c`. Only aligned 32-bit reads in the
enabled tables succeed. Other widths, misaligned reads, holes and every write
abort. The guarded apertures are `0x0c440000`/`0x3000` and
`0x0c40a000`/`0x1000`; holes do not return invented zeroes. The captured version
is used to validate the layout, not to enable another MMIO read.

Owner replay requires APID replay; secondary replay requires owner replay.
The model rejects missing/wrong-sized files at realization and does not infer
missing tables from the firmware or return generic success.

## Observed execution and new boundary

| Enabled PMIC tables | Observed next stop |
| --- | --- |
| None | Read `0x0c440900`, PC `0x80060d40` |
| APID only | Read `0x0c40a700`, PC `0x80061020` |
| APID and owner | Read `0x0c442300`, PC `0x80060d98` |
| All three | SCM `0xc2000c19`, return PC `0x80041aa4`; no MMIO fault |

With all tables enabled, QHEE makes 866 APID reads (512 scan reads plus 354
re-reads), 354 owner reads and 256 secondary-map reads. The regression suite
checks the entire address/value sequence against the captures, including repeat
reads. Both initial GCC clock states reach the same SCM call.

`trace_init_tail.py --through-pmic-tables` now records eleven read-only
checkpoints through the second table's first read. `--through-pmic-scm` adds
the pending SCM call as a twelfth checkpoint. Breakpoints are disabled after
their first matching hit; the SCM breakpoint filters the FID before recording.
Only registers, bounded stack frames and the known argument buffer are read.
No QHEE instructions, registers, arguments or page tables are patched.

At the pending call:

| Field | Observed value |
| --- | --- |
| FID / arginfo | `0xc2000c19` / `5` |
| x2 / x3 | `0x0ccf0000` / `0x0cd00000` |
| x4 | `2` |
| x5 | `0x801cc390`, the extended argument buffer |
| Extended scalar arguments | `6`, `1` |
| x6 / x7 | 0 / 0 |
| Candidate return-PC chain | `0x80048690 → 0x80067acc → 0x8005ff68 → 0x80044160 → 0x80040170` |

The inspected buffer also contains two trailing words `0x30`, `0`; they are
not additional arguments to this five-argument call. Its start/end describe a
64 KiB interval in the SPMI channel aperture. Original code at `0x80061ac4`
and `0x80061ad8` constructs channel base + index*64 KiB; `0x80067abc` computes
the exclusive end. The caller passes this through its generic region-mapping
path. Values 2/6/1 are consistent with destination VMID, permissions and a
mapping operation, respectively, but the full TZ contract and reply semantics
have not been established. No matching physical SCM request was issued.

Next trace the service contract and the caller's remaining region requests,
then decide whether an exact optional response/ledger model is justified.
Do not reuse the earlier `0xc2000c16` assignment contract: this call uses a
different FID, scalar arguments and caller. Keep unknown requests terminal.

## Validation and reproduction

The milestone has **580 passing checks**: all previous 477, 96 PMIC replay
checks and seven differential trace/dependency checks. The new tests read every
captured word twice, validate widths/addresses/write denial, reject malformed
captures and snapshot sizes, and verify exact full-firmware read sequences,
checkpoint order and SCM arguments under both clock initial states.

```sh
python3 tools/hyp_re/build_qemu_model.py
python3 tools/hyp_re/test_pmic.py
python3 tools/hyp_re/test_pmic_trace.py
python3 tools/hyp_re/trace_init_tail.py \
  --manifest kernel-work/out/qhee-pmic-trace-tests/complete-off/manifest.json \
  --through-pmic-scm \
  --out reports/qhee-offline/pmic-scm-checkpoints
```

`test_pmic_trace.py` contains the complete explicit run arguments. Canonical
runs are under `kernel-work/out/qhee-pmic-trace-tests/complete-{off,on}/`;
each has its own checkpoint manifest. Sources, captures and runs are hashed
in `reports/qhee-offline/pmic-milestone.json`. All 19 test scripts and the four
original MMU debugger checks were rerun; logs are in
`reports/qhee-offline/pmic-regressions/`.

Earlier successful-response and SMMU/clock assumptions still apply, including
the IsDeviceNonSecure unsupported-response experiment. No firmware partition
was written. Linux remains at EL1; the current result does not prove TZ
acceptance, a complete EL2 handoff, or KVM execution. The CPU0 firmware-test
scope and independent recovery questions remain in [KVM-PLAN.md](KVM-PLAN.md).
