#!/usr/bin/env python3
"""Validate exact TZ-log pointer replay and the resulting original-QHEE MMU boundary."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from qhee import ROOT
from run_qemu import compile_elf, environment, tz_log_sample


def main():
    out=ROOT/'kernel-work/out/qhee-tz-log-tests'
    out.mkdir(parents=True,exist_ok=True)
    sample=ROOT/'reports/nio-tz-log-pointer-20261005/manifest.json'
    value,metadata=tz_log_sample(sample)
    qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    sources=Path(__file__).resolve().parent/'emulator'
    results=[]
    cases=[('captured-word',0x146bf720,0,True,value),
           ('nonzero-word',0x146bf720,0,True,0xa5a5a5a5),
           ('disabled',0x146bf720,0,False,0xffffffff),
           ('write32',0x146bf720,1,True,None),
           ('read8',0x146bf720,3,True,None),
           ('read16',0x146bf720,5,True,None),
           ('read64',0x146bf720,4,True,None),
           ('write8',0x146bf720,7,True,None),
           ('write64',0x146bf720,8,True,None),
           ('previous-word',0x146bf71c,0,True,None),
           ('next-word',0x146bf724,0,True,None),
           ('aperture-start',0x146bf000,0,True,None),
           ('aperture-end',0x146bfffc,0,True,None)]
    for name,address,access,enabled,expected in cases:
        elf=out/(name+'.elf')
        compile_elf(sources/'register_probe.S',0x40200000,elf,
                    [f'-DADDRESS={address:#x}',f'-DACCESS={access}'])
        cmd=[str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3',
             '-cpu','cortex-a76','-m','2G','-smp','1','-accel','tcg',
             '-display','none','-serial','stdio','-monitor','none','-nic','none',
             '-semihosting-config','enable=on,target=native','-no-reboot',
             '-device',f'loader,file={elf},cpu-num=0']
        if enabled: cmd+=['-device',f'nio-tz-log-pointer,value={0xa5a5a5a5 if name=="nonzero-word" else value:#x}']
        run=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=5)
        lines=run.stdout.splitlines()
        if expected is None:
            passed=(len(lines)==3 and lines[0]=='ABORT' and int(lines[1],16)>>26==0x25
                    and int(lines[1],16)&0x3f==0x10 and int(lines[2],16)==address)
        else: passed=lines==['READ',f'{expected:016x}']
        results.append({'case':name,'passed':passed and run.returncode==0,
                        'stdout':run.stdout,'stderr':run.stderr})
    for name in ('valid-publication','disabled-publication','wrong-value','wrong-width','adjacent-write','repeat-publication','publication-readback'):
        dest=out/name;dest.mkdir(exist_ok=True)
        source=(sources/'register_probe.S').read_text()
        snippet='ldr x19, =0x200080209000\n    str x19, [x8]'
        if name=='wrong-value':snippet=snippet.replace('0x200080209000','0x20008020a000')
        if name=='wrong-width':snippet=snippet.replace('str x19','str w19')
        if name=='repeat-publication':snippet+='\n    str x19, [x8]'
        if name=='publication-readback':snippet+='\n    ldr x19, [x8]'
        source=source.replace('ldr x19, =0x123456789abcdef0\n    str x19, [x8]\n    ldr x19, [x8]',snippet)
        (dest/'probe.S').write_text(source)
        addr=0x146bfb38 if name=='adjacent-write' else 0x146bfb30
        compile_elf(dest/'probe.S',0x40200000,dest/'probe.elf',[f'-DADDRESS={addr:#x}','-DACCESS=11'])
        cmd=[str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3','-cpu','cortex-a76',
            '-m','2G','-smp','1','-accel','tcg','-display','none','-serial','stdio','-monitor','none','-nic','none',
            '-semihosting-config','enable=on,target=native','-no-reboot',
            '-device',f'loader,file={dest/"probe.elf"},cpu-num=0',
            '-device',f'nio-tz-log-pointer,value={value:#x},publications={"off" if name=="disabled-publication" else "on"}']
        run=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=5)
        lines=run.stdout.splitlines()
        success=name=='valid-publication'
        passed=(lines==['READ','0000200080209000'] if success else
            len(lines)==3 and lines[0]=='ABORT' and int(lines[1],16)>>26==0x25 and int(lines[1],16)&0x3f==0x10 and int(lines[2],16)==addr)
        passed=passed and run.stderr.count('NIO_IMEM_HYP_LOG_PUBLISH')==(1 if name in ('valid-publication','repeat-publication','publication-readback') else 0)
        results.append({'case':name,'passed':passed and run.returncode==0,'stdout':run.stdout,'stderr':run.stderr})
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        path=Path(tmp)/'sample.json'
        for name in ('failed-read','wrong-address','wrong-width','multiple-values','overflow','negative','missing','junk'):
            report=json.loads(sample.read_text());check=report['checks']['tz_log_pointer']
            if name=='failed-read':check['status']=1
            if name=='wrong-address':check['command']='devmem 0x146bf724 32'
            if name=='wrong-width':check['command']='devmem 0x146bf720 64'
            if name=='multiple-values':check['stdout']='0x00000000\n0x00000001\n'
            if name=='overflow':check['stdout']='0x100000000\n'
            if name=='negative':check['stdout']='-1\n'
            if name=='missing':del report['checks']['tz_log_pointer']
            if name=='junk':check['stdout']='read failed\n0x00000000\n'
            path.write_text(json.dumps(report))
            try:tz_log_sample(path)
            except ValueError:passed=True
            else:passed=False
            results.append({'case':name,'passed':passed})
    report={'results':results,'tz_log_pointer':metadata,
            'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
            'source_sha256':hashlib.sha256((sources/'nio-tz-log-pointer.c').read_bytes()).hexdigest(),
            'scope':'Offline exact-word TZ pointer replay and opt-in one-shot log publication; no general IMEM memory.'}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):raise SystemExit('TZ-log pointer regression failed')


if __name__=='__main__':main()
