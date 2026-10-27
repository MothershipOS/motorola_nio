#!/usr/bin/env python3
"""Coverage-accounted linear sweep of QHEE; instruction candidates, not a CFG proof.

Finds every eret/smc/hvc and every access to the system registers that decide
where and at what EL the hypervisor drops the payload:
  - SPSR_EL2 / ELR_EL2      : target PSTATE (EL) and address of an ERET
  - HCR_EL2                 : RW (AArch64 EL1), VM (stage-2), TSC (trap SMC)
  - VBAR_EL2 / VTTBR_EL2    : EL2 vectors, stage-2 base
  - SCTLR_EL1 / *_EL1       : the EL1 context QHEE builds for HLOS
For each ERET it prints the preceding window so the SPSR_EL2 setup is visible.

  python3 tools/hyp_re/analyze.py [hyp_a.img] [--around 0xADDR]
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qhee import QheeImage, DEFAULT_IMAGE  # noqa: E402

# System registers that matter for EL selection / hypervisor handoff.
WATCH = ['spsr_el2', 'elr_el2', 'hcr_el2', 'vbar_el2', 'vttbr_el2', 'sctlr_el2',
         'cptr_el2', 'cnthctl_el2', 'hstr_el2', 'mdcr_el2', 'vpidr_el2', 'vmpidr_el2',
         'sctlr_el1', 'spsr_el1', 'elr_el1', 'vbar_el1', 'sp_el1', 'sp_el0',
         'scr_el3', 'spsr_el3', 'elr_el3']


def disasm(image: QheeImage):
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    md.detail = False
    # ARM64 instructions are four bytes. Preserve alignment across embedded data.
    md.skipdata = True
    md.skipdata_setup = (".word", lambda code, size, offset, user: min(4, size - offset), None)
    base, code = image.code_bytes()
    return md, base, code


def scan(image: QheeImage):
    md, base, code = disasm(image)
    insns = list(md.disasm(code, base))
    by_addr = {i.address: n for n, i in enumerate(insns)}
    erets, branches, sysreg = [], [], {r: [] for r in WATCH}
    for i in insns:
        m = i.mnemonic
        if m == 'eret':
            erets.append(i.address)
        elif m in ('smc', 'hvc', 'svc'):
            branches.append((i.address, m, i.op_str))
        elif m in ('msr', 'mrs'):
            text = i.op_str.lower()
            for reg in WATCH:
                if reg in text:
                    sysreg[reg].append((i.address, m, i.op_str))
    return insns, by_addr, erets, branches, sysreg


def window(insns, by_addr, addr, before=14, after=2):
    n = by_addr[addr]
    for i in insns[max(0, n - before):n + after + 1]:
        mark = '>>' if i.address == addr else '  '
        print(f'  {mark} {i.address:#010x}: {i.mnemonic:<8} {i.op_str}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('image', nargs='?', type=Path, default=DEFAULT_IMAGE)
    parser.add_argument('--json', type=Path, help='write coverage and candidate sites')
    parser.add_argument('--around', type=lambda x: int(x, 0), help='dump a window around this address')
    args = parser.parse_args()
    image = QheeImage(args.image)
    insns, by_addr, erets, branches, sysreg = scan(image)
    segment_bytes = image.code.filesz
    decoded_bytes = sum(i.size for i in insns if i.id != 0)
    undecoded_bytes = sum(i.size for i in insns if i.id == 0)
    assert decoded_bytes + undecoded_bytes == segment_bytes, 'incomplete sweep'
    report = {'image_sha256': hashlib.sha256(image.data).hexdigest(),
        'segment_bytes': segment_bytes, 'decoded_candidate_bytes': decoded_bytes,
        'undecoded_bytes': undecoded_bytes, 'accounted_bytes': decoded_bytes + undecoded_bytes,
        'eret_candidates': [hex(a) for a in erets],
        'calls': [{'address':hex(a), 'instruction':m, 'operands':o} for a,m,o in branches],
        'register_candidates': {r:[{'address':hex(a),'instruction':m,'operands':o} for a,m,o in hits] for r,hits in sysreg.items()},
        'caveat': 'Linear sweep includes data that may decode as instructions; candidates need control-flow validation.'}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + '\n')
    print(f'{image.path.name}: entry {image.entry:#x}; {decoded_bytes:#x} decoded candidate bytes + '
          f'{undecoded_bytes:#x} undecoded = {segment_bytes:#x} accounted bytes')
    print(report['caveat'] + '\n')

    if args.around is not None:
        if args.around not in by_addr:
            parser.error('--around must name an aligned file-backed address')
        window(insns, by_addr, args.around, before=20, after=20)
        return

    print(f'=== ERET sites ({len(erets)}) — candidate exception returns; target EL depends on SPSR ===')
    for addr in erets:
        print(f'\n-- eret @ {addr:#x} --')
        window(insns, by_addr, addr)

    print(f'\n=== SMC/HVC/SVC ({len(branches)}) ===')
    for addr, mnem, ops in branches:
        print(f'  {addr:#010x}: {mnem} {ops}')

    print('\n=== EL-selection system registers ===')
    for reg in WATCH:
        hits = sysreg[reg]
        if hits:
            writes = [h for h in hits if h[1] == 'msr']
            print(f'  {reg:<12} {len(hits):>3} access ({len(writes)} writes): '
                  + ', '.join(f'{a:#x}' for a, _, _ in hits[:8]) + (' ...' if len(hits) > 8 else ''))


if __name__ == '__main__':
    main()
