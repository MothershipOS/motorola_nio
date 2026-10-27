#!/usr/bin/env python3
"""Exact measured SEC platform selector and original descriptor-to-MMIO dataflow."""
import argparse,hashlib,json,re,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn.arm64_const import UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC,UC_ARM64_REG_X0
from qhee import ROOT
from xbl_target import payload

SAMPLE=ROOT/'reports/nio-platform-selector-20261006/manifest.json'
STOP=0x9fc220fc
POINTS={0x9fc2a154:'sec-selector-read-complete',0x9fc2a164:'sec-selector-before-choice',
 0x9fc2a168:'sec-selector-chosen',0x9fc22c10:'sec-selector-wrapper-return',
 0x9fc22c1c:'sec-selected-descriptor-stored',0x9fc2208c:'sec-selection-init-return',
 0x9fc220ac:'sec-descriptor-continuation',0x9fc220dc:'sec-descriptor-table-match',
 0x9fc22bf0:'sec-descriptor-noop-hook',0x9fc220e8:'sec-descriptor-hook-return',STOP:'sec-before-selected-mmio-read'}


def sample(path):
    data=path.read_bytes();r=json.loads(data)
    try:
        values=[]
        for name in ('selector','selector_repeat'):
            c=r['checks'][name]
            if c['command']!='devmem 0x01fc8004 32' or c['status']!=0:raise ValueError('Selector needs successful exact uint32 reads')
            lines=[s.strip() for s in c['stdout'].splitlines() if s.strip() and s.strip()!='~ #']
            if len(lines)!=1 or not re.fullmatch(r'0x[0-9a-fA-F]{8}',lines[0]):raise ValueError('Selector needs one uint32 per read')
            values.append(int(lines[0],16))
        if values[0]!=values[1]:raise ValueError('Selector repeated captures differ')
        if r['checks']['uname']['status']!=0 or '6.18.54-mothership-nio-dev' not in r['checks']['uname']['stdout']:raise ValueError('Selector needs diagnostic kernel context')
        if r['checks']['entry_level']['status']!=0 or 'started at EL1' not in r['checks']['entry_level']['stdout']:raise ValueError('Selector needs captured EL1 context')
    except (KeyError,TypeError,AttributeError) as e:raise ValueError('Incomplete selector capture') from e
    return values[0],{'path':str(path.resolve()),'sha256':hashlib.sha256(data).hexdigest(),'address':'0x1fc8004','width':4,'value':hex(values[0]),'capture_time':r.get('timestamp'),
      'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'read_limit':1,'prerequisite':'At least one exact original hardware-version register read at 0x01fc8000.',
      'assumptions':['EL1-visible postboot selector reused at modeled SEC entry and diagnostic EL2; cold-entry equality unverified.'],
      'scope':'One exact measured selector uint32 read only, separately default-disabled; no register writes, neighboring bank, physical cold state or firmware acceptance.'}


