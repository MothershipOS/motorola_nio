# SEC selector replay and QUP hardware-version boundary — 2026-10-06

Original SEC now consumes the exact measured selector word, selects and stores
its original platform descriptor, matches the copied descriptor ID in its
original table, executes the no-op hook, and reaches its next MMIO read.
Ten full profiles preserve the current EL throughout: diagnostic execution
retains EL2, while stock EL1 remains the comparison control. The current
milestone has **878 passing checks across 43 suites**, including nine new
tests, 15 device contracts and four earlier/default stop controls.

The next read is uint32 `0x00ac0004` at PC `0x9fc220fc`. The current model
aborts there at either EL, paused before the vector handler. Local Linux
6.18.54 sources identify that address as QUPv3 wrapper 1's hardware-version
register. The phone reports the wrapper's AHB clocks disabled; no physical
QUP register read or clock write was attempted in this milestone.

## Exact selector replay

The prior phone capture contains two successful fixed uint32 reads of
`0x01fc8004`, both returning zero, with diagnostic Linux/EL1 context.
`xbl_selector.sample()` requires those exact successful commands, one uint32
per result, identical repeated values and the captured kernel/EL1 context.
Metadata pins the capture and parser hashes.

`run_qemu.py --xbl-selector-sample reports/nio-platform-selector-20261006/manifest.json`
requires prepared original XBL, the existing SoC-version input and measured
SEC hold-flag replay. Earlier exact reply dependencies remain enforced.
The existing `nio-soc-version` device gains a separately default-disabled
selector option. Its original four-byte mapping remains when this option is
disabled; enabling it maps the adjacent selector word as well.
The selector at offset four accepts one uint32 read only after a successful
exact hardware-version uint32 read. It returns the supplied captured value
and logs `NIO_SEC_SELECTOR_READ`; subsequent selector reads, missing
prerequisite, writes, unsupported widths and neighbors fail. Re-reading the
hardware-version word cannot rearm the selector.

Reusing a postboot EL1 observation at modeled SEC entry and diagnostic EL2
remains an explicit assumption. The device's prior-read guard is a bounded
model ordering check, not proof of a real cold firmware or access-policy state.
No general register bank or firmware response was introduced.

## Original descriptor selection and continuation

The original `ldr w8, [x8]` at `0x9fc2a150` reads the replayed zero. SEC masks
bits 1:0 and compares them with one. The original conditional selection is:

| Low bits | Descriptor | MMIO bases |
| --- | --- | --- |
| Exactly `1` | `0x9fc35728` | `0x00988000`, `0x009c0000` |
| Otherwise | `0x9fc356e0` | `0x00a90000`, `0x00ac0000` |

Eight original-instruction Unicorn leaf controls cover all low-bit values,
upper-bit variations and the maximum uint32 input. They perform exactly one
selector read, no memory writes, and preserve SP. The alternative descriptor
is a slice control only; the ten full paths all use the captured zero.

The wrapper stores the selected pointer at `0x9fc3d720`. The original
initializer unwinds to SP=`0x9ffcfac0`, reads its copied ID `0x1c200`, and
matches the record at `0x9fc32600`. The no-op hook at `0x9fc22bf0` receives
argument `0x708000` and returns zero. Traces check the pointer, original
72-byte descriptor contents, match record and argument.

The selected second base is `0x00ac0000`. Original code adds four and reaches
`ldr w11, [x8]` at `0x9fc220fc`. The tracer stops before that instruction by
default. `--inspect-xbl-next-step` attempts it once and records:

| Path | Exception level | Syndrome | FAR | Vector PC |
| --- | --- | --- | --- | --- |
| Stock | EL1 | `0x96000010` | `0x00ac0004` | `0x9ff8c200` |
| Diagnostic | EL2 | `0x96000010` | `0x00ac0004` | `0x9ff8c200` |

