#!/usr/bin/env python3
"""Test extracted QHEE SPSR/ERET slices in QEMU; NOT whole-firmware validation."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess

from qhee import QheeImage, ROOT
from run_qemu import compile_elf, environment, provenance


def main():
    q = QheeImage()
    out = ROOT / 'kernel-work/out/qhee-slices'
    out.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parent / 'emulator'
    dispatch = q.read(0x800401bc, 0x80040214 - 0x800401bc)
    tail = q.read(0x800402b0, 0x8004032c - 0x800402b0)
    assert struct.unpack_from('<I', dispatch, 0x1c)[0] == 0xd28010a5
    assert tail[-4:] == bytes.fromhex('e0039fd6')
    (out / 'tail.bin').write_bytes(tail)
    compile_elf(source / 'probe.S', 0x40400000, out / 'probe.elf')
    qemu, env = environment()
    results = []
    cases = [('stock', False, False, False, 1),
             ('spsr-only-mmu-off-model', True, False, False, 2),
             ('spsr-only-mmu-on-model', True, True, False, 2),
             ('clear-mc-identity-model', True, True, True, 2)]
    for name, patch, mmu, clear, expected in cases:
        data = bytearray(dispatch)
        if patch:
            struct.pack_into('<I', data, 0x1c, 0xd2800005 | (0x3c9 << 5))
        path = out / (name + '.bin')
        path.write_bytes(data)
        defines = ['-DSLICE_DISPATCH="' + str(path) + '"',
                   '-DSLICE_TAIL="' + str(out / 'tail.bin') + '"']
        if mmu: defines.append('-DMMU_ON')
        if clear: defines.append('-DCLEAR_MC')
        elf = out / (name + '.elf')
        compile_elf(source / 'start.S', 0x40200000, elf, defines)
        cmd = [str(qemu), '-M', 'virt,secure=on,virtualization=on,gic-version=3',
            '-cpu', 'cortex-a76', '-m', '2G', '-accel', 'tcg', '-smp', '1',
            '-display', 'none', '-serial', 'stdio', '-monitor', 'none', '-nic', 'none',
            '-semihosting-config', 'enable=on,target=native', '-no-reboot',
            '-device', f'loader,file={elf},cpu-num=0',
            '-device', f'loader,file={out / "probe.elf"}']
        try:
            r = subprocess.run(cmd, capture_output=True, env=env, text=True, timeout=5)
        except subprocess.TimeoutExpired as error:
            r = subprocess.CompletedProcess(cmd, 124,
                (error.stdout or b'').decode(errors='replace'),
                (error.stderr or b'').decode(errors='replace') + ' timed out')
        lines = r.stdout.splitlines()
        passed = r.returncode == 0 and bool(lines) and lines[0] == f'EL{expected}'
        sctlr = int(lines[1], 16) if passed and expected == 2 and len(lines) > 1 else None
        if expected == 2:
            passed = passed and sctlr is not None and (sctlr & 5) == (5 if mmu and not clear else 0)
        result = {'case':name, 'observed':r.stdout, 'stderr':r.stderr,
                  'qemu_exit':r.returncode, 'passed':passed,
                  'sctlr_el2':hex(sctlr) if sctlr is not None else None}
        results.append(result)
        print(json.dumps(result))
    report = {'image_sha256':hashlib.sha256(q.data).hexdigest(),
        'tool_sha256':{**provenance(qemu, source),
            str(Path(__file__).resolve().relative_to(ROOT)):hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        'extracted_ranges':['0x800401bc..0x80040214', '0x800402b0..0x8004032c'],
        'results':results,
        'limits':['Synthetic single-CPU state; intermediate QHEE code omitted',
          'No TZ, ABL or Linux execution', 'Identity map and clean model state are assumptions',
          'The clear-M/C case is a model-only illustration, NOT a phone Patch B',
          'No dirty-cache teardown, stage-2 ownership, PSCI or secondary-CPU validation']}
    (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    if not all(r['passed'] for r in results):
        raise SystemExit('One or more handoff-model checks failed')


if __name__ == '__main__':
    main()
