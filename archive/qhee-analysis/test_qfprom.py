#!/usr/bin/env python3
"""Validate exact QFPROM replay and the resulting original-QHEE MMU boundary."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from qhee import ROOT
from run_qemu import compile_elf, environment, qfprom_sample


def main():
    out=ROOT/'kernel-work/out/qhee-qfprom-tests'
    out.mkdir(parents=True,exist_ok=True)
    sample=ROOT/'reports/nio-gcc-mmu-checkpoint-20260928/manifest.json'
    value,metadata=qfprom_sample(sample)
    qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    sources=Path(__file__).resolve().parent/'emulator'
    results=[]
    cases=[('captured-word',0x784218,0,True,value),
           ('nonzero-word',0x784218,0,True,0xa5a5a5a5),
           ('disabled',0x784218,0,False,None),
           ('write32',0x784218,1,True,None),
           ('read8',0x784218,3,True,None),
           ('read16',0x784218,5,True,None),
           ('read64',0x784218,4,True,None),
           ('write8',0x784218,7,True,None),
           ('write64',0x784218,8,True,None),
           ('previous-word',0x784214,0,True,None),
           ('next-word',0x78421c,0,True,None),
           ('aperture-start',0x784000,0,True,None),
           ('aperture-end',0x784ffc,0,True,None)]
    for name,address,access,enabled,expected in cases:
        elf=out/(name+'.elf')
        compile_elf(sources/'register_probe.S',0x40200000,elf,
                    [f'-DADDRESS={address:#x}',f'-DACCESS={access}'])
        cmd=[str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3',
             '-cpu','cortex-a76','-m','2G','-smp','1','-accel','tcg',
             '-display','none','-serial','stdio','-monitor','none','-nic','none',
             '-semihosting-config','enable=on,target=native','-no-reboot',
             '-device',f'loader,file={elf},cpu-num=0']
        if enabled: cmd+=['-device',f'nio-qfprom,value={0xa5a5a5a5 if name=="nonzero-word" else value:#x}']
        run=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=5)
        lines=run.stdout.splitlines()
        if expected is None:
            passed=(len(lines)==3 and lines[0]=='ABORT' and int(lines[1],16)>>26==0x25
                    and int(lines[1],16)&0x3f==0x10 and int(lines[2],16)==address)
        else: passed=lines==['READ',f'{expected:016x}']
        results.append({'case':name,'passed':passed and run.returncode==0,
                        'stdout':run.stdout,'stderr':run.stderr})
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        path=Path(tmp)/'sample.json'
        for name in ('failed-read','wrong-address','wrong-width','multiple-values','overflow','negative','missing','junk'):
            report=json.loads(sample.read_text());check=report['checks']['qfprom_784218']
            if name=='failed-read':check['status']=1
            if name=='wrong-address':check['command']='devmem 0x0078421c 32'
            if name=='wrong-width':check['command']='devmem 0x00784218 64'
            if name=='multiple-values':check['stdout']='0x00000000\n0x00000001\n'
            if name=='overflow':check['stdout']='0x100000000\n'
            if name=='negative':check['stdout']='-1\n'
            if name=='missing':del report['checks']['qfprom_784218']
            if name=='junk':check['stdout']='read failed\n0x00000000\n'
            path.write_text(json.dumps(report))
            try:qfprom_sample(path)
            except ValueError:passed=True
            else:passed=False
            results.append({'case':name,'passed':passed})
    for clocks,enabled,failure in [('off',False,True),('off',True,False),('off',True,True),('on',True,True)]:
        name=f'qhee-{clocks}-qfprom-{enabled}-query-failure-{failure}'
        dest=out/name
        cmd=[sys.executable,str(Path(__file__).with_name('run_qemu.py')),
             '--qemu',str(qemu),'--out',str(dest),'--soc-hw-version','0x60080201',
             '--devcfg',str(ROOT/'backups/nio-firmware-20260927T163534Z/devcfg_a.img'),
             '--secure-state-sample',str(ROOT/'reports/nio-scm-live-20260928-direct/manifest.json'),
             '--psci-version','0x10001','--smem-sample',str(ROOT/'reports/nio-smem-layout-20260928-v7/manifest.json'),
             '--smem-version-write','--smem-rlock-zero','--smem-mutex','--smem-ram-table-write',
             '--prng-word','0x736d656d','--gcc-mmu-clocks',clocks,
             '--smmu-ids',str(ROOT/'reports/nio-mmu-ids-active-20260928/manifest.json'),
             '--qcom-timer','--smmu-control']
        if enabled:cmd+=['--qfprom-sample',str(sample)]
        if failure:cmd+=['--nonsecure-query-unsupported']
        subprocess.run(cmd,stdout=subprocess.DEVNULL,check=True)
        report=json.loads((dest/'manifest.json').read_text());stop=report['stop'] or {}
        if not enabled:passed=stop.get('qhee_fault')=={'address':'0x784218','pc':'0x8006a908'}
        elif not failure:passed=stop.get('registers',{}).get('x0')=='0xc2000310' and 'NIO_QFPROM_READ' not in report['stderr']
        else:
            passed=(report['outcome']=='qhee_fatal_watchdog_request'
                    and stop.get('qhee_fault')=={'address':'0x80901010','pc':'0x8005ea9c'}
                    and 'ESR_EL2(96000006)' in report['stdout']
                    and 'NIO_QFPROM_READ address=0x00784218 value=0x00000000 size=4' in report['stderr']
                    and 'NIO_SMEM_DENIED' not in report['stderr'])
        results.append({'case':name,'passed':passed,'manifest':str(dest/'manifest.json')})
    report={'results':results,'qfprom':metadata,
            'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
            'source_sha256':hashlib.sha256((sources/'nio-qfprom.c').read_bytes()).hexdigest(),
            'scope':'Offline read replay. The new CPU translation fault is a failure, not a completed handoff.'}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):raise SystemExit('QFPROM regression failed')


if __name__=='__main__':main()