ELR is the original load PC. No vector handler is executed. Earlier
`--xbl-counter` controls still stop before the selector and do not consume
its replay. Four controls verify earlier and default unstepped boundaries.

## Width handling and regression coverage

Extending the device to cover two neighboring words exposed a TCG behavior:
with a four-byte implementation limit, an aligned eight-byte base load was
split into two individually permitted callbacks and could complete when the
selector option was enabled. The device now delivers aligned eight-byte
accesses intact to its callback, which explicitly rejects non-four-byte reads.
A regression proves that the aligned wide base transfer fails without
consuming the selector.

An unaligned eight-byte load starting at the selector crosses the region end.
TCG still splits it: the allowed four-byte selector half is consumed, then the
neighbor aborts. It never completes an eight-byte transfer. This partial-read
behavior is recorded explicitly rather than claimed to be a zero-side-effect
width rejection. The original SEC uses a single four-byte load.

Fifteen architectural device controls cover zero/nonzero fixture values,
default-disabled state, missing prerequisite, repeats including a repeat after
another version read, small/wide accesses, writes, the neighbor and preserved
repeated base reads. Earlier SoC-register/secure-call tests remain in the full
regression run.

Every full profile also checks cache/hypervisor controls, EL/interrupt masks,
canary and exact reply ledgers, workspace guards, unchanged timer/SIMD controls,
and the stored counter result. The original 263 cold QHEE calls, 241-entry
PMIC ledger and stock-versus-EL2 buffer forwarding counts stay unchanged.
QEMU's 62.5MHz counter versus firmware's 19.2MHz conversion remains a recorded
timing limitation.

## Next implementation step

The pinned SM8250 DTS maps QUP wrapper 1 at `0x00ac0000` and serial engine 12
at `0x00a90000`. Its wrapper driver defines `QUPV3_HW_VER_REG=4` and reads
`wrapper->base + QUPV3_HW_VER_REG`. This identifies the next register without
inventing its value. Source hashes and exact matching statements are recorded
in `selector-static/register-identity.json`.

The read-only phone clock inspection reports both wrapper 1 AHB clocks with
zero prepare/enable counts and hardware-enabled `N`. These are postboot clock
observations, not a cold-entry capture. The attached serial device is bound,
but reports runtime status `unsupported`; changing `power/control` alone is
not a demonstrated way to acquire these clocks.

Prepare a narrow kernel diagnostic that acquires the existing wrapper clocks
through the clock framework, enables them with balanced references, reads
only the fixed version word, and releases them on success or error. Obtain
repeated values and context before adding a bounded version replay. This avoids
raw clock-register pokes and a made-up QUP bank. Follow the original version
comparison to the next required access after that gate.

Physical KVM still requires Linux to receive EL2. Cold monitor records,
hold-flag entry state/publisher, complete UEFI/ABL/Linux entry, image acceptance,
and recovery independent of ABL remain open. No firmware or partition was
written, and this milestone does not create a flashable firmware candidate.

## Reproduce and evidence

```sh
python3 tools/hyp_re/build_qemu_model.py --jobs 8
python3 tools/hyp_re/xbl_selector.py
python3 tools/hyp_re/test_selector.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/selector-regressions
```

- `reports/nio-platform-selector-20261006/`: prior repeated selector capture.
- `reports/nio-qup-wrapper-clocks-20261006/`: read-only phone clock inspection.
- `reports/qhee-offline/selector-static/`: original windows, eight selection slices and primary-source register identity.
- `kernel-work/out/qhee-selector-tests/results.json`: ten full profiles and fault controls.
- `kernel-work/out/qhee-selector-tests/device-contracts/results.json`: 15 device controls.
- `kernel-work/out/qhee-selector-tests/earlier-controls.json`: four earlier/default stops.
- `reports/qhee-offline/selector-regressions/results.json`: full regressions.
- `reports/qhee-offline/selector-milestone.json`: verified current evidence inventory.
