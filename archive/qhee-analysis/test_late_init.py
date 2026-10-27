#!/usr/bin/env python3
"""Bounded PMIC/PIL/late-PRNG contracts and final IMEM publication guards."""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from qhee import ROOT, QheeImage
from pmic_regions import inventory
from run_qemu import compile_elf, decode_stop, environment
from test_replay import caller_source

SOURCES = Path(__file__).resolve().parent/'emulator'
OUT = ROOT/'kernel-work/out/qhee-late-init-tests'
SEED = 0x736d656d


def symbols(elf):
    return {n:int(a,16) for a,n in re.findall(r'^([0-9a-f]+) . (\w+)$',subprocess.check_output(
        ['aarch64-linux-gnu-nm',str(elf)],text=True),re.M)}


def machine(qemu, elf, caller=None):
    cmd=[str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3','-cpu','cortex-a76',
        '-m','2G','-smp','1','-accel','tcg','-display','none','-serial','stdio','-monitor','none',
        '-nic','none','-semihosting-config','enable=on,target=native','-no-reboot',
        '-device',f'loader,file={elf},cpu-num=0']
    if caller: cmd+=['-device',f'loader,file={caller}']
    return cmd


def service(qemu, env, kind):
    dest=OUT/kind;dest.mkdir(parents=True,exist_ok=True)
    requests,_=inventory(QheeImage(),*[ROOT/p for p in (
        'reports/nio-pmic-arbiter-20261005/manifest.json','reports/nio-pmic-owners-20261005/manifest.json',
        'reports/nio-pmic-secondary-map-20261005/manifest.json')])
    cases=['valid','repeat','disabled','wrong-fid','wrong-arginfo','wrong-el','wrong-immediate','wrong-callsite']
    if kind=='pmic': cases+=['bad-extra-pointer','wrong-start','wrong-end','wrong-vmid','wrong-permissions','wrong-operation',
        'reserved-x6','reserved-x7','out-of-order','ledger-already-mapped','last-valid','exhausted','unused-trailing']
    if kind=='pil': cases += [f'reserved-x{i}' for i in range(2,8)]
    if kind=='prng': cases+=['half-low','half-high','bad-buffer','wrong-size','out-of-order','exhausted']+[f'reserved-x{i}' for i in range(4,8)]
    results=[]
    for name in cases:
        d=dest/name;d.mkdir(exist_ok=True)
        fid={'pmic':0xc2000c19,'pil':0x4200020e,'prng':0xc2000a02}[kind]
        arginfo={'pmic':5,'pil':1,'prng':0x22}[kind]
        if name=='wrong-fid':fid^=0x80000000
        if name=='wrong-arginfo':arginfo+=1
        immediate=int(name=='wrong-immediate')
        asm,initial=caller_source(fid,arginfo,1 if name=='wrong-el' else 2,immediate)
        definitions={'pmic':['-DPMIC_REGION_MAP_MODEL'],'pil':['-DPIL_EMPTY_REGIONS_MODEL'],
            'prng':[f'-DPRNG_MODEL_WORD={SEED:#x}','-DHANDOFF_PRNG_MODEL']}[kind]
        compile_elf(SOURCES/'start.S',0x40200000,d/'el3.elf',[] if name=='disabled' else definitions)
        sym=symbols(d/'el3.elf');blocks={};read=[];count=0
        if kind=='pmic':
            values={2:requests[0][0],3:requests[0][1],4:2,5:0x801cc390,6:0,7:0}
            extra=[6,1,0xa5a5a5a5a5a5a5a5,0xdeadbeef12345678]
            if name=='wrong-permissions':extra[0]=7
            if name=='wrong-operation':extra[1]=0
            if name=='bad-extra-pointer':values[5]=0xdead0000
            if name=='wrong-start':values[2]+=1
            if name=='wrong-end':values[3]-=4096
            if name=='wrong-vmid':values[4]=3
            if name=='out-of-order':values.update({2:requests[1][0],3:requests[1][1]})
            if name=='last-valid':count=240;values.update({2:requests[-1][0],3:requests[-1][1]})
            if name=='exhausted':count=241
            blocks[0x801cc390]=struct.pack('<4Q',*extra)
            if name!='disabled':
                blocks[sym['pmic_region_map_count']]=struct.pack('<Q',count)
                ledger=[6]*count+[0]*(241-count)
                if name=='ledger-already-mapped':ledger[0]=6
                blocks[sym['pmic_region_map_ledger']]=struct.pack('<241Q',*ledger)
                read += [sym['pmic_region_map_count']]+[sym['pmic_region_map_ledger']+8*i for i in range(241)]
            read += [0x801cc390+8*i for i in range(4)]
            marker='MODEL_PMIC_REGION_MAP_VMID2_RW'
        elif kind=='pil':
            values={i:0 for i in range(2,8)};marker='MODEL_PIL_EMPTY_REGION_LIST_ASSUMPTION'
            blocks[0x803e0000]=struct.pack('<Q',0xa5a5a5a5a5a5a5a5);read=[0x803e0000]
            if name!='disabled':read.append(sym['pil_empty_regions_count'])
        else:
            count={'half-low':1,'half-high':2,'exhausted':3}.get(name,0)
            address,size=[(0x80095a60,4),(0x801ccaa8,2),(0x801ccaaa,2)][min(count,2)]
            values={2:address,3:size,4:0,5:0,6:0,7:0}
            if name=='bad-buffer':values[2]=0x80095a64
            if name=='wrong-size':values[3]=8
            if name=='out-of-order':values[2]=0x801ccaa8;values[3]=2
            marker='MODEL_HANDOFF_PRNG_FIXED_WORD_NOT_ENTROPY'
            blocks[0x80095a60]=b'\xa5'*8;blocks[0x801ccaa8]=b'\xa5'*8
            read=[0x80095a60,0x801ccaa8]
            if name!='disabled':blocks[sym['handoff_prng_count']]=struct.pack('<Q',count);read.append(sym['handoff_prng_count'])
        if name.startswith('reserved-x'):values[int(name.split('x')[-1])]=1
        for i,v in values.items():
            asm=asm.replace(f'ldr x{i}, ={initial[i]:#x}',f'ldr x{i}, ={v:#x}');initial[i]=v
        # One shared original-firmware SMC return PC, even for repeat attempts.
        asm=asm.replace(f'smc #{immediate}',f'b call\nresume:\n',1)
        if name=='repeat':asm=asm.replace('sub sp, sp, #272','b caller_setup\nsub sp, sp, #272',1)
        loads=[]
        for i,a in enumerate(read,33):loads += [f'ldr x0, ={a:#x}','ldr x0, [x0]',f'str x0, [sp, #{8*i}]']
        stack=((33+len(read))*8+15)&~15
        asm=asm.replace('sub sp, sp, #272',f'sub sp, sp, #{stack}').replace('add x0, sp, #272',f'add x0, sp, #{stack}')
        asm=asm.replace('mov x20, sp','\n'.join(loads)+'\nmov x20, sp').replace('mov x21, #33',f'mov x21, #{33+len(read)}')
        asm+=f'\n.org {0x1aa4 if name=="wrong-callsite" else 0x1aa0:#x}\ncall:\nsmc #{immediate}\nb resume\n'
        init=[];data=[]
        for i,(a,b) in enumerate(blocks.items()):
            p=d/f'{a:x}.bin';p.write_bytes(b)
            init += [f'adr x11, block_{i}',f'ldr x12, ={a:#x}',f'mov x13, #{len(b)//8}',
                f'copy_{i}:','ldr x14, [x11], #8','str x14, [x12], #8',
                'subs x13, x13, #1',f'b.ne copy_{i}']
            data += ['.balign 8',f'block_{i}:',f'.incbin "{p}"']
        asm=asm.replace('_start:\n','_start:\n'+'\n'.join(init)+'\ncaller_setup:\n',1)+'\n'+'\n'.join(data)+'\n'
        (d/'caller.S').write_text(asm);compile_elf(d/'caller.S',0x80040000,d/'caller.elf')
        cmd=machine(qemu,d/'el3.elf',d/'caller.elf')
        run=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=5)
        valid=name in ('valid','last-valid','unused-trailing','half-low','half-high')
        if valid:
            expected=initial[:]
            if kind=='pil':expected[:4]=[0]*4
            else:expected[0]=0
            if kind=='pmic':expected[1]=0
            expected += [0x803f0000,0xa0000000]
            if kind=='pmic':expected += [count+1]+[6]*(count+1)+[0]*(240-count)+extra
            if kind=='pil':expected += [0xa5a5a5a5a5a5a5a5,1]
            if kind=='prng':
                mem={a:bytearray(b) for a,b in blocks.items() if a in (0x80095a60,0x801ccaa8)}
                a=values[2];base=a&~7;v=SEED>>(16 if name=='half-high' else 0)
                mem[base][a-base:a-base+values[3]]=(v&((1<<(8*values[3]))-1)).to_bytes(values[3],'little')
                expected += [int.from_bytes(mem[a],'little') for a in (0x80095a60,0x801ccaa8)]+[count+1]
            lines=run.stdout.splitlines();passed=lines==[marker]+[f'{v:016x}' for v in expected]
        else:
            regs=(decode_stop(run.stdout.encode()) or {}).get('registers',{})
            # Fault dump exposes x0..x3; successful calls verify all GPRs, SP and NZCV.
            passed=all(regs.get(f'x{i}')==hex(v) for i,v in enumerate(initial[:4]))
            passed=passed and run.stdout.count(marker)==int(name=='repeat')
            if kind in ('pmic','pil') and name!='disabled':
                label='MODEL_PMIC_REGION_MAP_ACCEPTED_COUNT' if kind=='pmic' else 'MODEL_PIL_EMPTY_REGION_LIST_COUNT'
                m=re.search(label+r':\n([0-9a-f]+)',run.stdout)
                passed=passed and bool(m) and int(m[1],16)==(1 if name=='repeat' else count)
        results.append({'case':kind+'/'+name,'passed':bool(passed and run.returncode==0),'stdout':run.stdout,'stderr':run.stderr})
    return results


