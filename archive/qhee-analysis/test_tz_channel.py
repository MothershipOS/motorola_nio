#!/usr/bin/env python3
"""Check the exact VMID 21/22 channel transition and original QHEE progress."""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

from qhee import ROOT, QheeImage
from run_qemu import compile_elf, decode_stop, environment
from test_replay import caller_source

FID=0xc2000c16
MARKER='MODEL_TZ_CHANNEL_VMID21_22_ASSIGN'
MASK=(1<<21)|(1<<22)


def main():
    out=ROOT/'kernel-work/out/qhee-tz-channel-tests';out.mkdir(parents=True,exist_ok=True)
    qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    sources=Path(__file__).resolve().parent/'emulator';results=[]
    cases=['valid','repeat','disabled','wrong-fid','wrong-arginfo','wrong-el','wrong-immediate',
           'wrong-callsite','bad-buffer','bad-extra-buffer','adjacent-channel','unaligned-region','short-region',
           'long-region','short-destinations','long-destinations','source-owner','first-owner','second-owner',
           'read-only','executable','context','context-size','reserved','last-byte','reversed']
    for name in cases:
        dest=out/name;dest.mkdir(exist_ok=True)
        region=bytearray(struct.pack('<QQ',0x80dc1000,4096))
        source=bytearray(struct.pack('<II',3,0xa5a5a5a5))
        extra=bytearray(struct.pack('<4Q',4,0x8020b000,48,0))
        descriptors=bytearray(b''.join(struct.pack('<IIQII',v,6,0,0,0) for v in (21,22)))
        if name=='adjacent-channel':region[:]=struct.pack('<QQ',0x80ddc000,8192)
        if name=='unaligned-region':struct.pack_into('<Q',region,0,0x80dc1001)
        if name=='short-region':struct.pack_into('<Q',region,8,2048)
        if name=='long-region':struct.pack_into('<Q',region,8,8192)
        if name in ('short-destinations','long-destinations'):struct.pack_into('<Q',extra,16,24 if name.startswith('short') else 72)
        if name=='source-owner':struct.pack_into('<I',source,0,21)
        if name=='first-owner':struct.pack_into('<I',descriptors,0,3)
        if name=='second-owner':struct.pack_into('<I',descriptors,24,42)
        if name in ('read-only','executable'):struct.pack_into('<I',descriptors,4,4 if name=='read-only' else 7)
        for case,offset in [('context',8),('context-size',16),('reserved',20),('last-byte',47)]:
            if name==case:descriptors[offset]=1
        if name=='reversed':descriptors[:]=descriptors[24:]+descriptors[:24]
        blocks={0x8020c000:region,0x8020d000:source,0x801cc390:extra,0x8020b000:descriptors}
        fid=FID if name!='wrong-fid' else 0x42000c16
        arginfo=0x1117 if name!='wrong-arginfo' else 0x1116
        immediate=1 if name=='wrong-immediate' else 0
        assembly,initial=caller_source(fid,arginfo,1 if name=='wrong-el' else 2,immediate)
        values={2:0x8020c000,3:16,4:0x8020d000,5:0x801cc390,6:0,7:0}
        if name=='bad-buffer':values[2]=0xdead0000
        if name=='bad-extra-buffer':values[5]=0xdead0000
        for reg,value in values.items():
            assembly=assembly.replace(f'ldr x{reg}, ={initial[reg]:#x}',f'ldr x{reg}, ={value:#x}');initial[reg]=value
        offset=0x1aa4 if name=='wrong-callsite' else 0x1aa0
        assembly=assembly.replace(f'smc #{immediate}',f'b call\n.org {offset:#x}\ncall:\nsmc #{immediate}',1)
        if name=='repeat':assembly=assembly.replace('sub sp, sp, #272','b _start\nsub sp, sp, #272',1)
        defines=['-DSMEM_TOC_ASSIGN_MODEL']+([] if name=='disabled' else ['-DTZ_CHANNEL_ASSIGN_MODEL'])
        compile_elf(sources/'start.S',0x40200000,dest/'el3.elf',defines)
        symbols=subprocess.check_output(['aarch64-linux-gnu-nm',str(dest/'el3.elf')],text=True)
        ledgers={}
        for ledger in ('smem_toc_ledger','tz_channel_ledger'):
            match=re.search(r'^([0-9a-f]+) . '+ledger+r'$',symbols,re.M)
            if match:ledgers[ledger]=int(match.group(1),16)
        loads=[];expected_memory=[];index=33
        for addr,block in blocks.items():
            for offset in range(0,len(block),8):
                loads += [f'ldr x0, ={addr+offset:#x}','ldr x0, [x0]',f'str x0, [sp, #{8*index}]'];index+=1
                expected_memory.append(int.from_bytes(block[offset:offset+8],'little'))
        for addr in ledgers.values():
            for offset in (0,8):
                loads += [f'ldr x0, ={addr+offset:#x}','ldr x0, [x0]',f'str x0, [sp, #{8*index}]'];index+=1
        stack=(index*8+15)&~15
        assembly=assembly.replace('sub sp, sp, #272',f'sub sp, sp, #{stack}').replace('add x0, sp, #272',f'add x0, sp, #{stack}')
        assembly=assembly.replace('mov x20, sp','\n'.join(loads)+'\nmov x20, sp').replace('mov x21, #33',f'mov x21, #{index}')
        (dest/'caller.S').write_text(assembly);compile_elf(dest/'caller.S',0x80040000,dest/'caller.elf')
        cmd=[str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3','-cpu','cortex-a76',
             '-m','2G','-smp','1','-accel','tcg','-display','none','-serial','stdio','-monitor','none',
             '-nic','none','-semihosting-config','enable=on,target=native','-no-reboot',
             '-device',f'loader,file={dest/"el3.elf"},cpu-num=0','-device',f'loader,file={dest/"caller.elf"}']
        for addr,block in blocks.items():
            path=dest/f'{addr:x}.bin';path.write_bytes(block)
            cmd+=['-device',f'loader,file={path},addr={addr:#x},force-raw=on']
        run=subprocess.run(cmd,capture_output=True,env=env,timeout=5);text=run.stdout.decode(errors='replace')
        if name=='valid':
            expected=[0,0]+initial[2:]+[0x803f0000,0xa0000000]+expected_memory+[8,0,MASK,MASK]
            lines=text.splitlines();passed=len(lines)==len(expected)+1 and lines[0]==MARKER and [int(v,16) for v in lines[1:]]==expected
        else:
            regs=(decode_stop(run.stdout) or {}).get('registers',{})
            passed=(regs.get('x0')==hex(fid) and regs.get('x1')==hex(arginfo)
                    and regs.get('x2')==hex(initial[2]) and regs.get('x3')==hex(initial[3])
                    and text.count(MARKER)==(1 if name=='repeat' else 0))
            match=re.search(r'MODEL_SMEM_TOC_LEDGER_OWNERS_PERMISSIONS:\n([0-9a-f]+)\n([0-9a-f]+)',text)
            passed=passed and bool(match) and [int(v,16) for v in match.groups()]==[8,0]
            if name!='disabled':
                match=re.search(r'MODEL_TZ_CHANNEL_LEDGER_READERS_WRITERS:\n([0-9a-f]+)\n([0-9a-f]+)',text)
                passed=passed and bool(match) and [int(v,16) for v in match.groups()]==([MASK,MASK] if name=='repeat' else [8,0])
        results.append({'case':name,'passed':bool(passed and run.returncode==0),'stdout':text,'stderr':run.stderr.decode(errors='replace')})
    image=QheeImage();descriptor=image.read(0x800a2c70,56)
    results.append({'case':'pinned-channel-descriptor','passed':struct.unpack('<QQ4I4II4x',descriptor)==
                    (0x80dc1000,4096,21,22,0,0,6,6,0,0,2)})
    base=[sys.executable,str(Path(__file__).with_name('run_qemu.py')),
          '--qemu',str(qemu),'--soc-hw-version','0x60080201',
          '--devcfg',str(ROOT/'backups/nio-firmware-20260927T163534Z/devcfg_a.img'),
          '--secure-state-sample',str(ROOT/'reports/nio-scm-live-20260928-direct/manifest.json'),
          '--psci-version','0x10001','--smem-sample',str(ROOT/'reports/nio-smem-layout-20260928-v7/manifest.json'),
          '--smem-version-write','--smem-rlock-zero','--smem-mutex','--smem-ram-table-write',
          '--prng-word','0x736d656d','--gcc-mmu-clocks','off',
          '--smmu-ids',str(ROOT/'reports/nio-mmu-ids-active-20260928/manifest.json'),
          '--smmu-firmware-counts','--smmu-control','--smmu-contexts','--qcom-timer',
          '--qfprom-sample',str(ROOT/'reports/nio-gcc-mmu-checkpoint-20260928/manifest.json'),
          '--cmd-db-sample',str(ROOT/'reports/nio-cmd-db-pointer-20261005/manifest.json'),
          '--nonsecure-query-unsupported','--out','PLACEHOLDER']
    for clocks in ('off','on'):
        dest=out/('qhee-'+clocks);cmd=base[:]
        cmd[cmd.index('--out')+1]=str(dest);cmd[cmd.index('--gcc-mmu-clocks')+1]=clocks
        subprocess.run(cmd+['--smem-toc-assign','--smem-partition-assign','--tz-channel-assign'],stdout=subprocess.DEVNULL,check=True)
        report=json.loads((dest/'manifest.json').read_text());stop=report['stop'] or {}
        inspection=dest/'inspection'
        subprocess.run([sys.executable,str(Path(__file__).with_name('inspect_assign_mem.py')),
                        '--manifest',str(dest/'manifest.json'),'--skip','12','--out',str(inspection)],stdout=subprocess.DEVNULL,check=True)
        state=json.loads((inspection/'buffers.json').read_text());ledger=state['ledgers']['smem_partition_ledger']['words']
        passed=(report['tz_channel_assign_model']['accepted_transitions']==1
                and report['smem_toc_assign_model']['accepted_transitions']==1
                and report['smem_partition_assign_model']['accepted_transitions']==10
                and not stop.get('qhee_fault') and stop.get('registers',{}).get('x0')==hex(FID)
                and 'NIO_MMU_DENIED' not in report['stderr'] and 'NIO_SMEM_DENIED' not in report['stderr']
                and state['ledgers']['tz_channel_ledger']['words']==[MASK,MASK]
                and all(ledger[i+2:i+4]==ledger[i+6:i+8] for i in range(0,80,8))
                and state['region']==[0x80ddc000,8192] and state['source_vmids']==[3]
                and state['destinations']==[{'vmid':v,'permission':6,'context':0,'context_size':0,'reserved':0} for v in (21,42)])
        results.append({'case':'qhee-'+clocks,'passed':passed,'manifest':str(dest/'manifest.json'),'inspection':str(inspection/'buffers.json')})
    run=subprocess.run([sys.executable,str(Path(__file__).with_name('run_qemu.py')),'--tz-channel-assign'],capture_output=True,text=True)
    results.append({'case':'requires-pinned-contract','passed':run.returncode==2 and 'requires --smem-toc-assign' in run.stderr})
    report={'results':results,'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
        (sources/'start.S',sources/'smem_assign.S',sources/'tz_channel_assign.S',Path(__file__))},
        'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
        'scope':'Exact offline VMID 21/22 ownership contract; not TrustZone enforcement or physical KVM'}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):raise SystemExit('TZ channel regression failed')


if __name__=='__main__':main()
