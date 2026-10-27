#!/usr/bin/env python3
"""Integration regression: narrow MMIO model resolves the observed QHEE fatal path."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from qhee import ROOT, DEFAULT_IMAGE
from run_qemu import compile_elf, environment


def main():
    qemu = ROOT / 'kernel-work/emulation/qemu-build/qemu-system-aarch64'
    if not qemu.exists():
        raise SystemExit('Run tools/hyp_re/build_qemu_model.py first')
    out = ROOT / 'kernel-work/out/qhee-secure-call-tests'
    out.mkdir(parents=True, exist_ok=True)
    results = []
    # Architectural test at nonsecure EL2: only the exact aligned read succeeds.
    cases = [('absent', 0, False), ('read32', 0, True), ('write32', 1, True),
             ('neighbor', 2, True), ('read8', 3, True)]
    for name, access, enabled in cases:
        elf = out / (name + '.elf')
        compile_elf(Path(__file__).resolve().parent / 'emulator/register_probe.S',
                    0x40200000, elf, [f'-DACCESS={access}'])
        command = [str(qemu), '-M', 'virt,secure=on,virtualization=on,gic-version=3',
            '-cpu', 'cortex-a76', '-m', '2G', '-accel', 'tcg', '-smp', '1',
            '-display', 'none', '-serial', 'stdio', '-monitor', 'none', '-nic', 'none',
            '-semihosting-config', 'enable=on,target=native', '-no-reboot',
            '-device', f'loader,file={elf},cpu-num=0']
        if enabled:
            command += ['-device','nio-soc-version,value=0x60080201']
        run = subprocess.run(command, capture_output=True, text=True,
                             env=environment(qemu)[1], timeout=5)
        lines = run.stdout.splitlines()
        if name == 'read32':
            passed = lines == ['READ', '0000000060080201']
        else:
            passed = (len(lines) == 3 and lines[0] == 'ABORT'
                      and (int(lines[1],16) >> 26) == 0x25
                      and (int(lines[1],16) & 0x3f) == 0x10
                      and int(lines[2],16) == (0x1fc8004 if name == 'neighbor' else 0x1fc8000))
        results.append({'case':name, 'passed':passed and run.returncode == 0,
                        'stdout':run.stdout, 'stderr':run.stderr})
    # Same emulator and original firmware; change only the modeled board input.
    for name, enabled in [('qhee-baseline', False), ('qhee-soc-model', True)]:
        dest = out / name
        command = [sys.executable, str(Path(__file__).with_name('run_qemu.py')),
                   '--qemu', str(qemu), '--out', str(dest)]
        if enabled: command += ['--soc-hw-version','0x60080201']
        subprocess.run(command, stdout=subprocess.DEVNULL, check=True)
        report = json.loads((dest / 'manifest.json').read_text())
        stop = report['stop'] or {}
        if enabled:
            passed = (stop.get('service') == 'TZ_INFO_GET_SECURE_STATE'
                      and 'qhee_fault' not in stop
                      and 'NIO_MODEL_TCSR_READ' in report['stderr'])
        else:
            passed = (report['outcome'] == 'qhee_fatal_watchdog_request'
                      and stop.get('qhee_fault') == {'address':'0x1fc8000','pc':'0x80093da0'})
        results.append({'case':name,'passed':passed,'manifest':str(dest/'manifest.json')})
    report = {'results':results, 'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
              'image_sha256':hashlib.sha256(DEFAULT_IMAGE.read_bytes()).hexdigest(),
              'scope':'Model regression, not a phone EL2 boot or proof of actual nio register value'}
    (out / 'results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if not all(r['passed'] for r in results):
        raise SystemExit('Secure-call model regression failed')


if __name__ == '__main__':
    main()
