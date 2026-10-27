# Original XBL stack query and QHEE forwarding — 2026-10-06

Original XBL now runs through its stack-sizing prologue and dispatcher to the
first secure-monitor query after the full modeled QHEE cold path. A single
architectural SMC step distinguishes the stock EL1 trap into QHEE from the
EL2 experiment's direct entry into the synthetic EL3 vector. Original QHEE
then forwards the stock query unchanged at `0x80041cbc`.

This narrows the next investigation to TZ's handling of the actual query and
subsequent buffer service. No new secure-service response or entropy model
was added. Physical Linux at EL2, complete UEFI/ABL execution and KVM remain
unverified. No phone access or firmware write occurred.

Nine new tests cover ten query/routing executions, five original QHEE handler
executions, and two earlier-boundary controls. This historical milestone had
**806 passing checks across 35 suites**.

## Original stack and query path

The read-only tracer adds `--xbl-stack-smc`, stopping at `0x9fc284dc` before
its SMC. Existing `--xbl-startup` and `--xbl-prefix` keep their earlier bounds.
The same original FV, sentinel RAM and loaded-code guards apply.

Seven additional checkpoints follow these original instructions:

```text
SEC call at 0x9fc0cf28
  -> stack sizing at 0x9fc21ce8
  -> four-bit source/cache helper at 0x9fc21c6c
  -> source dispatcher at 0x9fc2849c
  -> query entry at 0x9fc284d0
  -> stop before SMC at 0x9fc284dc
```

Runtime reads confirm that the nibble cache at `0x9fc3d710` and selector at
`0x9fc356c8` are both zero. Original code takes the empty-cache path and the
first table entry, `0x9fc284d0`. The earlier conditional static path is now
executed under all tested controls.

Three original stack prologues consume 80 bytes. SP becomes `0x9ffcffb0`.
Saved frame pointers, link registers, the `0x40000` workspace size and the
startup timestamp match their original call sites. The rest of BSS remains
zero, vectors retain their original fill, and all sixteen-byte sentinel guards
remain intact. No stack-sizing result has yet been returned.

The captured request is:

| Register | Stock EL1 | Diagnostic EL2 |
| --- | --- | --- |
| x0 | `0x02000601` | `0x02000601` |
| x1 | `1` | `1` |
| x2 | `0x02000602` | `0x02000602` |
| x3 | `0x9ffd0000` | `0x9ffd0000` |
| x4 | `0` | `0` |
| x5 | `0` | `1` |
| x6 | `0` | `0x801cba78` |
| x7 | `0` | `0` |

The service/command fields identify an availability query (service 6, command
1), matching the local Linux SCM definitions. The table records actual
registers, without assuming that TZ ignores the remaining values.

The x5/x6 difference precedes SEC: the bounded diagnostic terminal replacement
clears x0–x3 and leaves higher registers populated, whereas original QHEE's
terminal clears x0–x30. Entry, first-fetch and SEC-startup snapshots demonstrate
this distinction. It is not a modification made by the debugger or a new
service reply. The loaded terminal remains an offline diagnostic experiment;
unused-register assumptions must be checked against the original TZ dispatcher
before turning it into a boot-chain candidate.

## One architectural routing step

`--inspect-xbl-smc-route` requires `--xbl-stack-smc`. It executes exactly the
original SMC instruction and pauses before the destination vector's first
instruction. No secure handler executes in the EL2 case.

| Caller | Observed destination | Syndrome and saved return address |
| --- | --- | --- |
| Stock EL1, HCR=`0x80080005` with TSC set | Original QHEE vector `0x80093400` at EL2 | ESR_EL2=`0x5e000000`, ELR_EL2=`0x9fc284dc` |
| Diagnostic EL2, SEC HCR=`0x10` | Synthetic EL3 vector `0x40200c00` | ESR_EL3=`0x5e000000`, ELR_EL3=`0x9fc284e0` |

All eight argument registers remain unchanged at exception entry, and the
appropriate SPSR contains the caller's complete PSTATE. The trap return address
points to the original SMC; direct EL3 entry saves the following instruction.
This validates modeled architectural routing, not physical TZ availability,
interrupt delivery, service acceptance or a returned result.

## Original QHEE forwarding control

`--inspect-xbl-qhee-forward` additionally requires stock EL1 and routing
inspection. It runs the original QHEE trap handler, stopping at its first
original SMC or a return to XBL. Four SMC instruction sites are bounded from
the pinned loaded code; unknown service execution gets no invented response.
This mode is rejected for the EL2 loaded-code variant.

Every tested stock control reaches `0x80041cbc` before forwarding. x0–x7 are
identical to the original XBL request, and the forwarding stack is
`0x80208dc0`. QHEE's SCTLR_EL2 remains `0x8100f`; its original MMU selector
chooses this SMC site. No forwarding SMC is executed and no TZ reply is supplied.
The path does not answer the query locally or rewrite it into the cold-path
PRNG request. The original cold initialization call sequence and ledgers stay
unchanged in all cases.

The successful matrix covers the earlier synthetic entry plus both TZ-derived
HCR inputs, both GCC inputs for derived entries, and stock/diagnostic targets.
Both HCR inputs converge through original QHEE initialization as before.
The optional handler control runs for all five stock cases.

## Next implementation order

1. Trace the pinned TZ nonsecure SMC dispatcher for this exact request. The
   earlier TZ boot-frame/restore fixture is a separate path; it does not
   establish normal query service handling. Check caller level/NS state,
   argument-count decoding and higher-register handling.
2. Establish the actual query result or finite supported/unsupported controls
   from original code. Original XBL branches on w0: zero selects table offset
   `0x10` and its `0x02000a01` buffer call; nonzero selects offset `8` and its
   `0x02801202` path. Positive w0 retries the SMC. No branch reply is invented
   by this milestone.
3. Trace only the selected eight-byte source/buffer contract needed to return
   from stack sizing, then stop at the next concrete firmware dependency.
   Preserve the bootstrap-record, Linux-entry, image-acceptance and independent
   recovery gates in [KVM-PLAN.md](KVM-PLAN.md).

The EL2 path has an architectural route to EL3. Real TZ processing, physical
cache/coherency behavior and subsequent boot services remain open. This
investigation does not require a complete SoC emulator or Android device stack.

## Reproduce and evidence

```sh
python3 tools/hyp_re/test_xbl_stack.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/xbl-stack-regressions
```

Prepared full-cold XBL fixtures can use `--xbl-stack-smc`, optionally adding
`--inspect-xbl-smc-route`; stock fixtures may also add
`--inspect-xbl-qhee-forward`. Commands and model inputs are recorded in manifests.

- `kernel-work/out/qhee-xbl-stack-tests/results.json`: ten query/routing cases
  and five forwarding traces; case directories also contain boundary controls.
- `reports/qhee-offline/xbl-stack-static/`: pinned XBL and QHEE instruction windows.
- `reports/qhee-offline/xbl-stack-regressions/results.json`: current suite results.
- `reports/qhee-offline/xbl-stack-milestone.json`: verified evidence inventory.

Earlier workspace initialization is documented in
[original SEC vectors, BSS and temporary stack](EL2-XBL-startup.md).

The subsequent [original TZ query reply milestone](EL2-TZ-query-reply.md)
advances both modeled paths to the next eight-byte buffer SMC, under an
explicit finite reply and unverified policy/context-switch assumptions.
