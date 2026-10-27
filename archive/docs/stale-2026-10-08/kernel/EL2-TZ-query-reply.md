# Original TZ availability reply and XBL buffer request — 2026-10-06

Pinned original TZ argument, registry, callback and marshalling slices now
resolve the first XBL stack-source query. A finite synthetic EL3 reply derived
from those slices advances full modeled QHEE and original XBL to the next SMC,
`0x02000a01`, requesting eight bytes at `0x9fc356c0`. Both stock EL1 and the
bounded EL2 diagnostic reach this boundary.

The milestone has **815 passing checks across 36 suites**, including nine new
tests. This is offline execution. Secure policy, accounting/locking wrappers,
EL3 context switching and the original monitor return remain unexecuted or
assumed. No phone access or firmware write occurred; physical Linux at EL2
and KVM remain open.

## What the original code establishes

The nonsecure monitor path switches to secure EL1. The earlier boot-frame
fixture is a separate entry path and does not establish service acceptance.
Static dispatcher windows connect the normal secure EL1 service branch to
`0x1c06734c`. Two bounded instruction slices execute the actual original bytes:

1. Argument decoding starts at `0x1c0673b8`, after owner accounting. Original
   copy, SMC32 normalization, registry lookup and argument validation run
   continuously. Execution stops at `0x1c067664` before the policy getter.
   Wrong argument counts return validation status -5; wrong types return -10.
2. The separately seeded marshaller at `0x1c06794c` invokes the registry-derived
   callback and copies seven result words into its caller frame. Its complete
   return reaches a synthetic link register. Original file-backed canary data
   is used; runtime secure startup and policy are not modeled.

The registry descriptor has function ID at +4, argument info at +8, flags at
+12 and callback at +16. The query `0x02000601` has argument info 1, flags 1,
and callback `0x1c06705c`. The queried `0x02000602` is absent: lookup returns 1
and leaves its output descriptor untouched. The callback returns transport
status zero and availability zero. Thus the marshalled reply is:

```text
x0 = 0  (successful query)
x1 = 0  (queried function unavailable)
x2 = 0
x3 = 0
```

Positive controls query the registered `0x02000601` and `0x02000a01` functions:
they return transport status zero and availability one. Status and availability
are distinct. Original XBL tests w0, so it takes the successful-query branch
with selector `0x10` even though x1 is zero.

Each of the ten full-path cases supplies its actual pre-query x0–x13 to the
original slices. Stock x5/x6 are zero; diagnostic x5/x6 are 1/`0x801cba78`.
The one-scalar callback branch never dereferences that inherited x6 pointer.
This establishes argument dataflow within the slices, not approval of either
caller level by the omitted policy and context-switch path.

Only pinned, file-backed code/data pages are mapped; instruction count,
execution ranges and write ranges are bounded. Unmapped accesses and unexpected
writes stop execution. Reports retain loaded-page hashes, instruction addresses,
reads, writes, normalized frames and output frames.

## Exact replay and original XBL continuation

`run_qemu.py --xbl-query-reply` requires a prepared original XBL payload and
the existing cold bridge/PRNG models. The default harness gains no new reply.
The opt-in reply accepts only the captured function, count, target and higher
registers, the exact EL3 return site for stock forwarding or diagnostic EL2,
an EL2h SMC #0 caller and completed bridge initialization. A ledger permits
one reply. The model returns only x0–x3, preserves other registers and caller
state, and writes no XBL buffer or entropy. Its metadata contains the pinned
TZ hash and deterministic derivation hash; the tracer rejects mismatches.

Sixteen synthetic caller contracts check a valid reply, disabled mode, wrong
site/level/immediate/function/count/target/higher arguments, missing prerequisite,
consumed ledger and repeated query. The valid case checks register, SP and
NZCV preservation; rejected cases stop without an extra successful reply.

The read-only `--xbl-stack-buffer` tracer stops at `0x9fc28468` before the next
original SMC. Its successful matrix has ten cases: the earlier synthetic entry
at GCC off, plus both TZ-derived HCR entries at GCC off/on, each at stock EL1
and diagnostic EL2. All retain the original cold call sequence and 241 PMIC
ownership entries. Earlier trace boundaries remain available.

| State at the next boundary | Observed value |
| --- | --- |
| x0 / x1 | `0x02000a01` / `0x22` |
| x2 / x3 | `0x9fc356c0` / `8` |
| x4 / x7 | zero |
| x5 / x6, stock | zero / zero |
| x5 / x6, diagnostic | `1` / `0x801cba78` |
| SP | `0x9ffcffb0` |
| Selector at `0x9fc356c8` | `0x10` |
| Nibble cache at `0x9fc3d710` | zero |
| Requested eight-byte buffer | zero; original XBL clears it |
| Query reply ledger | one |

Original XBL runs its cache helper before this request. Sentinel guards remain
intact. No buffer response is supplied, and stack sizing has not returned.
TCG execution of cache instructions does not establish physical coherency.

## Next step toward KVM

Trace only `0x02000a01`: its registry entry has argument info `0x22`, flags 1
and original callback `0x1c054b30`. Follow original pointer/type validation,
write bounds, output-frame construction and the required entropy source before
adding a finite buffer response. Do not reuse an earlier cold-path PRNG reply
without establishing this distinct contract. Stop after stack sizing returns
or at the next concrete firmware dependency.

Bootstrap records, intervening UEFI/ABL/Linux entry, physical TZ acceptance,
image acceptance and recovery independent of ABL remain separate gates in
[KVM-PLAN.md](KVM-PLAN.md). The immediate hardware goal stays one CPU0 KVM vCPU.

## Reproduce and evidence

```sh
python3 tools/hyp_re/tz_query.py
python3 tools/hyp_re/test_tz_query.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/tz-query-regressions
```

- `reports/qhee-offline/tz-query-static/`: pinned instruction windows and slice result.
- `kernel-work/out/qhee-tz-query-tests/results.json`: ten full-path cases;
  each stores its original TZ slice derivation, QEMU and tracer manifests.
- `kernel-work/out/qhee-tz-query-tests/reply-contracts/results.json`: sixteen
  synthetic reply contracts; an earlier-query boundary control is also retained.
- `reports/qhee-offline/tz-query-regressions/results.json`: complete regression results.
- `reports/qhee-offline/tz-query-milestone.json`: verified current evidence inventory.

The previous no-reply boundary is preserved in
[XBL stack query and original QHEE forwarding](EL2-XBL-stack-SMC.md).

The subsequent [original buffer/PRNG slice milestone](EL2-TZ-buffer-contract.md)
establishes pointer-check boundaries, finite FIFO output and the original
status/count reply under explicit joins; the full harness remains pre-buffer-SMC.