def contract(value=0):
    if type(value) is not int or not 0<=value<=0xffffffff:raise ValueError('Selector needs uint32')
    b,m=payload();md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);windows={}
    for name,a,n in (('selector',0x9fc2a140,0x2c),('selection-wrapper',0x9fc22bf8,0x30),('descriptor-continuation',0x9fc2208c,0x74),('descriptor-noop-hook',0x9fc22bf0,8)):
        data=b[a-0x9fc00000:a-0x9fc00000+n];ins=[{'address':hex(i.address),'mnemonic':i.mnemonic,'operands':i.op_str} for i in md.disasm(data,a)]
        if len(ins)*4!=n:raise ValueError('Incomplete selector window')
        windows[name]={'address':hex(a),'size':n,'sha256':hashlib.sha256(data).hexdigest(),'instructions':ins}
    instructions={i['address']:(i['mnemonic'],i['operands']) for w in windows.values() for i in w['instructions']}
    if any(instructions[hex(a)]!=v for a,v in {0x9fc2a150:('ldr','w8, [x8]'),0x9fc2a164:('csel','x0, x10, x9, eq'),STOP:('ldr','w11, [x8]')}.items()):raise ValueError('Unexpected original selector/MMIO instruction')
    a=0x9fc35728 if value&3==1 else 0x9fc356e0;data=b[a-0x9fc00000:a-0x9fc00000+0x48];bases=struct.unpack_from('<II',data)
    copied_id=struct.unpack_from('<I',b,0x325f0)[0];table=[]
    for off in range(0x32600,0x32700,12):
        key,arg,config=struct.unpack_from('<III',b,off);table.append({'address':hex(0x9fc00000+off),'key':hex(key),'argument':hex(arg),'config':hex(config)})
        if key==copied_id:break
        if key==0:raise ValueError('Original copied descriptor has no table match')
    else:raise ValueError('Descriptor table bound exhausted')
    return {'firmware_sha256':m['firmware_sha256'],'fv_sha256':m['segment_sha256'],'windows':windows,'value':hex(value),'low_bits':value&3,
      'selected_descriptor':hex(a),'descriptor_hex':data.hex(),'descriptor_sha256':hashlib.sha256(data).hexdigest(),'mmio_bases':[hex(v) for v in bases],
      'stored_pointer_address':'0x9fc3d720','copied_descriptor_id':hex(copied_id),'table_scan':table,'matched_argument':table[-1]['argument'],'matched_config':table[-1]['config'],
      'stop_before':hex(STOP),'next_access':{'instruction':'ldr w11, [x8]','address':hex(bases[1]+4),'size':4,'kind':'selected descriptor second MMIO base + 4 read; register semantics unverified'},
      'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'scope':'Original measured selector read, low-bit descriptor selection, pointer store, original table match and no-op hook; stops before selected MMIO uint32 read. Entry/EL2 equality remains an assumption. No new MMIO bank, timer fix, complete SEC/UEFI/ABL/Linux boot or physical KVM.'}


def select(value):
    con=contract(value);b,m=payload();u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0x9fc00000,len(b));u.mem_write(0x9fc00000,b);u.mem_map(0x1fc8000,0x1000);u.mem_write(0x1fc8004,struct.pack('<I',value))
    u.reg_write(UC_ARM64_REG_LR,0x9fc00000);u.reg_write(UC_ARM64_REG_SP,0x9000f000);reads=[]
    def read(u,access,a,n,v,_):
        if a!=0x1fc8004 or n!=4 or reads:raise ValueError('Unexpected selector slice read')
        reads.append({'address':hex(a),'size':n,'value':hex(value)})
    def write(*args):raise ValueError('Original selector leaf must not write memory')
    u.hook_add(UC_HOOK_MEM_READ,read);u.hook_add(UC_HOOK_MEM_WRITE,write);u.emu_start(0x9fc2a140,0x9fc00000,count=16)
    if u.reg_read(UC_ARM64_REG_PC)!=0x9fc00000 or hex(u.reg_read(UC_ARM64_REG_X0))!=con['selected_descriptor'] or len(reads)!=1:raise ValueError('Original selector slice mismatch')
    return {'input':hex(value),'selected_descriptor':con['selected_descriptor'],'reads':reads,'sp':hex(u.reg_read(UC_ARM64_REG_SP))}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'reports/qhee-offline/selector-static');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);value,meta=sample(SAMPLE)
    r={'contract':contract(value),'sample':meta,'selection_slices':[select(v) for v in (0,1,2,3,4,5,0xfffffffd,0xffffffff)]}
    for name,w in r['contract']['windows'].items():(a.out/(name+'.txt')).write_text(''.join(f"{i['address']}: {i['mnemonic']} {i['operands']}\n" for i in w['instructions']))
    (a.out/'manifest.json').write_text(json.dumps(r,indent=2)+'\n');print('Selector',hex(value),'next read',r['contract']['next_access']['address'])

if __name__=='__main__':main()
