#!/usr/bin/env python3
"""Exact SHM bridge and its allocator PRNG: replies, ledgers, preservation, denial."""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
from qhee import ROOT
from run_qemu import compile_elf, decode_stop, environment
from test_replay import caller_source
from test_late_init import machine, symbols

SOURCES=Path(__file__).resolve().parent/'emulator'
OUT=ROOT/'kernel-work/out/qhee-bridge-tests'
HANDLE=0x53484d0000000001
WORD=0xfedcba9876543210


def caller(d,asm,blocks,reads,immediate,wrong_site,repeat):
    asm=asm.replace(f'smc #{immediate}','b call\nresume:\n',1)
    if repeat:asm=asm.replace('sub sp, sp, #272','b caller_setup\nsub sp, sp, #272',1)
    loads=[]
    for i,a in enumerate(reads,33):loads += [f'ldr x0, ={a:#x}','ldr x0, [x0]',f'str x0, [sp, #{8*i}]']
    stack=((33+len(reads))*8+15)&~15
    asm=asm.replace('sub sp, sp, #272',f'sub sp, sp, #{stack}').replace('add x0, sp, #272',f'add x0, sp, #{stack}')
    asm=asm.replace('mov x20, sp','\n'.join(loads)+'\nmov x20, sp').replace('mov x21, #33',f'mov x21, #{33+len(reads)}')
    asm+=f'\n.org {0x1aa4 if wrong_site else 0x1aa0:#x}\ncall:\nsmc #{immediate}\nb resume\n'
    init=[];data=[]
    for i,(a,b) in enumerate(blocks.items()):
        p=d/f'{a:x}.bin';p.write_bytes(b)
        init += [f'adr x11, block_{i}',f'ldr x12, ={a:#x}',f'mov x13, #{len(b)//8}',f'copy_{i}:',
            'ldr x14, [x11], #8','str x14, [x12], #8','subs x13, x13, #1',f'b.ne copy_{i}']
        data += ['.balign 8',f'block_{i}:',f'.incbin "{p}"']
    asm=asm.replace('_start:\n','_start:\n'+'\n'.join(init)+'\ncaller_setup:\n',1)+'\n'+'\n'.join(data)+'\n'
    (d/'caller.S').write_text(asm);compile_elf(d/'caller.S',0x80040000,d/'caller.elf')


