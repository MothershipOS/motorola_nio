# Original SEC canary store and first readiness read — 2026-10-06

The modeled cold path now returns from XBL's second eight-byte buffer request,
executes the original canary store, unwinds its stack and enters SEC main.
Stock EL1 and diagnostic EL2 follow the original code to `0x9fc0e37c`, paused
before its first external readiness read at `0x146bf944`. No readiness value
is supplied or read. The diagnostic caller still runs at EL2 with I/D enabled
and translation disabled.

The milestone has **851 passing checks across 40 suites**, including nine
new tests and 28 synthetic reply contracts. This is offline execution using finite FIFO fixtures and explicit secure-policy,
backend, cache and monitor assumptions. The repeated bytes are deterministic
test data, not entropy or a production canary. No phone access or firmware write
occurred. Physical Linux at EL2 and KVM remain unverified.

## Separately guarded second reply

`run_qemu.py --xbl-canary-reply` requires the existing query and first buffer
reply models. It opts into a separate one-shot reply whose metadata derives
status zero and count eight from original TZ slices at the captured stock and
direct-EL2 x0–x13 contracts. The default remains disabled. The first buffer
reply keeps its original checks and ledger; it cannot serve the second request.

The second reply requires:

- Exact function `0x02000a01`, argument info `0x22`, pointer `0x9fc356c0`,
  length eight, x4=7 and x5=`0x1d`.
- Stock QHEE return site `0x80041aa4`, SP=`0x80208db0`, x6=0, x7=3; or direct
  EL2 return site `0x9fc2846c`, SP=`0x9ffcfce0`, x6=`0x82000023`, x7 all ones.
- I/D enabled and translation disabled in the XBL caller's SCTLR bank.
- Bridge, query and first buffer reply ledgers each one; second reply ledger zero.
- Zero requested buffer, selector `0x10`, shifted nibble cache
  `0x0444444dd444444c`, and original canary `0xc0c0c0c0`.

It writes exactly eight buffer bytes and its own ledger, supplies x0–x3 as
`0,8,0,0`, and preserves the remaining registers, SP and NZCV. It does not write
the canary. The first buffer ledger remains one. A further request stops without
another successful reply.

Original TZ slice decoding still stops before pointer validation. Successful
ownership/policy, backend startup/release, cache completion and monitor return
remain explicit joins. Repeating the original four-word FIFO fixture produces
`cc444444dd444444` for this request too. This deliberately repeats finite test
input; it establishes no randomness property.

## Original canary store and SEC main

`trace_bridge_handoff.py --xbl-canary-return` checks exact model metadata and
records the second source return, canary store and SEC-main entry. It performs
no debugger register or memory writes. Earlier stop boundaries remain available
with the second model enabled and do not consume it.

| Checkpoint | Observed result |
| --- | --- |
| Second buffer return at `0x9fc2846c` | status/count `0,8,0,0`; all three reply ledgers one |
| Original source return at `0x9fc0cd50` | x0=`0x444444dd444444cc`; canary still original |
| Original store at `0x9fc0cd54`, checked at `0x9fc0cd58` | canary becomes `0x444444dd444444cc`; adjacent words unchanged |
| Canary initializer returns at `0x9fc0cf48` | SP restored to `0x9ffcfd00` |
| SEC-main call/entry at `0x9fc0cf50` / `0x9fc0e308` | x0=`0x9ff90000`, x1=`0x3fd00` |
| Readiness helper at `0x9fc0e33c` | original flag-address calculation |
| Before readiness load at `0x9fc0e37c` | x8=`0x146bf944`, SP=`0x9ffcfcc0`; no read executed |

Both SCTLR banks, HCR, current EL and interrupt masks stay unchanged across this
extension. Workspace guards remain intact. The 263 cold SCM calls and 241 PMIC
ownership entries remain unchanged; stock execution adds its second forwarding
call separately. The shifted nibble cache and selector are unchanged.

## Concrete next dependency

Original readiness code reads a 32-bit base at FV global `0x9fc2f2c8`:
`0x146bf000`; adds the 64-bit offset at `0x9fc2f2d8`: `0x944`; and polls the
32-bit word at `0x146bf944`. It waits while the word equals `0x55444247`,
loaded from global `0x9fc2f2e0`. The next load has not executed. The tracer
records the comparison value from the helper's stack, not the pre-load x9,
which still holds the base address.

Next establish who publishes that readiness flag and its real entry-time value
from original boot-chain code and available captures. Add only a bounded,
explicit model supported by that contract. A later timer dependency must be
traced separately; an arbitrary ready value would conceal this gate.

The bootstrap records, complete UEFI/ABL/Linux entry, image acceptance and
recovery independent of ABL remain open in [KVM-PLAN.md](KVM-PLAN.md).

## Reproduce and evidence

```sh
python3 tools/hyp_re/xbl_canary.py
python3 tools/hyp_re/test_canary_return.py
python3 tools/hyp_re/check_all.py --out reports/qhee-offline/canary-return-regressions
```

- `reports/qhee-offline/canary-return-static/`: original instruction windows,
  readiness literals, captured reply contracts and two original TZ derivations.
- `kernel-work/out/qhee-canary-return-tests/results.json`: ten full cases and
  ten controls paused before the second reply, including five original stock
  forwarding controls; four earlier stop controls reside in case directories.
- `kernel-work/out/qhee-canary-return-tests/reply-contracts/results.json`:
  synthetic reply preservation, denial and repeated-call checks.
- `reports/qhee-offline/canary-return-regressions/results.json`: full regression.
- `reports/qhee-offline/canary-return-milestone.json`: verified evidence inventory.

## Subsequent milestone

[SEC hold-flag replay and virtual-counter boundary](EL2-XBL-readiness.md)
records repeated read-only phone captures, adds an exact one-read replay
under an explicit postboot-to-entry assumption, and follows original SEC
to its first `CNTVCT_EL0` access. That milestone has 860 checks across 41
suites; the 851-check result above records the earlier before-flag boundary.
