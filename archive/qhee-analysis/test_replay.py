#!/usr/bin/env python3
"""Exercise EL3 replay contracts with synthetic callers and original QHEE."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from qhee import ROOT
from run_qemu import compile_elf, decode_stop, environment, secure_state_sample


def caller_source(fid, arginfo=0, el=2, immediate=0):
    lines = ['.text', '.global _start', '_start:']
    if el == 1:
        lines += ['ldr x0, =0x803f0000', 'msr sp_el1, x0',
                  'adr x0, caller', 'msr elr_el2, x0', 'mov x0, #0x3c5',
                  'msr spsr_el2, x0', 'eret', 'caller:']
    lines += ['mov x9, #0xa0000000', 'msr nzcv, x9']
    values = [fid, arginfo] + [0x1200 + i for i in range(2, 31)]
    lines += [f'ldr x{i}, ={value:#x}' for i, value in enumerate(values)]
    lines += [f'smc #{immediate}', 'sub sp, sp, #272']
    lines += [f'str x{i}, [sp, #{i*8}]' for i in range(31)]
    lines += ['add x0, sp, #272', 'str x0, [sp, #248]', 'mrs x0, nzcv',
              'str x0, [sp, #256]', 'mov x20, sp', 'mov x21, #33',
              'dump:', 'ldr x4, [x20], #8', 'mov x5, #60',
              'ldr x2, =0x09000000', 'hex:', 'lsr x1, x4, x5',
              'and x1, x1, #15', 'cmp x1, #10', 'add x3, x1, #48',
              'add x1, x1, #87', 'csel x1, x3, x1, lo', 'str w1, [x2]',
              'subs x5, x5, #4', 'b.ge hex', 'mov w1, #10', 'str w1, [x2]',
              'subs x21, x21, #1', 'b.ne dump', 'mov x0, #0x20',
              'adr x1, exit_block', 'hlt #0xf000', 'b .',
              '.balign 8', 'exit_block: .quad 0x20026, 0']
    return '\n'.join(lines) + '\n', values


def main():
    out = ROOT / 'kernel-work/out/qhee-replay-tests'
    out.mkdir(parents=True, exist_ok=True)
    qemu, env = environment(ROOT / 'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    source = Path(__file__).resolve().parent / 'emulator/start.S'
    # Deliberately nonzero, distinct, full-width replies catch truncation and mixups.
    reply = [0xf7f, 0x123456789abcdef0, 0xfedcba9876543210]
    definitions = [f'-DSECURE_STATE_R{i}={v:#x}' for i,v in enumerate(reply,1)]
    definitions += ['-DPSCI_MODEL_VERSION=0x10001', '-DNONSECURE_QUERY_UNSUPPORTED']
    results = []
    cases = [('nonsecure-unsupported',0xc2000310,0,2,0,True),
             ('nonsecure-wrong-arginfo',0xc2000310,1,2,0,True),
             ('nonsecure-wrong-el',0xc2000310,0,1,0,True),
             ('nonsecure-wrong-immediate',0xc2000310,0,2,1,True),
             ('nonsecure-wrong-fid',0x42000310,0,2,0,True),
             ('nonsecure-disabled',0xc2000310,0,2,0,False),
             ('secure', 0x42000604, 0, 2, 0, True),
             ('psci', 0x84000000, 0x1234, 2, 0, True),
             ('unknown', 0xc200ffff, 0, 2, 0, True),
             ('watchdog', 0xc2000108, 0, 2, 0, True),
             ('wrong-arginfo', 0x42000604, 1, 2, 0, True),
             ('wrong-el', 0x42000604, 0, 1, 0, True),
             ('wrong-immediate', 0x42000604, 0, 2, 1, True),
             ('disabled', 0x42000604, 0, 2, 0, False)]
    for name, fid, arginfo, el, immediate, enabled in cases:
        dest = out / name
        dest.mkdir(exist_ok=True)
        assembly, initial = caller_source(fid, arginfo, el, immediate)
        (dest / 'caller.S').write_text(assembly)
        compile_elf(dest / 'caller.S', 0x80040000, dest / 'caller.elf')
        compile_elf(source, 0x40200000, dest / 'el3.elf', definitions if enabled else [])
        command = [str(qemu), '-M', 'virt,secure=on,virtualization=on,gic-version=3',
                   '-cpu', 'cortex-a76', '-m', '2G', '-accel', 'tcg', '-smp', '1',
                   '-display', 'none', '-serial', 'stdio', '-monitor', 'none', '-nic', 'none',
                   '-semihosting-config', 'enable=on,target=native', '-no-reboot',
                   '-device', f'loader,file={dest / "el3.elf"},cpu-num=0',
                   '-device', f'loader,file={dest / "caller.elf"}']
        run = subprocess.run(command, capture_output=True, env=env, timeout=5)
        stdout = run.stdout.decode(errors='replace')
        if name in ('secure', 'psci', 'nonsecure-unsupported'):
            expected = ([0] + reply + initial[4:] if name == 'secure'
                        else [0x10001 if name == 'psci' else 0xffffffffffffffff] + initial[1:]) + [0x803f0000, 0xa0000000]
            lines = stdout.splitlines()
            marker = {'secure':'MODEL_SECURE_STATE_REPLAY','psci':'MODEL_PSCI_VERSION',
                      'nonsecure-unsupported':'MODEL_NONSECURE_QUERY_UNSUPPORTED'}[name]
            passed = (len(lines) == 34 and lines[0] == marker
                      and [int(line,16) for line in lines[1:]] == expected)
        else:
            stop = decode_stop(run.stdout) or {}
            regs = stop.get('registers', {})
            passed = ('MODEL_' not in stdout and regs.get('x0') == hex(fid)
                      and regs.get('x1') == hex(arginfo)
                      and regs.get('x2') == hex(initial[2])
                      and regs.get('x3') == hex(initial[3]))
        results.append({'case':name, 'passed':passed and run.returncode == 0,
                        'stdout':stdout, 'stderr':run.stderr.decode(errors='replace')})
    # Input provenance is accepted only for a successful exact service response.
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        path = Path(tmp) / 'sample.json'
        for name, changes in [('bad-service', {'service':'0xc2000108'}),
                              ('failed-status', {'status':-22}),
                              ('overflow', {'r1':'0x10000000000000000'}),
                              ('negative', {'r2':'-1'})]:
            response = {'service':'0x42000604','status':0,'r1':'0xf7f','r2':'0','r3':'0'}
            path.write_text(json.dumps({'secure_state':response | changes}))
            try:
                secure_state_sample(path)
            except ValueError:
                passed = True
            else:
                passed = False
            results.append({'case':name,'passed':passed})
    sample = ROOT / 'reports/nio-scm-live-20260928-direct/manifest.json'
    for name, psci in [('qhee-secure-replay', False), ('qhee-psci-replay', True)]:
        dest = out / name
        command = [sys.executable, str(Path(__file__).with_name('run_qemu.py')),
                   '--qemu', str(qemu), '--out', str(dest),
                   '--soc-hw-version', '0x60080201', '--secure-state-sample', str(sample),
                   '--devcfg', str(ROOT / 'backups/nio-firmware-20260927T163534Z/devcfg_a.img')]
        if psci:
            command += ['--psci-version','0x10001']
        subprocess.run(command, stdout=subprocess.DEVNULL, check=True)
        report = json.loads((dest / 'manifest.json').read_text())
        stop = report['stop'] or {}
        passed = (stop.get('service') == 'PSCI_VERSION' if not psci else
                  stop.get('qhee_fault') == {'address':'0x1fd4000', 'pc':'0x8005f778'})
        passed = passed and report['secure_state_replay']['response']['r1'] == '0xf7f'
        results.append({'case':name,'passed':passed,'manifest':str(dest / 'manifest.json')})
    report = {'results':results, 'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
              'el3_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'scope':'Offline replay contract checks; no phone EL2 handoff or actual EL3 response capture'}
    (out / 'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for result in results:
        print(result['case'], 'PASS' if result['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):
        raise SystemExit('Replay regression failed; inspect results.json')


if __name__ == '__main__':
    main()