def publications(qemu,env):
    results=[]
    for name in ('valid','disabled','no-prior-log','wrong-value','wrong-width','adjacent','repeat','readback'):
        d=OUT/('ready-'+name);d.mkdir(exist_ok=True)
        addr=0x146bfb28 if name=='adjacent' else 0x146bfb20
        snippet='' if name=='no-prior-log' else 'ldr x8, =0x146bfb30\n    ldr x19, =0x200080209000\n    str x19, [x8]\n    '
        snippet+=f'ldr x8, ={addr:#x}\n    ldr x19, ={0x800a5022 if name=="wrong-value" else 0x800a5021:#x}\n    str {"w19" if name=="wrong-width" else "x19"}, [x8]'
        if name=='repeat':snippet+='\n    str x19, [x8]'
        if name=='readback':snippet+='\n    ldr x19, [x8]'
        asm=(SOURCES/'register_probe.S').read_text().replace('ldr x19, =0x123456789abcdef0\n    str x19, [x8]\n    ldr x19, [x8]',snippet)
        (d/'probe.S').write_text(asm);compile_elf(d/'probe.S',0x40200000,d/'probe.elf',[f'-DADDRESS={addr:#x}','-DACCESS=11'])
        cmd=machine(qemu,d/'probe.elf')+['-device',f'nio-tz-log-pointer,publications=on,ready-publication={"off" if name=="disabled" else "on"}']
        run=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=5);lines=run.stdout.splitlines()
        passed=lines==['READ','00000000800a5021'] if name=='valid' else len(lines)==3 and lines[0]=='ABORT' and int(lines[1],16)>>26==0x25 and int(lines[1],16)&63==16 and int(lines[2],16)==addr
        passed=passed and run.stderr.count('NIO_IMEM_QHEE_READY_PUBLISH')==int(name in ('valid','repeat','readback'))
        results.append({'case':'ready/'+name,'passed':bool(passed and run.returncode==0),'stdout':run.stdout,'stderr':run.stderr})
    return results


