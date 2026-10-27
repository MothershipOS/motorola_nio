#!/usr/bin/env python3
"""Check exact SMEM ownership transition, rejection, register/buffer preservation and QHEE progress."""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

from qhee import ROOT
from run_qemu import compile_elf, decode_stop, environment
from test_replay import caller_source

FID=0xc2000c16
OWNERS=0x1004c000078
MARKER='MODEL_SMEM_TOC_ASSIGN_READ_ONLY_8_OWNERS'


def main():
    out=ROOT/'kernel-work/out/qhee-smem-assign-tests';out.mkdir(parents=True,exist_ok=True)
    qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    sources=Path(__file__).resolve().parent/'emulator'
    results=[]
    cases=['valid-preserves-registers-buffers','repeated-stale-owner','disabled','wrong-fid','wrong-arginfo',
           'wrong-el','wrong-immediate','wrong-callsite','region-pointer','region-descriptor-size',
           'source-pointer','extended-pointer','x6-nonzero','x7-nonzero','source-size',
           'destination-pointer','destination-size','reserved-argument','region-start','region-size',
           'source-owner','destination-owner','destination-permission','destination-context',
           'destination-context-size','destination-reserved','last-destination-byte']
    contracts=json.loads((ROOT/'reports/qhee-offline/smem-partition-contracts.json').read_text())['entries']
    cases += [f'partition-{i}' for i in range(10)] + ['partition-unlisted','partition-partial',
        'partition-write-escalation','partition-exec-escalation','partition-stale','partition-disabled',
        'partition-wrong-size','partition-reordered','partition-source-owner']
    for name in cases:
        partition=name.startswith('partition-')
        part_index=int(name.split('-')[1]) if partition and name.split('-')[1].isdigit() else 3
        valid_partition=partition and name.split('-')[1].isdigit()
        dest=out/name;dest.mkdir(exist_ok=True)
        region=struct.pack('<QQ',0x80aff000,0x1000)
        source=struct.pack('<II',3,0xa5a5a5a5)
        extra=struct.pack('<QQQQ',4,0x8020b000,192,0)
        destinations=b''.join(struct.pack('<IIQII',vmid,4,0,0,0) for vmid in [3,6,5,30,27,4,40,26])
        if partition:
            contract=contracts[part_index]
            region=struct.pack('<QQ',int(contract['start'],0),int(contract['size'],0))
            destinations=b''.join(struct.pack('<IIQII',d['vmid'],d['permission'],0,0,0) for d in contract['destinations'])
            extra=struct.pack('<QQQQ',4,0x8020b000,len(destinations),0)
            if name=='partition-unlisted':region=struct.pack('<QQ',0x80dc1000,0x1000)
            if name=='partition-partial':region=struct.pack('<QQ',int(contract['start'],0)+4096,int(contract['size'],0)-4096)
            if name=='partition-write-escalation':destinations=destinations[:4]+struct.pack('<I',6)+destinations[8:]
            if name=='partition-exec-escalation':destinations=destinations[:4]+struct.pack('<I',5)+destinations[8:]
            if name=='partition-wrong-size':extra=struct.pack('<QQQQ',4,0x8020b000,len(destinations)+24,0)
            if name=='partition-reordered':destinations=destinations[24:48]+destinations[:24]+destinations[48:]
            if name=='partition-source-owner':source=struct.pack('<II',6,0xa5a5a5a5)
        blocks={0x8020c000:bytearray(region),0x8020d000:bytearray(source),
                0x801cc390:bytearray(extra),0x8020b000:bytearray(destinations)}
        mutations={'source-size':(0x801cc390,0,8),'destination-pointer':(0x801cc390,8,0xdead0000),
                   'destination-size':(0x801cc390,16,193),'reserved-argument':(0x801cc390,24,1),
                   'region-start':(0x8020c000,0,0x80afe000),'region-size':(0x8020c000,8,0x2000)}
        if name in mutations:
            address,offset,value=mutations[name];struct.pack_into('<Q',blocks[address],offset,value)
        for case,address,offset in [('source-owner',0x8020d000,0),('destination-owner',0x8020b000,0),
                                    ('destination-permission',0x8020b000,4),('destination-context',0x8020b000,8),
                                    ('destination-context-size',0x8020b000,16),('destination-reserved',0x8020b000,20),
                                    ('last-destination-byte',0x8020b000,191)]:
            if name==case:blocks[address][offset]^=1
        fid=0x42000c16 if name=='wrong-fid' else FID
        arginfo=0x1116 if name=='wrong-arginfo' else 0x1117
        immediate=1 if name=='wrong-immediate' else 0
        assembly,initial=caller_source(fid,arginfo,1 if name=='wrong-el' else 2,immediate)
        registers={2:0x8020c000,3:16,4:0x8020d000,5:0x801cc390,6:0,7:0}
        changes={'region-pointer':(2,0xdead0000),'region-descriptor-size':(3,32),
                 'source-pointer':(4,0xdead0000),'extended-pointer':(5,0xdead0000),
                 'x6-nonzero':(6,1),'x7-nonzero':(7,1)}
        if name in changes:
            index,value=changes[name];registers[index]=value
        for index,value in registers.items():
            assembly=assembly.replace(f'ldr x{index}, ={initial[index]:#x}',f'ldr x{index}, ={value:#x}')
            initial[index]=value
        call_offset=0x1aa4 if name=='wrong-callsite' else 0x1aa0
        assembly=assembly.replace(f'smc #{immediate}',f'b assignment_call\n.org {call_offset:#x}\nassignment_call:\nsmc #{immediate}',1)
        if name in ('repeated-stale-owner','partition-stale'):
            assembly=assembly.replace('sub sp, sp, #272','b _start\nsub sp, sp, #272',1)
        defines=[] if name=='disabled' else ['-DSMEM_TOC_ASSIGN_MODEL']
        if partition and name!='partition-disabled':defines+=['-DSMEM_PARTITION_ASSIGN_MODEL']
        compile_elf(sources/'start.S',0x40200000,dest/'el3.elf',defines)
        symbols=subprocess.check_output(['aarch64-linux-gnu-nm',str(dest/'el3.elf')],text=True)
        match=re.search(r'^([0-9a-f]+) . smem_toc_ledger$',symbols,re.M)
        ledger=int(match.group(1),16) if match else 0
        match=re.search(r'^([0-9a-f]+) . smem_partition_ledger$',symbols,re.M)
        partition_ledger=int(match.group(1),16) if match else 0
        expected_words=[];loads=[];index=33
        for address,block in blocks.items():
            for offset in range(0,len(block),8):
                expected_words.append(int.from_bytes(block[offset:offset+8],'little'))
                loads += [f'ldr x0, ={address+offset:#x}','ldr x0, [x0]',f'str x0, [sp, #{index*8}]'];index+=1
        if ledger:
            for offset in (0,8):
                loads += [f'ldr x0, ={ledger+offset:#x}','ldr x0, [x0]',f'str x0, [sp, #{index*8}]'];index+=1
        if partition_ledger:
            for entry in range(10):
                for offset in (48,56):
                    loads += [f'ldr x0, ={partition_ledger+64*entry+offset:#x}','ldr x0, [x0]',f'str x0, [sp, #{index*8}]'];index+=1
        partition_state=[]
        for i,entry in enumerate(contracts):
            if i==part_index and (valid_partition or name=='partition-stale'):
                partition_state += [sum(1<<d['vmid'] for d in entry['destinations']),
                                    sum(1<<d['vmid'] for d in entry['destinations'] if d['permission']&2)]
            else:partition_state += [8,0]
        stack=(index*8+15)&~15
        assembly=assembly.replace('sub sp, sp, #272',f'sub sp, sp, #{stack}').replace('add x0, sp, #272',f'add x0, sp, #{stack}')
        assembly=assembly.replace('mov x20, sp','\n'.join(loads)+'\nmov x20, sp').replace('mov x21, #33',f'mov x21, #{index}')
        (dest/'caller.S').write_text(assembly);compile_elf(dest/'caller.S',0x80040000,dest/'caller.elf')
        cmd=[str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3','-cpu','cortex-a76',
             '-m','2G','-smp','1','-accel','tcg','-display','none','-serial','stdio','-monitor','none',
             '-nic','none','-semihosting-config','enable=on,target=native','-no-reboot',
             '-device',f'loader,file={dest/"el3.elf"},cpu-num=0','-device',f'loader,file={dest/"caller.elf"}']
        for address,block in blocks.items():
            path=dest/f'{address:x}.bin';path.write_bytes(block)
            cmd+=['-device',f'loader,file={path},addr={address:#x},force-raw=on']
        run=subprocess.run(cmd,capture_output=True,env=env,timeout=5);text=run.stdout.decode(errors='replace')
        if name=='valid-preserves-registers-buffers' or valid_partition:
            expected=[0,0]+initial[2:]+[0x803f0000,0xa0000000]+expected_words+([8,0]+partition_state if partition else [OWNERS,4])
            lines=text.splitlines()
            passed=len(lines)==len(expected)+1 and lines[0]==('MODEL_SMEM_PARTITION_ASSIGN_EXACT' if partition else MARKER) and [int(v,16) for v in lines[1:]]==expected
        else:
            regs=(decode_stop(run.stdout) or {}).get('registers',{})
            accepted=1 if name=='repeated-stale-owner' else 0
            ledger_words=[OWNERS,4] if accepted else [8,0]
            partition_accepted=1 if name=='partition-stale' else 0
            ledger_match=re.search(r'MODEL_SMEM_TOC_LEDGER_OWNERS_PERMISSIONS:\n([0-9a-f]+)\n([0-9a-f]+)',text)
            passed=(regs.get('x0')==hex(fid) and regs.get('x1')==hex(arginfo)
                    and regs.get('x2')==hex(initial[2]) and regs.get('x3')==hex(initial[3])
                    and text.count(MARKER)==accepted
                    and (name=='disabled' or (ledger_match and [int(v,16) for v in ledger_match.groups()]==ledger_words)))
            if partition_ledger:
                match=re.search(r'MODEL_SMEM_PARTITION_LEDGER_READERS_WRITERS:\n((?:[0-9a-f]{16}\n){20})',text)
                passed=passed and text.count('MODEL_SMEM_PARTITION_ASSIGN_EXACT')==partition_accepted and bool(match) and [int(v,16) for v in match.group(1).splitlines()]==partition_state
        results.append({'case':name,'passed':bool(passed and run.returncode==0),'stdout':text,'stderr':run.stderr.decode(errors='replace')})
    # Original firmware, both clock initial states. No instruction/data patches.
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
        cmd=base[:];dest=out/('qhee-'+clocks)
        cmd[cmd.index('--out')+1]=str(dest);cmd[cmd.index('--gcc-mmu-clocks')+1]=clocks
        subprocess.run(cmd+['--smem-toc-assign'],stdout=subprocess.DEVNULL,check=True)
        report=json.loads((dest/'manifest.json').read_text());stop=report['stop'] or {}
        passed=(report['smem_toc_assign_model']['accepted_transitions']==1
                and stop.get('registers',{}).get('x0')==hex(FID) and not stop.get('qhee_fault')
                and 'NIO_MMU_DENIED' not in report['stderr'] and 'NIO_SMEM_DENIED' not in report['stderr'])
        inspection=dest/'inspection'
        subprocess.run([sys.executable,str(Path(__file__).with_name('inspect_assign_mem.py')),
                        '--manifest',str(dest/'manifest.json'),'--skip','1','--out',str(inspection)],stdout=subprocess.DEVNULL,check=True)
        buffers=json.loads((inspection/'buffers.json').read_text())
        passed=(passed and buffers['region']==[0x80acf000,0x30000] and buffers['source_vmids']==[3]
                and buffers['destinations']==[{'vmid':vmid,'permission':6,'context':0,'context_size':0,'reserved':0} for vmid in (3,6)])
        results.append({'case':'qhee-'+clocks,'passed':passed,'manifest':str(dest/'manifest.json'),'inspection':str(inspection/'buffers.json')})
    for clocks in ('off','on'):
        cmd=base[:];dest=out/('qhee-partitions-'+clocks)
        cmd[cmd.index('--out')+1]=str(dest);cmd[cmd.index('--gcc-mmu-clocks')+1]=clocks
        subprocess.run(cmd+['--smem-toc-assign','--smem-partition-assign'],stdout=subprocess.DEVNULL,check=True)
        report=json.loads((dest/'manifest.json').read_text());stop=report['stop'] or {}
        inspection=dest/'inspection'
        subprocess.run([sys.executable,str(Path(__file__).with_name('inspect_assign_mem.py')),
                        '--manifest',str(dest/'manifest.json'),'--skip','11','--out',str(inspection)],stdout=subprocess.DEVNULL,check=True)
        buffers=json.loads((inspection/'buffers.json').read_text())
        ledger=buffers['ledgers']['smem_partition_ledger']['words']
        complete=all(ledger[i+2:i+4]==ledger[i+6:i+8] for i in range(0,80,8))
        passed=(report['smem_toc_assign_model']['accepted_transitions']==1
                and report['smem_partition_assign_model']['accepted_transitions']==10
                and stop.get('registers',{}).get('x0')==hex(FID) and not stop.get('qhee_fault')
                and 'NIO_MMU_DENIED' not in report['stderr'] and 'NIO_SMEM_DENIED' not in report['stderr']
                and buffers['region']==[0x80dc1000,0x1000] and buffers['source_vmids']==[3]
                and buffers['destinations']==[{'vmid':v,'permission':6,'context':0,'context_size':0,'reserved':0} for v in (21,22)]
                and complete and buffers['ledgers']['smem_toc_ledger']['words']==[OWNERS,4]
                and [w['entries'][-1]['value'] for w in buffers['walks']]==
                    ['0x50000080900703','0x50000080901703','0x40000080aff783'])
        results.append({'case':'qhee-partitions-'+clocks,'passed':passed,'manifest':str(dest/'manifest.json'),
                        'inspection':str(inspection/'buffers.json')})
        if clocks=='off':
            # Independently inspect every original firmware request, not just markers.
            for index in range(11):
                inspection=dest/('request-'+str(index))
                subprocess.run([sys.executable,str(Path(__file__).with_name('inspect_assign_mem.py')),
                    '--manifest',str(dest/'manifest.json'),'--skip',str(index),'--out',str(inspection)],stdout=subprocess.DEVNULL,check=True)
                observed=json.loads((inspection/'buffers.json').read_text())
                region=[0x80aff000,0x1000] if index==0 else [int(contracts[index-1][k],0) for k in ('start','size')]
                expected=[{'vmid':v,'permission':4} for v in (3,6,5,30,27,4,40,26)] if index==0 else contracts[index-1]['destinations']
                expected=[d|{'context':0,'context_size':0,'reserved':0} for d in expected]
                passed=(observed['region']==region and observed['source_vmids']==[3] and observed['destinations']==expected)
                results.append({'case':'original-request-'+str(index),'passed':passed,'inspection':str(inspection/'buffers.json')})
    for name,args in [('partition-without-toc',['--smem-partition-assign']),
                      ('partition-with-wrong-capture',['--smem-partition-assign','--smem-toc-assign','--smem-sample',str(ROOT/'reports/nio-cmd-db-pointer-20261005/manifest.json')])]:
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('run_qemu.py'))]+args,capture_output=True,text=True)
        results.append({'case':name,'passed':result.returncode==2 and 'error:' in result.stderr,'stderr':result.stderr})
    report={'results':results,'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
            'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (sources/'start.S',sources/'smem_assign.S',sources/'smem_partitions.S',Path(__file__))},
            'scope':'Exact offline ownership ledger; no TrustZone enforcement or physical KVM claim'}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):raise SystemExit('SMEM assignment regression failed')


if __name__=='__main__':main()
