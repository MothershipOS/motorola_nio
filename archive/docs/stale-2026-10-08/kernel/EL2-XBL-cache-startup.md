# Original SEC cache startup and second buffer request — 2026-10-06

Original XBL now executes its set/way invalidation loop, enables instruction
and data caches at its existing exception level, and dispatches a second
eight-byte secure-monitor request for SEC's stack canary. Ten complete modeled
cold-path cases cover stock EL1 and diagnostic EL2, synthetic entry controls,
and TZ-derived entry controls with both HCR and GCC inputs.

The milestone has **842 passing checks across 39 suites**, including nine
new tests. The tracer stops before replying to the second request. The canary at
`0x9fc350a8` retains its original image value, `0xc0c0c0c0`. No phone access
or firmware write occurred. Linux at EL2 and a physical KVM guest remain open.

## Original cache execution

After [stack sizing returns](EL2-XBL-stack-return.md), SP is `0x9ffcfd00`.
Helper `0x9fc17b90` executes a barrier and dispatches the original set/way
loop at `0x9fc18200`, using callback `0x9fc17db0` (`dc isw, x0`). The code
reads CLIDR, selects cache levels through CSSELR, and reads CCSIDR to calculate
loop bounds. It preserves the caller's interrupt mask and stack on return.

The next two original SEC calls enable I and D in the SCTLR bank for the
current exception level. The other SCTLR bank and HCR remain unchanged.
Translation remains disabled in the XBL caller's bank.

| Path | Before cache startup | After I enabled | After D enabled |
| --- | --- | --- | --- |
| Stock EL1, SCTLR_EL1 | `0x800000` | `0x801000` | `0x801004` |
| Diagnostic EL2, SCTLR_EL2 | `0x8000a` | `0x8100a` | `0x8100e` |

These are QEMU results, not captures of the phone's caches. With the selected
Cortex-A76 model, executed cache-register reads and original loop bounds give:

| CSSELR | CCSIDR | Line bytes | Ways | Sets | Calculated set/way operations |
| --- | --- | --- | --- | --- | --- |
| `0` | `0x701fe01a` | 64 | 4 | 256 | 1,024 |
| `2` | `0x707fe03a` | 64 | 8 | 1,024 | 8,192 |

CLIDR is `0x82000023`. The 9,216 total is calculated from the observed bounds;
the tracer records two geometry checkpoints rather than every operation.
TCG does not prove physical dirty-cache maintenance or coherency. Entry fixtures
mask IRQ/FIQ, so this does not test actual interrupt delivery.

## Second request and distinct forwarding contract

Original canary initializer `0x9fc0cd44` calls `0x9fc1aa88`, which branches
to the source dispatcher. Selector `0x10` reuses the modern buffer path without
another availability query. XBL zeroes the same eight-byte buffer and reaches
`0x9fc28468` for the second time, with SP=`0x9ffcfce0`.

| Register | Original XBL second request | Original stock QHEE forwarding |
| --- | --- | --- |
| x0 | `0x02000a01` | same |
| x1 | `0x22` | same |
| x2 | `0x9fc356c0` | same |
| x3 | `8` | same |
| x4 | `7` | same |
| x5 | `0x1d` | same |
| x6 | `0x82000023` | zero |
| x7 | `0xffffffffffffffff` | `3` |

Stock EL1 traps into the original QHEE vector, then pauses before forwarding
SMC `0x80041aa0`, SP=`0x80208db0`. Direct diagnostic EL2 enters the synthetic
EL3 vector with saved return site `0x9fc2846c`, retaining the original request
registers. Both routing controls verify the saved caller PSTATE. CPSR is
normalized to its architectural 32-bit width because GDB may sign-extend it
when the N flag is set.

The first availability and buffer reply ledgers each remain one. The nibble
cache stays `0x0444444dd444444c`, and workspace sentinel guards remain intact.
Only the first buffer reply marker occurs. No second reply or canary store is
executed. Cold-path calls and later forwarding calls remain separate; each
stock handler record contains only the second request's forwarding call.

Actual x0–x13 snapshots feed the separately seeded original TZ buffer slices.
The decoder reaches pointer checker `0x1c065b0c`, with validation pending,
without dereferencing inherited x6. Under the existing explicit ownership,
backend, FIFO, cache and monitor joins, the slices derive status zero and count
eight. They do not prove physical secure-policy acceptance or entropy.

## Next step toward KVM

Add a separately guarded, second-occurrence buffer fixture reply using this
captured request and state. Then trace the original canary store and stop at
the first concrete SEC-main dependency. Keep the first reply one-shot and
retain earlier stop boundaries.

The remaining bootstrap-record bridge, complete UEFI/ABL/Linux entry contract,
firmware acceptance and recovery independent of ABL are tracked in
[KVM-PLAN.md](KVM-PLAN.md). This milestone completes modeled cache startup;
it does not establish a flashable candidate or a physical EL2 Linux boot.

## Reproduce and evidence

```sh
python3 tools/hyp_re/xbl_cache.py
python3 tools/hyp_re/test_cache_startup.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/cache-startup-regressions
```

- `reports/qhee-offline/cache-startup-static/`: eleven pinned original instruction
  windows and the second-request boundary contract.
- `kernel-work/out/qhee-cache-startup-tests/results.json`: ten full cases,
  five original stock forwarding controls, ten TZ slice derivations and four
  earlier-boundary controls in case directories.
- `reports/qhee-offline/cache-startup-regressions/results.json`: regression results.
- `reports/qhee-offline/cache-startup-milestone.json`: verified evidence inventory.

## Subsequent milestone

[Original canary store and SEC readiness boundary](EL2-XBL-canary-return.md)
adds a separate guarded second reply, executes the original canary store and
enters SEC main, stopping before readiness read `0x146bf944`. That milestone
has 851 checks across 40 suites; the 842-check result above records this
earlier second-request boundary.
