#!/usr/bin/env python3
"""Check firmware-derived counts, bounded context controls and QHEE progress."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from qhee import ROOT,QheeImage
from run_qemu import compile_elf,environment,smmu_ids_sample
from smmu_config import firmware_counts


def main():
    out=ROOT/'kernel-work/out/qhee-smmu-context-tests';out.mkdir(parents=True,exist_ok=True)
    qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    sources=Path(__file__).resolve().parent/'emulator'
    original,_=smmu_ids_sample(ROOT/'reports/nio-mmu-ids-active-20260928/manifest.json')
    properties,derived=firmware_counts(original,QheeImage())
    results=[{'case':'firmware-counts-project-to-capture','passed':
              [(b['model_contexts'],b['model_streams'],len(b['reserved_contexts']),b['reserved_streams']) for b in derived['banks']]==[(95,128,21,41),(8,7,3,1)]},
             {'case':'vmid5-context86','passed':any(e['vmid']==5 and e['index']==86 for e in derived['banks'][0]['reserved_contexts'])},
             {'case':'no-invented-feature-bits','passed':all(properties[n+'-id0']&~255==original[n+'-id0']&~255 for n in ('apps','gpu'))}]
    for name,key in [('context-mismatch','apps-id1'),('stream-mismatch','apps-id0')]:
        bad=dict(original);bad[key]+=1
        try:firmware_counts(bad,QheeImage())
        except ValueError:passed=True
        else:passed=False
        results.append({'case':name,'passed':passed})
    fake=QheeImage();fake.data=fake.data[:-1]+bytes([fake.data[-1]^1])
    try:firmware_counts(original,fake)
    except ValueError:passed=True
    else:passed=False
    results.append({'case':'firmware-hash-required','passed':passed})
    opts='nio-gcc-mmu,ids-enabled=on,control=on,'+','.join(f'{k}={v}' for k,v in properties.items())
    template=(sources/'register_probe.S').read_text();before,rest=template.split('#if ACCESS == 0',1);_,after=rest.split('#endif',1)
    write='ldr w19, =0x12345000\nstr w19, [x8]\nldr w19, [x8]'
    cases=[('vmid5-ttbr',0x150d6020,write,True,0x12345000),
           ('last-app-bank',0x150de030,write,True,0x12345000),
           ('past-app-bank',0x150df020,'ldr w19,[x8]',True,None),
           ('last-gpu-bank',0x3daf020,write,True,0x12345000),
           ('contexts-disabled',0x150d6020,'ldr w19,[x8]',False,None),
           ('unknown-register',0x150d6014,'ldr w19,[x8]',True,None),
           ('wide-register',0x150d6020,'ldr x19,[x8]',True,None),
           ('byte-register',0x150d6020,'ldrb w19,[x8]',True,None),
           ('tlb-idle',0x150d67f4,'ldr w19,[x8]',True,0),
           ('tlb-readonly',0x150d67f4,'str wzr,[x8]',True,None),
           ('tlb-sync',0x150d67f0,'str wzr,[x8]\nldr w19,[x8]',True,0),
           ('restore-zero',0x150d605c,'str wzr,[x8]\nsub x8,x8,#4\nldr w19,[x8]',True,0),
           ('restore-nonzero',0x150d605c,'mov w19,#1\nstr w19,[x8]',True,None),
           ('restore-read-denied',0x150d605c,'ldr w19,[x8]',True,None),
           ('bank-isolation',0x150d6020,'mov w19,#1\nstr w19,[x8]\nsub x8,x8,#1,lsl #12\nldr w19,[x8]',True,0)]
    for name,address,code,enabled,expected in cases:
        source=out/(name+'.S');source.write_text(before+code+'\n'+after)
        elf=out/(name+'.elf');compile_elf(source,0x40200000,elf,[f'-DADDRESS={address:#x}'])
        cmd=[str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3','-cpu','cortex-a76',
             '-m','2G','-smp','1','-accel','tcg','-display','none','-serial','stdio','-monitor','none',
             '-nic','none','-semihosting-config','enable=on,target=native','-no-reboot',
             '-device',f'loader,file={elf},cpu-num=0','-device',opts+(',contexts=on' if enabled else '')]
        r=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=5);lines=r.stdout.splitlines()
        passed=(lines==['READ',f'{expected:016x}'] if expected is not None else
                len(lines)==3 and lines[0]=='ABORT' and int(lines[1],16)>>26==0x25
                and int(lines[1],16)&0x3f==0x10 and int(lines[2],16)==address)
        results.append({'case':name,'passed':passed and r.returncode==0,'stdout':r.stdout,'stderr':r.stderr})
    # Replay the exact emitted CLI inputs; change only optional model switches.
    fixed=[sys.executable,str(Path(__file__).with_name('run_qemu.py')),'--qemu',str(qemu),
           '--soc-hw-version','0x60080201','--devcfg',str(ROOT/'backups/nio-firmware-20260927T163534Z/devcfg_a.img'),
           '--secure-state-sample',str(ROOT/'reports/nio-scm-live-20260928-direct/manifest.json'),
           '--psci-version','0x10001','--smem-sample',str(ROOT/'reports/nio-smem-layout-20260928-v7/manifest.json'),
           '--smem-version-write','--smem-rlock-zero','--smem-mutex','--smem-ram-table-write',
           '--prng-word','0x736d656d','--smmu-ids',str(ROOT/'reports/nio-mmu-ids-active-20260928/manifest.json'),
           '--smmu-firmware-counts','--smmu-control','--qcom-timer',
           '--qfprom-sample',str(ROOT/'reports/nio-gcc-mmu-checkpoint-20260928/manifest.json'),
           '--nonsecure-query-unsupported']
    for name,clocks,contexts,pointer in [('no-context-model','off',False,False),('contexts-only','off',True,False),
                                       ('full-off','off',True,True),('full-on','on',True,True)]:
        dest=out/name;cmd=fixed+['--gcc-mmu-clocks',clocks,'--out',str(dest)]
        if contexts:cmd+=['--smmu-contexts']
        if pointer:cmd+=['--cmd-db-sample',str(ROOT/'reports/nio-cmd-db-pointer-20261005/manifest.json')]
        subprocess.run(cmd,stdout=subprocess.DEVNULL,check=True)
        r=json.loads((dest/'manifest.json').read_text());stop=r['stop'] or {}
        if not contexts:passed=stop.get('qhee_fault')=={'address':'0x150de020','pc':'0x80059330'}
        elif not pointer:passed=stop.get('qhee_fault')=={'address':'0xc3f000c','pc':'0x8006ca84'}
        else:passed=(not stop.get('qhee_fault') and stop['registers']['x0']=='0xc2000c16'
                     and stop['registers']['x1']=='0x1117' and 'VMID 5 not support' not in r['stdout']
                     and 'NIO_MMU_DENIED' not in r['stderr'] and 'NIO_SMEM_DENIED' not in r['stderr'])
        results.append({'case':name,'passed':passed,'manifest':str(dest/'manifest.json')})
    report={'results':results,'derived_counts':derived,'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
            'model_sha256':hashlib.sha256((sources/'nio-gcc-mmu.c').read_bytes()).hexdigest(),
            'scope':'Offline control path and firmware-derived count hypothesis; no raw EL2 capture or DMA claim'}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):raise SystemExit('SMMU context tests failed')


if __name__=='__main__':main()