def main():
    OUT.mkdir(parents=True,exist_ok=True);qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    results=[]
    for kind in ('pmic','pil','prng'):results+=service(qemu,env,kind)
    results+=publications(qemu,env)
    requests,_=inventory(QheeImage(),*[ROOT/p for p in ('reports/nio-pmic-arbiter-20261005/manifest.json',
        'reports/nio-pmic-owners-20261005/manifest.json','reports/nio-pmic-secondary-map-20261005/manifest.json')])
    table=[tuple(int(v,16) for v in pair) for pair in re.findall(r'\.quad (0x[0-9a-f]+), (0x[0-9a-f]+)',(SOURCES/'pmic_region_map_table.S').read_text())]
    results.append({'case':'pinned-map-inventory-matches-assembly','passed':table==[r[:2] for r in requests]})
    report={'results':results,'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
        'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__),SOURCES/'start.S',SOURCES/'pmic_region_map.S',SOURCES/'pmic_region_map_table.S',SOURCES/'pil_empty_regions.S',SOURCES/'nio-tz-log-pointer.c']},
        'scope':'Offline finite response and register/memory preservation checks. Assumes TZ acceptance and empty PIL region list; fixed PRNG is not entropy.'}
    (OUT/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):raise SystemExit('Late-init model regression failed')


if __name__=='__main__':main()
