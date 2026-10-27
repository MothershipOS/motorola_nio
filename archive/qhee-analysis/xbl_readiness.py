#!/usr/bin/env python3
"""Measured postboot SEC hold-flag replay and original path to CNTVCT access."""
import argparse,hashlib,json,re,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn.arm64_const import UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC,UC_ARM64_REG_X9
from qhee import ROOT
from xbl_target import payload

STOP=0x9fc2bb48
POINTS={0x9fc0e380:'sec-flag-loaded',0x9fc0e388:'sec-flag-before-branch',0x9fc0e390:'sec-flag-loop-complete',
 0x9fc0e320:'sec-flag-helper-return',0x9fc1667c:'sec-optional-init-noop',
 0x9fc0d1e4:'sec-platform-main-entry',0x9fc0d244:'sec-platform-before-counter-call',
 0x9fc19b5c:'sec-counter-wrapper',0x9fc27fdc:'sec-counter-platform-branch',STOP:'sec-before-cntvct-read'}
SAMPLE=ROOT/'reports/nio-sec-flag-20261006/manifest.json'


def sample(path):
    data=path.read_bytes();r=json.loads(data)
    try:
        values=[]
        for name in ('sec_flag','sec_flag_repeat'):
            c=r['checks'][name]
            if c['command']!='devmem 0x146bf944 32' or c['status']!=0:raise ValueError('SEC flag needs successful exact uint32 reads')
            lines=[s.strip() for s in c['stdout'].splitlines() if s.strip() and s.strip()!='~ #']
            if len(lines)!=1 or not re.fullmatch(r'0x[0-9a-fA-F]{8}',lines[0]):raise ValueError('SEC flag needs exactly one uint32 per read')
            values.append(int(lines[0],16))
        if values[0]!=values[1]:raise ValueError('SEC flag repeated captures differ')
        if r['checks']['uname']['status']!=0 or '6.18.54-mothership-nio-dev' not in r['checks']['uname']['stdout']:raise ValueError('SEC flag needs diagnostic kernel context')
        if r['checks']['entry_level']['status']!=0 or 'started at EL1' not in r['checks']['entry_level']['stdout']:raise ValueError('SEC flag needs captured EL1 context')
    except (KeyError,TypeError,AttributeError) as e:raise ValueError('Incomplete SEC flag capture') from e
    return values[0],{'path':str(path.resolve()),'sha256':hashlib.sha256(data).hexdigest(),'address':'0x146bf944','width':4,'value':hex(values[0]),'capture_time':r.get('timestamp'),
      'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'read_limit':1,
      'assumptions':['EL1-visible postboot value reused at modeled SEC entry and diagnostic EL2; cold-entry equality and publisher unverified.'],
      'scope':'One exact measured flag read only, requiring prior exact QHEE IMEM publications. No flag write/release model, general IMEM storage, real cold state or physical acceptance.'}


def contract():
    b,m=payload();md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);windows={}
    for name,a,n in (('hold-poll',0x9fc0e33c,0x5c),('sec-main',0x9fc0e308,0x34),('optional-init-noop',0x9fc1667c,4),
      ('platform-prologue',0x9fc0d1e4,0x64),('counter-wrapper',0x9fc19b5c,4),('counter-platform-branch',0x9fc27fdc,4),('virtual-counter',STOP,8)):
        data=b[a-0x9fc00000:a-0x9fc00000+n];ins=[{'address':hex(i.address),'mnemonic':i.mnemonic,'operands':i.op_str} for i in md.disasm(data,a)]
        if len(ins)*4!=n:raise ValueError('Incomplete readiness/counter window')
        windows[name]={'address':hex(a),'size':n,'sha256':hashlib.sha256(data).hexdigest(),'instructions':ins}
    if (windows['virtual-counter']['instructions'][0]['mnemonic'],windows['virtual-counter']['instructions'][0]['operands'])!=('mrs','x0, cntvct_el0'):
        raise ValueError('Unexpected original virtual counter access')
    return {'firmware_sha256':m['firmware_sha256'],'fv_sha256':m['segment_sha256'],'windows':windows,'flag_address':'0x146bf944','wait_while_value':'0x55444247',
      'stop_before':hex(STOP),'counter':'CNTVCT_EL0','optional_init':'single original ret',
      'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'publisher_status':'Unverified: bounded SEC consumer does not write this flag. A literal search is not proof of absence of an earlier or external publisher.',
      'scope':'Original hold-flag comparison/exit, no-op hook and SEC platform prologue through virtual-counter MRS boundary. Paused before CNTVCT; no counter result/model, complete SEC/UEFI/ABL/Linux entry or physical KVM.'}


def poll(values):
    if not values or len(values)>8 or any(not isinstance(v,int) or not 0<=v<=0xffffffff for v in values):raise ValueError('Poll fixture requires one to eight uint32 values')
    b,m=payload();u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0x9fc00000,len(b));u.mem_write(0x9fc00000,b)
    u.mem_map(0x146bf000,0x1000);u.mem_map(0x90000000,0x10000)
    u.reg_write(UC_ARM64_REG_SP,0x9000f000);u.reg_write(UC_ARM64_REG_LR,0x90008000);reads=[];writes=[];pcs=[];exhausted=False
    def code(u,a,n,_):
        nonlocal exhausted
        pcs.append(hex(a))
        if a==0x9fc0e37c and len(reads)==len(values):exhausted=True;u.emu_stop()
    def read(u,access,a,n,v,_):
        if a==0x146bf944:
            if n!=4 or len(reads)>=len(values):raise ValueError('Unexpected hold-flag read')
            val=values[len(reads)];u.mem_write(a,struct.pack('<I',val));reads.append({'address':hex(a),'size':n,'value':hex(val)})
    def write(u,access,a,n,v,_):
        if a<0x9000e000 or a+n>0x90010000:raise ValueError('Unexpected poll write')
        writes.append({'address':hex(a),'size':n,'value':hex(v)})
    u.hook_add(UC_HOOK_CODE,code);u.hook_add(UC_HOOK_MEM_READ,read);u.hook_add(UC_HOOK_MEM_WRITE,write)
    u.emu_start(0x9fc0e33c,0x90008000,count=1000)
    pc=u.reg_read(UC_ARM64_REG_PC)
    if pc not in (0x90008000,0x9fc0e37c):raise ValueError('Poll instruction bound exhausted')
    return {'input':[hex(v) for v in values],'reads':reads,'writes':writes,'pcs':pcs,'stop':hex(pc),'sp':hex(u.reg_read(UC_ARM64_REG_SP)),
      'x9':hex(u.reg_read(UC_ARM64_REG_X9)),'exhausted':exhausted,'scope':'Original poll slice with finite synthetic flag observations; held value cannot manufacture release. No publisher or physical cold-entry proof.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'reports/qhee-offline/readiness-static');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    v,meta=sample(SAMPLE);r={'contract':contract(),'sample':meta,'poll_nonheld':poll([v]),'poll_held':poll([0x55444247]),'poll_release_fixture':poll([0x55444247,0x55444247,v])}
    for name,w in r['contract']['windows'].items():(a.out/(name+'.txt')).write_text(''.join(f"{i['address']}: {i['mnemonic']} {i['operands']}\n" for i in w['instructions']))
    (a.out/'manifest.json').write_text(json.dumps(r,indent=2)+'\n');print('Measured flag',hex(v),'next counter',r['contract']['stop_before'])

if __name__=='__main__':main()
