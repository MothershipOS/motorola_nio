# Original TZ eight-byte buffer contract — 2026-10-06

Original TZ slices now trace the `0x02000a01` request from typed argument
validation through its registered handler and selected PRNG backend. With
explicit successful ownership/setup/cache assumptions and finite synthetic
FIFO samples, the original eight-byte loop, handler and marshaller produce
`status=0, bytes=8`. Nine new tests cover ten captured requests, rejection
boundaries, FIFO filtering/copy bounds and short-output handling.

The complete offline milestone has **824 passing checks across 37 suites**.
The full boot harness still stops before the buffer SMC at `0x9fc28468`.
These slices establish a narrow contract for the next response model; they do
not establish physical secure-service acceptance or supply real entropy.
No phone access or firmware write occurred. Linux at EL2 and KVM remain open.

## Typed request and pointer checks

The pinned registry entry for `0x02000a01` has argument info `0x22`, flags 1,
and callback `0x1c054b30`. The first argument is a type-2 buffer, followed by
its scalar length. This matches RW-buffer encoding in the local Linux SCM
header. Original SMC32 normalization truncates the arguments to 32 bits.
Count mismatches stop with -5; incompatible argument types stop with -10.

All ten previously captured stock/diagnostic requests reach the typed pointer
checker at `0x1c065c28` in the constructed register-frame fixture. Its result
is pending, not successful validation. The dispatcher/context metadata that
constructs the real secure caller frame remains unexecuted. In particular,
this fixture uses the captured x7 value in input slot +0x38; original decoding
uses that slot to select a pointer-check variant. Do not treat this selection
as a measured secure context or caller-policy decision.

The separately seeded original marshaller takes its two-argument branch at
`0x1c0679f0` and calls the registered handler with:

```text
x0 = 0x9fc356c0          requested buffer
x1 = 8                   length
x2 = marshaller scratch  result words
```

The handler rejects a null pointer or a length outside 1–512 before its own
pointer checker at `0x1c065b0c`. Neither prefix writes the requested buffer.
The inherited diagnostic x6 value is never dereferenced in these slices.

The two pointer-check fronts have distinct permission masks. They mask
interrupts, take a lock, attempt address translation and query ownership;
the handler variant tries several masks. These runtime dependencies have no
invented success result in the prefix traces. A separate original arithmetic
slice at `0x1c065a74` checks wraparound/end bounds, rounds the requested range
outward to pages, and stops before ownership lookup at `0x1c0c0b68`:

```text
0x9fc356c0 + 8 -> page 0x9fc35000, length 0x1000
```

Empty/overflowing ranges and ranges too near the address-space end return
false. Page rounding is executable evidence; actual ownership is unresolved.

## Selected backend and finite FIFO execution

After explicitly seeding successful pointer acceptance, original handler
instructions select the driver table at `0x1c11b5a8` and enter the random
wrapper at `0x1c03d0d0`. The file-backed backend pointer at `0x1c03b050`
selects `0x1c042c8c`. Execution stops at its state callback `0x1c0549c8`
before the first runtime state write. A separate slice seeded after that
callback reaches the original clock front at `0x1c0666dc`, with index 4,
without supplying a clock response.

The pinned driver table identifies MMIO base `0x00791000` and original copy
callback `0x1c050c88`. These are image values; their active secure-runtime
contents are unverified. Static backend instructions show configuration writes
and polling before the FIFO loop. The loop itself is independently executed
from `0x1c042df8` after explicit successful setup assumptions:

1. Read ready bit 0 at base +4.
2. Read a first FIFO sample at base; retry if its low 16 bits are zero.
3. Read ready again, then a second sample; retry if it is below `0x10000`.
4. XOR the pair and use the original copy wrapper to write up to four bytes.
5. Repeat until the eight-byte request is filled, then stop before release.

The finite fixture supplies four ready reads and exactly four FIFO samples:

| Sample pair | XOR word | Written little-endian bytes |
| --- | --- | --- |
| `0x11223344`, `0x55667788` | `0x444444cc` | `cc 44 44 44` |
| `0x99aabbcc`, `0xddeeff11` | `0x444444dd` | `dd 44 44 44` |

Original instructions perform the filtering, XOR, bounded copy and loop count.
The output contains exactly eight bytes and retains both sixteen-byte guards.
Unknown MMIO accesses, excess polls, depleted samples, unexpected writes and
unmapped instructions fail closed. Alternate sample pairs change the output;
filtered samples exhaust the finite fixture rather than gaining new entropy.

## Handler return and assumptions at slice joins

A separately seeded continuation restores the original pre-backend register
frame/SP and supplies the fixture-derived bytes and produced count. Original
handler instructions publish the count and two zero result words, then stop
at their cache helper `0x1c0c72e4`. After an explicit cache-completion
assumption, the handler compares produced/requested counts, returns success,
and the original marshaller copies the result words:

```text
x0 = 0, x1 = 8, x2..x7 = 0
```

Produced counts zero or four take the original error-logging boundary at
`0x1c04d62c`; those traces have no fabricated completed reply.

Every join is recorded in the output: successful secure policy and both
ownership checks; backend state/clock/setup and finite FIFO inputs; successful
backend release/return; and completed cache maintenance. Code bytes are never
patched and original instructions run continuously within each slice. This is
not uninterrupted TZ execution. Accounting/locking/translation/ownership,
active runtime driver state, hardware readiness/entropy, monitor return and
physical coherency remain unverified.

## Next implementation order

1. Add only an opt-in, exact, one-shot buffer response to the offline EL3
   harness. Use these bytes explicitly as an entropy fixture, check the actual
   stock/EL2 call sites and arguments, and preserve adjacent buffer/selector
   data. Keep the earlier pre-SMC boundary available.
2. Continue original XBL through source/cache update and stack-sizing return.
   Verify the resulting stack adjustment, then stop at the next concrete
   dependency. This is branch/dataflow coverage under assumptions.
3. Preserve the bootstrap-record, Linux-entry, image-acceptance and independent
   recovery gates in [KVM-PLAN.md](KVM-PLAN.md). One physical CPU0 KVM guest
   remains the first hardware target.

## Reproduce and evidence

```sh
python3 tools/hyp_re/tz_buffer.py
python3 tools/hyp_re/test_tz_buffer.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/tz-buffer-regressions
```

- `reports/qhee-offline/tz-buffer-static/`: original instruction windows,
  driver table, bounded traces, fixture inputs, joins and return frame.
- `kernel-work/out/qhee-tz-buffer-tests/results.json`: ten per-request slice
  results and immutable input-trace snapshots with hashes. Original trace paths
  may be regenerated by the query suite; snapshots retain the inputs used here.
- `reports/qhee-offline/tz-buffer-regressions/results.json`: complete regression results.
- `reports/qhee-offline/tz-buffer-milestone.json`: verified evidence inventory.

The earlier full-QHEE continuation to the request remains documented in
[original TZ query reply](EL2-TZ-query-reply.md).

The subsequent [original XBL stack-return milestone](EL2-XBL-stack-return.md)
adds exact buffer replay and reaches the adjusted SP before the next helper.
Original stock forwarding sets x7=3, selecting a different typed checker
from the earlier pre-forward x7=0 fixture; both remain pending policy/ownership.
