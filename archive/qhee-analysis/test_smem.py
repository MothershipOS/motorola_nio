#!/usr/bin/env python3
"""Test sparse SMEM fault boundaries, provenance checks and QHEE progress."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from qhee import ROOT
from run_qemu import compile_elf, environment
from smem import snapshot


def main():
    out = ROOT / 'kernel-work/out/qhee-smem-tests'
    out.mkdir(parents=True, exist_ok=True)
    sample = ROOT / 'reports/nio-smem-layout-20260928-v4/manifest.json'
    complete_sample = ROOT/'reports/nio-smem-layout-20260928-v7/manifest.json'
    metadata = snapshot(complete_sample, out / 'snapshot.bin')
    qemu, env = environment(ROOT / 'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    source = Path(__file__).resolve().parent / 'emulator/register_probe.S'
    results = []
    cases = [('pointer-low',0x1fd4000,0,False,0x80aff230),
             ('pointer-high',0x1fd4004,0,False,0),
             ('pointer-write',0x1fd4000,1,True,None),
             ('pointer-byte',0x1fd4000,3,False,None),
             ('pointer-neighbor',0x1fd4008,0,False,None),
             ('target-magic',0x80aff230,0,False,0x49494953),
             ('target-base64',0x80aff238,4,False,0x80900000),
             ('target-byte',0x80aff230,3,False,0x53),
             ('item-canary',0x80901020,5,False,0xa5a5),
             ('uncaptured-payload',0x80901030,0,False,None),
             ('uncaptured-free-memory',0x80914000,0,False,None),
             ('last-reserved-word',0x80affffc,0,False,None),
             ('cross-capture-boundary',0x80aff244,4,False,None),
             ('metadata-write',0x80aff230,1,True,None),
             ('version-write-disabled',0x80900040,6,False,None),
             ('version-readback',0x80900040,6,True,0x12340000),
             ('version-adjacent-write',0x80900044,1,True,None),
             ('version-byte-write',0x80900040,7,True,None),
             ('version-wide-write',0x80900040,8,True,None),
             ('rlock-disabled',0x809051b0,0,False,None),
             ('rlock-zero',0x809051b0,0,False,0),
             ('rlock-write-readback',0x809051b0,6,False,0x12340000),
             ('rlock-end-readback',0x809071ac,6,False,0x12340000),
             ('rlock-outside-write',0x809071b0,1,False,None),
             ('mutex-free',0x1f49000,0,False,0),
             ('mutex-contention',0x1f49000,9,False,8),
             ('mutex-release-reacquire',0x1f49000,10,False,1),
             ('mutex-byte',0x1f49000,3,False,None),
             ('mutex-neighbor',0x1f49004,0,False,None),
             ('ram-disabled',0x80911ae0,11,False,None),
             ('ram-readback64',0x80911ae0,11,False,0x123456789abcdef0),
             ('ram-before',0x80911a78,1,False,None),
             ('ram-after',0x809123a0,1,False,None)]
    for name,address,access,write,value in cases:
        elf = out / (name+'.elf')
        compile_elf(source, 0x40200000, elf, [f'-DADDRESS={address:#x}',f'-DACCESS={access}'])
        rlock = name.startswith('rlock-') and name != 'rlock-disabled'
        mutex = name.startswith('mutex-')
        ram = name.startswith('ram-') and name != 'ram-disabled'
        command = [str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3',
            '-cpu','cortex-a76','-m','2G','-accel','tcg','-smp','1',
            '-display','none','-serial','stdio','-monitor','none','-nic','none',
            '-semihosting-config','enable=on,target=native','-no-reboot',
            '-device',f'loader,file={elf},cpu-num=0',
            '-device',f'nio-smem,snapshot={out / "snapshot.bin"},version-write={"on" if write else "off"},rlock-zero={"on" if rlock else "off"},mutex-model={"on" if mutex else "off"},ram-table-write={"on" if ram else "off"}']
        run = subprocess.run(command,capture_output=True,text=True,env=env,timeout=5)
        lines = run.stdout.splitlines()
        if value is not None:
            passed = lines == ['READ',f'{value:016x}']
        else:
            passed = (len(lines) == 3 and lines[0] == 'ABORT'
                      and int(lines[1],16) >> 26 == 0x25
                      and int(lines[1],16) & 0x3f == 0x10
                      and int(lines[2],16) == (address+4 if name == 'cross-capture-boundary' else address))
        results.append({'case':name,'passed':passed and run.returncode == 0,
                        'stdout':run.stdout,'stderr':run.stderr})
    # Reject damaged or inconsistent captures before launching QEMU.
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        tmp = Path(tmp)
        for file in sample.parent.glob('*.bin'):
            shutil.copyfile(file,tmp/file.name)
        original = json.loads(sample.read_text())
        for name in ('incomplete','bad-hash','out-of-bounds','overlap','bad-pointer','bad-item-chain'):
            report = json.loads(json.dumps(original))
            if name == 'incomplete': report['status'] = 'incomplete'
            if name == 'bad-hash': report['reads']['target_info']['sha256'] = '0'*64
            if name == 'out-of-bounds': report['reads']['target_info']['address'] = '0x81000000'
            if name == 'overlap': report['reads']['target_info']['address'] = '0x80900000'
            if name == 'bad-pointer': report['reads']['pointer']['address'] = '0x1fd4004'
            if name == 'bad-item-chain': report['reads']['item_header_001']['address'] = '0x80901040'
            (tmp/'manifest.json').write_text(json.dumps(report))
            try:
                snapshot(tmp/'manifest.json',tmp/'invalid.bin')
            except ValueError:
                passed = True
            else:
                passed = False
            results.append({'case':name,'passed':passed})
    for name,write in [('qhee-read-only',False),('qhee-version-write',True),('qhee-full-smem',True),
                       ('qhee-ram-seed-a',True),('qhee-ram-seed-b',True)]:
        dest = out / name
        selected_sample = ROOT/'reports/nio-smem-layout-20260928-v5/manifest.json' if name == 'qhee-full-smem' else sample
        if name.startswith('qhee-ram-'): selected_sample = complete_sample
        command = [sys.executable,str(Path(__file__).with_name('run_qemu.py')),
            '--qemu',str(qemu),'--out',str(dest),'--soc-hw-version','0x60080201',
            '--secure-state-sample',str(ROOT/'reports/nio-scm-live-20260928-direct/manifest.json'),
            '--psci-version','0x10001','--smem-sample',str(selected_sample),
            '--devcfg',str(ROOT/'backups/nio-firmware-20260927T163534Z/devcfg_a.img')]
        if write: command += ['--smem-version-write']
        if name == 'qhee-full-smem': command += ['--smem-rlock-zero','--smem-mutex']
        if name.startswith('qhee-ram-'):
            command += ['--smem-rlock-zero','--smem-mutex','--smem-ram-table-write',
                        '--prng-word','0x736d656d' if name.endswith('-a') else '0x12345678']
        subprocess.run(command,stdout=subprocess.DEVNULL,check=True)
        report = json.loads((dest/'manifest.json').read_text())
        fault = (report['stop'] or {}).get('qhee_fault',{})
        passed = (fault == {'address':'0x80900040','pc':'0x8005e658'} if not write else
                  fault == {'address':'0x809051b0','pc':'0x800746d8'})
        if name == 'qhee-full-smem':
            regs = (report['stop'] or {}).get('registers',{})
            passed = (not fault and regs.get('x0') == '0xc2000a02' and regs.get('x1') == '0x22'
                      and regs.get('x2') == '0x80095a28' and regs.get('x3') == '0x4'
                      and 'NIO_SMEM_DENIED' not in report['stderr']
                      and report['stderr'].count('NIO_SMEM_MUTEX write=8 owner=8') == 2
                      and report['stderr'].count('NIO_SMEM_MUTEX write=0 owner=0') == 2)
        if name.startswith('qhee-ram-'):
            passed = (fault == {'address':'0x17c02c','pc':'0x80063aec'}
                      and 'NIO_SMEM_DENIED' not in report['stderr']
                      and report['stdout'].count('MODEL_PRNG_FIXED_WORD_NOT_ENTROPY') == 3
                      and 'NIO_SMEM_RAM_TABLE_WRITE address=0x80911ae0 size=8 value=0x37700000' in report['stderr'])
        results.append({'case':name,'passed':passed,'manifest':str(dest/'manifest.json')})
    results.append({'case':'snapshot-file-unchanged',
                    'passed':hashlib.sha256((out/'snapshot.bin').read_bytes()).hexdigest() == metadata['snapshot_sha256']})
    report = {'results':results,'smem':metadata,
              'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
              'source_sha256':hashlib.sha256(source.with_name('nio-smem.c').read_bytes()).hexdigest(),
              'scope':'Offline single-CPU model; no KVM or phone handoff claim'}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results: print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):
        raise SystemExit('SMEM regression failed')


if __name__ == '__main__':
    main()
