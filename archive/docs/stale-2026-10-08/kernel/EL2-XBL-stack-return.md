# Original XBL stack-sizing return — 2026-10-06

The full modeled QHEE cold path now continues through original XBL's query,
eight-byte buffer request, source read, nibble-cache update and stack-sizing
return. Original SEC adjusts SP to `0x9ffcfd00` and stops at `0x9fc0cf38`
before calling its next helper, `0x9fc17b90`. Stock EL1 and diagnostic EL2
pass all ten entry/HCR/GCC combinations.

The milestone has **833 passing checks across 38 suites**, with nine new tests,
22 synthetic reply contracts, five original stock-forwarding traces and two
earlier-boundary routing controls. This is offline execution with synthetic
FIFO bytes and explicit ownership/setup/cache/monitor assumptions. No phone
access or firmware write occurred. Physical Linux at EL2 and KVM remain open.

## Exact buffer fixture reply

`run_qemu.py --xbl-buffer-reply` requires `--xbl-query-reply` and its prepared
original XBL/bridge prerequisites. It derives the buffer word and status/count
from [original TZ buffer slices](EL2-TZ-buffer-contract.md), records the complete
join assumptions and derivation hash, and enables only this opt-in response.
The default model gains no buffer service.

The request must be exactly `0x02000a01`, argument info `0x22`, buffer
`0x9fc356c0`, length 8, with the captured higher-register/call-site contract.
The bridge and query ledgers must each be one, the buffer reply ledger zero,
the requested buffer zero, selector `0x10`, and nibble cache zero. It writes
only the requested eight bytes and its reply ledger, supplies x0–x3 as
`0,8,0,0`, and preserves the remaining registers, SP and NZCV. The FIFO fixture
is `cc444444dd444444`; it is deterministic test data, not entropy.

Malformed service/count/pointer/size/level/immediate/site/arguments, missing
prerequisites, repeated replies, preexisting buffer contents, wrong selector
and populated cache stop without another successful reply. Valid stock and
EL2 synthetic callers verify register preservation and adjacent-word guards.

## Original stock forwarding differs from the query

A read-only routing/forwarding control now works at the buffer boundary as
well as the earlier availability query. Every stock case captures:

| Contract | Availability query | Eight-byte buffer request |
| --- | --- | --- |
| Original QHEE forwarding SMC | `0x80041cbc` | `0x80041aa0` |
| EL3 return site | `0x80041cc0` | `0x80041aa4` |
| Forwarding SP | `0x80208dc0` | `0x80208db0` |
| Forwarded x7 | zero | `3` |

At the buffer boundary, x0–x6 are otherwise unchanged. Direct diagnostic EL2
keeps x7 zero and has EL3 return site `0x9fc2846c`. The finite reply checks both
actual contracts; it does not reuse the earlier query's call-site guard.

Each original stock forwarding snapshot supplies x0–x13 to the TZ buffer
slices. With forwarded x7=3, original decoding selects checker `0x1c065b0c`,
rather than the `0x1c065c28` choice from the earlier pre-forward x7=0 fixture.
Validation still stops pending; no secure context/policy acceptance is proved.
The original marshaller/fixture-return path derives the same count reply.
The cold-start request log remains unchanged; later forwarding is recorded
separately in `xbl_forward_calls`.

## Original stack result and adjusted SP

`trace_bridge_handoff.py --xbl-stack-return` requires the exact buffer metadata.
It performs no debugger writes. Ten new original-instruction checkpoints follow
buffer return, cache-helper return, source load, cache publication/consumption,
stack-size computation, frame unwind and SEC stack adjustment.

| State | Observed fixture-derived result |
| --- | --- |
| Buffer/source word | `0x444444dd444444cc` |
| Consumed low four bits | `0xc` |
| Cache after shifting by four | `0x0444444dd444444c` |
| Original workspace size | `0x40000` |
| Returned stack size | `0x40000 - (0xc << 6) = 0x3fd00` |
| SP after all temporary frames unwind | `0x9ffd0000` |
| Original stack base | `0x9ff90000` |
| Adjusted SP | `0x9ff90000 + 0x3fd00 = 0x9ffcfd00` |
| Selector | remains `0x10` |
| Final PC | `0x9fc0cf38`, before the next call |

Original XBL executes its cache helper after the reply and reads the buffer
itself. Sentinel guards remain intact, reply ledgers are each one, and the
241 PMIC ownership entries are unchanged. TCG does not establish physical
cache coherency. Earlier prefix/startup/query/buffer boundaries remain available
and do not consume the buffer reply when stopped before its SMC.

## Next step toward KVM

Trace original helper `0x9fc17b90` and its next control/cache dependencies.
Continue only as far as the concrete CPU0 path requires, preserving the EL1
control alongside the diagnostic EL2 path. Stop at the next actual dependency
instead of adding unrelated hardware models.

The bootstrap-record bridge, intervening UEFI/ABL/Linux entry, physical TZ
acceptance, firmware integrity/acceptance and recovery independent of ABL stay
open in [KVM-PLAN.md](KVM-PLAN.md). This milestone returns from stack sizing;
it does not complete SEC, boot Linux at EL2, or execute a KVM guest.

## Reproduce and evidence

```sh
python3 tools/hyp_re/test_stack_return.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/stack-return-regressions
```

- `kernel-work/out/qhee-stack-return-tests/results.json`: ten full-path cases,
  five stock forwarding controls with original TZ slice derivations, and two
  earlier buffer routing controls in case directories.
- `kernel-work/out/qhee-stack-return-tests/reply-contracts/results.json`: 22
  synthetic caller contracts with source, compiled artifacts and console logs.
- `reports/qhee-offline/stack-return-static/`: pinned XBL instruction windows
  and the derived fixture/stack contract.
- `reports/qhee-offline/stack-return-regressions/results.json`: full regression results.
- `reports/qhee-offline/stack-return-milestone.json`: verified evidence inventory.

## Subsequent milestone

[Original SEC cache startup and canary request](EL2-XBL-cache-startup.md)
continues through helper `0x9fc17b90`, original cache enabling and the second
eight-byte SMC. That milestone has 842 checks across 39 suites; the 833-check
result above records this earlier boundary.
