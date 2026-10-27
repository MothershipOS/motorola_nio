#!/usr/bin/env python3
"""Exercise the exact command-database and QHEE-log SCM ownership contracts."""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from qhee import ROOT, QheeImage
from run_qemu import compile_elf, decode_stop, environment
from test_replay import caller_source

FID=0xc2000c16


def contract(label, region_base, region_size, owner, destinations, define, marker, ledger_name, ledger_marker):
    out=ROOT/'kernel-work/out/qhee-init-assign-tests'/label;out.mkdir(parents=True,exist_ok=True)
    qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    sources=Path(__file__).resolve().parent/'emulator';results=[]
    final_ledger=[sum(1<<v for v,p in destinations if p&4),sum(1<<v for v,p in destinations if p&2)]
    cases=['valid','repeat','disabled','wrong-fid','wrong-arginfo','wrong-el','wrong-immediate',
           'wrong-callsite','bad-buffer','bad-extra-buffer','adjacent-channel','unaligned-region','short-region',
           'long-region','short-destinations','long-destinations','source-owner','first-owner','second-owner',
           'no-access','executable','context','context-size','reserved','last-byte','reversed']
    for name in cases:
        dest=out/name;dest.mkdir(exist_ok=True)
        region=bytearray(struct.pack('<QQ',region_base,region_size))
        source=bytearray(struct.pack('<II',owner,0xa5a5a5a5))
        extra=bytearray(struct.pack('<4Q',4,0x8020b000,24*len(destinations),0))
        descriptors=bytearray(b''.join(struct.pack('<IIQII',v,p,0,0,0) for v,p in destinations))
        if name=='adjacent-channel':region[:]=struct.pack('<QQ',region_base+region_size,region_size)
        if name=='unaligned-region':struct.pack_into('<Q',region,0,region_base+1)
        if name=='short-region':struct.pack_into('<Q',region,8,region_size-4096)
        if name=='long-region':struct.pack_into('<Q',region,8,region_size+4096)
        if name in ('short-destinations','long-destinations'):struct.pack_into('<Q',extra,16,len(descriptors)-24 if name.startswith('short') else len(descriptors)+24)
        if name=='source-owner':struct.pack_into('<I',source,0,3 if owner==4 else 4)
        if name=='first-owner':struct.pack_into('<I',descriptors,0,31)
        if name=='second-owner':struct.pack_into('<I',descriptors,24,22)
        if name in ('no-access','executable'):struct.pack_into('<I',descriptors,4,0 if name=='no-access' else 7)
        for case,offset in [('context',8),('context-size',16),('reserved',20),('last-byte',len(descriptors)-1)]:
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
        defines=['-DSMEM_TOC_ASSIGN_MODEL']+([] if name=='disabled' else [define])
        compile_elf(sources/'start.S',0x40200000,dest/'el3.elf',defines)
        symbols=subprocess.check_output(['aarch64-linux-gnu-nm',str(dest/'el3.elf')],text=True)
        ledgers={}
        for ledger in ('smem_toc_ledger',ledger_name):
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
            expected=[0,0]+initial[2:]+[0x803f0000,0xa0000000]+expected_memory+[8,0]+final_ledger
            lines=text.splitlines();passed=len(lines)==len(expected)+1 and lines[0]==marker and [int(v,16) for v in lines[1:]]==expected
        else:
            regs=(decode_stop(run.stdout) or {}).get('registers',{})
            passed=(regs.get('x0')==hex(fid) and regs.get('x1')==hex(arginfo)
                    and regs.get('x2')==hex(initial[2]) and regs.get('x3')==hex(initial[3])
                    and text.count(marker)==(1 if name=='repeat' else 0))
            match=re.search(r'MODEL_SMEM_TOC_LEDGER_OWNERS_PERMISSIONS:\n([0-9a-f]+)\n([0-9a-f]+)',text)
            passed=passed and bool(match) and [int(v,16) for v in match.groups()]==[8,0]
            if name!='disabled':
                match=re.search(re.escape(ledger_marker)+r':\n([0-9a-f]+)\n([0-9a-f]+)',text)
                passed=passed and bool(match) and [int(v,16) for v in match.groups()]==(final_ledger if name=='repeat' else [1<<owner,0])
        results.append({'case':label+'/'+name,'passed':bool(passed and run.returncode==0),'stdout':text,'stderr':run.stderr.decode(errors='replace')})
    return results


def main():
    results=contract('cmd-db',0x80860000,0x20000,3,[(v,4) for v in (1,2,5,3,6,26,30,22)],
        '-DCMD_DB_ASSIGN_MODEL','MODEL_CMD_DB_ASSIGN_READ_ONLY','cmd_db_assign_ledger','MODEL_CMD_DB_ASSIGN_LEDGER_READERS_WRITERS')
    results+=contract('hyp-log',0x80209000,0x2000,4,[(3,4),(4,6)],
        '-DHYP_LOG_SHARE_MODEL','MODEL_HYP_LOG_SHARE','hyp_log_share_ledger','MODEL_HYP_LOG_LEDGER_READERS_WRITERS')
    im=QheeImage()
    results.append({'case':'pinned-command-db-region','passed':struct.unpack('<QQ',im.read(0x800a4e60,16))==(0x80860000,0x20000)})
    results.append({'case':'pinned-command-db-destinations','passed':im.read(0x800a4e70,192)==b''.join(struct.pack('<IIQII',v,4,0,0,0) for v in (1,2,5,3,6,26,30,22))})
    sources=Path(__file__).resolve().parent/'emulator'
    report={'results':results,'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__),sources/'start.S',sources/'smem_assign.S',sources/'cmd_db_assign.S',sources/'hyp_log_share.S']},
        'qemu_sha256':hashlib.sha256((ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64').read_bytes()).hexdigest(),
        'scope':'Offline exact ownership ledgers; assumes initial owners and TZ acceptance, no real access enforcement'}
    (ROOT/'kernel-work/out/qhee-init-assign-tests/results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results: print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results): raise SystemExit('Init-tail ownership regression failed')


if __name__=='__main__':main()
