# SEC hold-flag replay and virtual-counter boundary — 2026-10-06

Original SEC now reads a measured postboot IMEM word, exits its conditional
hold loop, executes its no-op hook, and enters the platform initialization
prologue. Ten full modeled cases reach `0x9fc2bb48`, paused before the first
`CNTVCT_EL0` read. Diagnostic execution retains EL2, I/D enabled and translation
disabled; stock EL1 remains the comparison control.

The milestone has **860 passing checks across 41 suites**, including nine
new tests, 15 device contracts and four earlier stop controls.

The phone was checked in diagnostic Linux 6.18.54 at EL1, with HYP unavailable
and no `/dev/kvm`. Two fixed read-only checks of `0x146bf944` both returned
`0x3a6506a5`. No IMEM, firmware or partition write occurred; opening the
existing diagnostic console sets its usual RAM host-attached marker. The
capture is in `reports/nio-sec-flag-20261006/manifest.json`.

The word's publisher and real cold-entry state remain unverified. Reusing a
postboot EL1-visible value at modeled SEC entry and diagnostic EL2 is an
explicit assumption, matching the limited scope of earlier pointer replays.
This does not prove physical EL2 handoff, firmware acceptance or KVM.

## Original polling behavior and publisher limit

The helper at `0x9fc0e33c` loads address `0x146bf944` from its original base
and offset globals. It loops only while the four-byte word equals
`0x55444247`. Other values return. This is a conditional hold marker; treating
any nonzero value as a universal readiness bit would misdescribe the code.

An original-instruction Unicorn slice verifies nonheld values, a held value
that exhausts its finite observations, and an explicitly synthetic sequence
of two held values followed by release. That last fixture is a loop-behavior
control, not a phone-observed publication or an enabled release model.

The bounded SEC consumer does not write the flag. Literal searches of pinned
XBL/QHEE/TZ/ABL images did not identify a publisher: the hold constant occurs
once in XBL's FV data and the complete flag address is not a literal in those
images. Instructions can construct addresses and values, and earlier/external
publishers remain possible. These limited searches do not establish absence
of a publisher. The model uses the measured value without claiming that this
producer/entry-state question has been solved.

## Exact one-read model

`run_qemu.py --xbl-readiness-sample reports/nio-sec-flag-20261006/manifest.json`
requires the earlier canary reply and exact QHEE IMEM publication models.
The parser requires two successful exact uint32 reads with the same value,
diagnostic-kernel context and captured EL1 context; metadata pins the entire
capture and parser source hashes.

The existing `nio-tz-log-pointer` device gains a separately disabled-by-default
flag option. It accepts exactly one four-byte read at offset `0x944`, after
both original QHEE log and ready publications have executed. It returns the
explicit sample value and records `NIO_SEC_FLAG_READ`. It rejects writes,
neighbors, missing publications and repeated reads. Other widths abort;
TCG splits the unaligned eight-byte probe into four-byte accesses, so that
probe consumes the allowed first half before aborting on the adjacent half.
It never completes an eight-byte read. The original caller uses a single
four-byte instruction, which the trace pins. Existing
TZ-log and publication contracts remain unchanged. There is no generic IMEM
storage or synthesized flag release.

The tracer validates metadata against its source capture and checks matching
device options. It performs no debugger register or memory writes. Earlier
canary/second-request stops remain available with the flag model enabled and
stop without consuming the flag read.

## Original execution after the flag

| Checkpoint | Observed result |
| --- | --- |
| `0x9fc0e380`, after the flag load | w9=`0x3a6506a5` |
| `0x9fc0e388`, before the conditional branch | Z clear; original code takes the nonheld path |
| `0x9fc0e320`, helper return | SP=`0x9ffcfce0` |
| `0x9fc1667c`, optional hook | one original `ret` |
| `0x9fc0d1e4`, platform main | x0=`0x9ff90000`, x1=`0x3fd00` |
| `0x9fc0d244`, before counter call | SP=`0x9ffcfbc0`; original frame holds copied canary at SP+`0x58` |
| `0x9fc19b5c` → `0x9fc27fdc` | two original branches |
| `0x9fc2bb48`, next instruction | `mrs x0, cntvct_el0`, not executed |

Canary value, all three reply ledgers, both SCTLR banks, HCR, EL and interrupt
masks remain unchanged. Workspace guards remain intact. Cold SCM calls remain
263, PMIC ownership entries remain 241, and later stock forwarding stays
separate. Each full case performs exactly one accepted flag read with no IMEM
access denial.

## Next step toward KVM

Execute and inspect the original architectural virtual-counter read and the
following frequency/conversion path at both EL1 and EL2. Establish any counter
access trap, offset/frequency assumption or next concrete platform dependency
before adding another model. The nearby MMIO counter helper at `0x9fc0e398`
is not the first timer accessor on this path; no MMIO timer model was added.

Cold flag state/publisher, bootstrap records, complete UEFI/ABL/Linux entry,
image acceptance and recovery independent of ABL remain open in
[KVM-PLAN.md](KVM-PLAN.md). Physical KVM still requires Linux to receive EL2.

## Reproduce and evidence

```sh
python3 tools/hyp_re/build_qemu_model.py --jobs 8
python3 tools/hyp_re/xbl_readiness.py
python3 tools/hyp_re/test_readiness.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/readiness-regressions
```

- `reports/nio-sec-flag-20261006/manifest.json`: repeated phone flag reads and
  kernel/EL1 context, with capture tool hash.
- `reports/qhee-offline/readiness-static/`: seven original windows, exact sample
  metadata and finite original poll controls.
- `kernel-work/out/qhee-readiness-tests/results.json`: ten full cases; original
  loop exit and counter boundary.
- `kernel-work/out/qhee-readiness-tests/device-contracts/results.json`: finite
  device acceptance/denial controls; `poll-contracts.json` records held/release
  slice behavior, and `earlier-controls.json` lists four earlier stops.
- `reports/qhee-offline/readiness-regressions/results.json`: full regression.
- `reports/qhee-offline/readiness-milestone.json`: verified evidence inventory.

## Subsequent milestone

The next trace now executes the counter read and fixed-frequency conversion,
then passes the SIMD constant load and descriptor copy. It reaches the
platform-selection uint32 read at `0x01fc8004`, which faults in the current
model. See [original counter and next MMIO boundary](EL2-XBL-counter.md).
The 860/41 counts and evidence above describe this historical readiness
milestone; the subsequent current milestone has 869 checks across 42 suites.
