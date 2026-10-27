#!/usr/bin/env python3
"""Validate exact Command-database pointer replay and the resulting original-QHEE MMU boundary."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from qhee import ROOT
from run_qemu import compile_elf, environment, cmd_db_sample


def main():
    out=ROOT/'kernel-work/out/qhee-cmd-db-tests'
    out.mkdir(parents=True,exist_ok=True)
    sample=ROOT/'reports/nio-cmd-db-pointer-20261005/manifest.json'
    value,metadata=cmd_db_sample(sample)
    qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    sources=Path(__file__).resolve().parent/'emulator'
    results=[]
    cases=[('captured-word',0xc3f000c,0,True,value),
           ('nonzero-word',0xc3f000c,0,True,0xa5a5a5a5),
           ('disabled',0xc3f000c,0,False,None),
           ('write32',0xc3f000c,1,True,None),
           ('read8',0xc3f000c,3,True,None),
           ('read16',0xc3f000c,5,True,None),
           ('read64',0xc3f000c,4,True,None),
           ('write8',0xc3f000c,7,True,None),
           ('write64',0xc3f000c,8,True,None),
           ('previous-word',0xc3f0008,0,True,None),
           ('next-word',0xc3f0010,0,True,None),
           ('aperture-start',0xc3f0000,0,True,None),
           ('aperture-end',0xc3f0ffc,0,True,None)]
    for name,address,access,enabled,expected in cases:
        elf=out/(name+'.elf')
        compile_elf(sources/'register_probe.S',0x40200000,elf,
                    [f'-DADDRESS={address:#x}',f'-DACCESS={access}'])
        cmd=[str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3',
             '-cpu','cortex-a76','-m','2G','-smp','1','-accel','tcg',
             '-display','none','-serial','stdio','-monitor','none','-nic','none',
             '-semihosting-config','enable=on,target=native','-no-reboot',
             '-device',f'loader,file={elf},cpu-num=0']
        if enabled: cmd+=['-device',f'nio-cmd-db-pointer,value={0xa5a5a5a5 if name=="nonzero-word" else value:#x}']
        run=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=5)
        lines=run.stdout.splitlines()
        if expected is None:
            passed=(len(lines)==3 and lines[0]=='ABORT' and int(lines[1],16)>>26==0x25
                    and int(lines[1],16)&0x3f==0x10 and int(lines[2],16)==(address+4 if name=='read64' else address))
        else: passed=lines==['READ',f'{expected:016x}']
        results.append({'case':name,'passed':passed and run.returncode==0,
                        'stdout':run.stdout,'stderr':run.stderr})
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        path=Path(tmp)/'sample.json'
        for name in ('failed-read','wrong-address','wrong-width','multiple-values','overflow','negative','missing','junk'):
            report=json.loads(sample.read_text());check=report['checks']['cmd_db_pointer']
            if name=='failed-read':check['status']=1
            if name=='wrong-address':check['command']='devmem 0x0c3f0010 32'
            if name=='wrong-width':check['command']='devmem 0x0c3f000c 64'
            if name=='multiple-values':check['stdout']='0x00000000\n0x00000001\n'
            if name=='overflow':check['stdout']='0x100000000\n'
            if name=='negative':check['stdout']='-1\n'
            if name=='missing':del report['checks']['cmd_db_pointer']
            if name=='junk':check['stdout']='read failed\n0x00000000\n'
            path.write_text(json.dumps(report))
            try:cmd_db_sample(path)
            except ValueError:passed=True
            else:passed=False
            results.append({'case':name,'passed':passed})
    report={'results':results,'cmd_db_pointer':metadata,
            'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
            'source_sha256':hashlib.sha256((sources/'nio-cmd-db-pointer.c').read_bytes()).hexdigest(),
            'scope':'Offline exact-word SRAM replay; no surrounding SRAM or writes modeled.'}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):raise SystemExit('Command-database pointer regression failed')


if __name__=='__main__':main()