def contracts(qemu,env,kind):
    common=['valid','repeat','disabled','wrong-fid','wrong-arginfo','wrong-el','wrong-immediate','wrong-callsite']
    cases=common+(['full-width-handle','bad-base','bad-intermediate','short-size','long-size','bad-ns-permission',
        'bad-secure-permission','bad-extra-permission','bad-vmid-count','bad-vmids','reserved-x6','reserved-x7',
        'preexisting-ledger','delete-is-unmodeled'] if kind=='bridge' else
        ['zero-word','no-prior-bridge','already-consumed','bad-buffer','unaligned-buffer','short-size','long-size',
         'reserved-x4','reserved-x5','reserved-x6','reserved-x7'])
    results=[]
    for name in cases:
        d=OUT/kind/name;d.mkdir(parents=True,exist_ok=True)
        handle=0xfedcba9876543210 if name=='full-width-handle' else HANDLE
        word=0 if name=='zero-word' else WORD
        defs=[f'-DSHM_BRIDGE_MODEL_HANDLE={handle:#x}']
        if kind=='prng':defs += ['-DPRNG_MODEL_WORD=0x736d656d']+([] if name=='disabled' else [f'-DBRIDGE_PRNG_MODEL_WORD={word:#x}'])
        elif name=='disabled':defs=[]
        compile_elf(SOURCES/'start.S',0x40200000,d/'el3.elf',defs);sym=symbols(d/'el3.elf')
        fid=0xc2000c1e if kind=='bridge' else 0xc2000a02;arginfo=4 if kind=='bridge' else 0x22
        if name=='wrong-fid':fid^=0x80000000
        if name=='delete-is-unmodeled':fid=0xc2000c1d
        if name=='wrong-arginfo':arginfo+=1
        immediate=int(name=='wrong-immediate');asm,initial=caller_source(fid,arginfo,1 if name=='wrong-el' else 2,immediate)
        blocks={0x800ab000:b'\xa5'*16,0x800ab088:b'\xa5'*24}
        ledger=[int(kind=='prng' or name=='preexisting-ledger'),0,0,0,0,0]
        count=int(name=='already-consumed')
        if kind=='bridge':
            values={2:0x800ab000,3:0x800ab004,4:0x1001a,5:0,6:0,7:0}
            changes={'bad-base':(2,0x800ac000),'bad-intermediate':(3,0x800ac004),
                'short-size':(4,0xf01a),'long-size':(4,0x1101a),'bad-ns-permission':(2,0x800ab006),
                'bad-secure-permission':(3,0x800ab006),'bad-extra-permission':(4,0x1001e),
                'bad-vmid-count':(4,0x1021a),'bad-vmids':(5,3)}
            marker='MODEL_SHM_BRIDGE_CREATE_ASSUMED_SUCCESS'
        else:
            values={2:0x800ab090,3:8,4:0,5:0,6:0,7:0}
            changes={'bad-buffer':(2,0x800ab098),'unaligned-buffer':(2,0x800ab091),
                'short-size':(3,4),'long-size':(3,16)}
            if name=='no-prior-bridge':ledger[0]=0
            marker='MODEL_BRIDGE_PRNG_FIXED_WORD_NOT_ENTROPY'
        if name in changes:i,v=changes[name];values[i]=v
        if name.startswith('reserved-x'):values[int(name.split('x')[-1])]=1
        for i,v in values.items():asm=asm.replace(f'ldr x{i}, ={initial[i]:#x}',f'ldr x{i}, ={v:#x}');initial[i]=v
        reads=[0x800ab000,0x800ab008,0x800ab088,0x800ab090,0x800ab098]
        if 'shm_bridge_ledger' in sym:
            blocks[sym['shm_bridge_ledger']]=struct.pack('<6Q',*ledger)
            reads += [sym['shm_bridge_ledger']+8*i for i in range(6)]
        if 'bridge_prng_count' in sym:
            blocks[sym['bridge_prng_count']]=struct.pack('<Q',count);reads.append(sym['bridge_prng_count'])
        caller(d,asm,blocks,reads,immediate,name=='wrong-callsite',name=='repeat')
        run=subprocess.run(machine(qemu,d/'el3.elf',d/'caller.elf'),capture_output=True,text=True,env=env,timeout=5)
        valid=name in ('valid','full-width-handle','zero-word')
        if valid:
            expected=initial[:];expected[0]=0
            if kind=='bridge':expected[1]=0;expected[2]=handle
            expected += [0x803f0000,0xa0000000]+[0xa5a5a5a5a5a5a5a5]*5
            if kind=='bridge':expected += [1,0x800ab000,0x800ab004,0x1001a,0,handle]
            else:expected[33+3]=word;expected += ledger+[1]
            passed=run.stdout.splitlines()==[marker]+[f'{v:016x}' for v in expected]
        else:
            regs=(decode_stop(run.stdout.encode()) or {}).get('registers',{})
            passed=all(regs.get(f'x{i}')==hex(v) for i,v in enumerate(initial[:4])) and run.stdout.count(marker)==int(name=='repeat')
            if 'shm_bridge_ledger' in sym:
                match=re.search(r'MODEL_SHM_BRIDGE_LEDGER_CREATED_INPUTS_HANDLE:\n((?:[0-9a-f]{16}\n){6})',run.stdout)
                expected=([1,0x800ab000,0x800ab004,0x1001a,0,handle] if kind=='bridge' and name=='repeat' else ledger)
                passed=passed and bool(match) and [int(v,16) for v in match[1].splitlines()]==expected
        results.append({'case':kind+'/'+name,'passed':bool(passed and run.returncode==0),'stdout':run.stdout,'stderr':run.stderr})
    return results


def main():
    OUT.mkdir(parents=True,exist_ok=True);qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    results=contracts(qemu,env,'bridge')+contracts(qemu,env,'prng')
    report={'results':results,'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
        'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__),SOURCES/'start.S',SOURCES/'shm_bridge.S',SOURCES/'bridge_prng.S']},
        'scope':'Exact offline bridge acceptance/handle and bounded PRNG experiments. No TZ acceptance or access enforcement; deterministic PRNG is not entropy.'}
    (OUT/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):raise SystemExit('SHM bridge model regression failed')


if __name__=='__main__':main()
