#!/usr/bin/env python3
"""Original SEC virtual counter, fixed-frequency conversion and next MMIO boundary."""
import argparse,hashlib,json,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_WRITE
from unicorn.arm64_const import UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC,UC_ARM64_REG_X0
from qhee import ROOT
from xbl_target import payload

STOP=0x9fc2a150
FREQUENCY=19200000
POINTS={0x9fc2bb4c:'sec-counter-read-complete',0x9fc0d248:'sec-before-counter-conversion',
 0x9fc19b78:'sec-counter-conversion-entry',0x9fc19be4:'sec-frequency-helper',
 0x9fc19bf0:'sec-fixed-frequency-return',0x9fc19b90:'sec-frequency-observed',
 0x9fc0d24c:'sec-counter-converted',0x9fc0d254:'sec-counter-result-stored',
 0x9fc0d280:'sec-before-platform-init',0x9fc0e45c:'sec-platform-init-entry',
 0x9fc17604:'sec-platform-init-once',0x9fc22828:'sec-next-init-entry',0x9fc22850:'sec-before-simd-load',0x9fc22854:'sec-simd-load-complete',
 0x9fc22018:'sec-init-descriptor-entry',0x9fc22084:'sec-init-descriptor-copied',
 0x9fc22bf8:'sec-platform-selection-entry',0x9fc2a140:'sec-platform-selector',STOP:'sec-before-platform-selection-read'}


def convert(ticks,frequency=FREQUENCY):
    if type(ticks) is not int or not 0<=ticks<1<<64 or type(frequency) is not int or not 0<frequency<1<<32:raise ValueError('Counter needs uint64 ticks and nonzero uint32 frequency')
    q,r=divmod(ticks,frequency)
    return (q*1000000000+r*1000000000//frequency)&((1<<64)-1)


def contract():
    b,m=payload();md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);windows={}
    for name,a,n in (('counter-accessors',0x9fc2bb40,16),('counter-conversion',0x9fc19b78,0x80),
      ('integer-arithmetic',0x9fc19a60,0x38),('division-dispatch',0x9fc1861c,0x64),('multiply-branch',0x9fc27f94,4),
      ('counter-storage-init',0x9fc0d244,0x40),('platform-init',0x9fc0e45c,0x8c),
      ('init-once',0x9fc17604,0x58),('next-init-prefix',0x9fc22828,0x40),('descriptor-init',0x9fc22018,0x78),
      ('selection-wrapper',0x9fc22bf8,0x30),('platform-selector',0x9fc2a140,0x2c)):
        data=b[a-0x9fc00000:a-0x9fc00000+n];ins=[{'address':hex(i.address),'mnemonic':i.mnemonic,'operands':i.op_str} for i in md.disasm(data,a)]
        if len(ins)*4!=n:raise ValueError('Incomplete counter window')
        windows[name]={'address':hex(a),'size':n,'sha256':hashlib.sha256(data).hexdigest(),'instructions':ins}
    instructions={i['address']:(i['mnemonic'],i['operands']) for w in windows.values() for i in w['instructions']}
    expected={0x9fc2bb48:('mrs','x0, cntvct_el0'),0x9fc19be8:('ldr','w0, [x8, #0x2e4]'),
      0x9fc22850:('ldr','q0, [x8, #0x5f0]'),STOP:('ldr','w8, [x8]')}
    if any(instructions[hex(a)]!=v for a,v in expected.items()):raise ValueError('Unexpected original counter/frequency/MMIO access')
    frequency=struct.unpack_from('<I',b,0x2f2e4)[0]
    if frequency!=FREQUENCY:raise ValueError('Unexpected fixed counter frequency')
    return {'firmware_sha256':m['firmware_sha256'],'fv_sha256':m['segment_sha256'],'windows':windows,
      'frequency':frequency,'frequency_address':'0x9fc2f2e4','descriptor_copy':{'address':'0x9fc3d728','size':40,'expected_hex':b[0x325f0:0x32600].hex()+'00'*24},'counter':'CNTVCT_EL0','result_address':'0x9fc3b3c0',
      'formula':'(ticks // frequency * 1000000000 + ticks % frequency * 1000000000 // frequency) modulo 2^64',
      'stop_before':hex(STOP),'next_access':{'instruction':'ldr w8, [x8]','address':'0x1fc8004','size':4,'kind':'platform selection MMIO read; bits 1:0 choose descriptor'},
      'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'scope':'Original CNTVCT execution and integer conversion using firmware fixed 19.2 MHz, result store and next init prologues. QEMU counter values are model time, not phone time; timer frequency mismatch must be reported. Executes original SIMD load and descriptor RAM copy; stops before platform-selection MMIO read; no new timer/MMIO reply, complete SEC/UEFI/ABL/Linux entry or physical KVM.'}


def slice_convert(ticks):
    convert(ticks);b,m=payload();u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0x9fc00000,len(b));u.mem_write(0x9fc00000,b)
    u.mem_map(0x90000000,0x10000);u.reg_write(UC_ARM64_REG_SP,0x9000f000);u.reg_write(UC_ARM64_REG_LR,0x90008000);u.reg_write(UC_ARM64_REG_X0,ticks);writes=[]
    def write(u,access,a,n,v,_):
        if not 0x9000e000<=a or a+n>0x9000f000:raise ValueError('Unexpected conversion write')
        writes.append({'address':hex(a),'size':n,'value':hex(v)})
    u.hook_add(UC_HOOK_MEM_WRITE,write);u.emu_start(0x9fc19b78,0x90008000,count=200)
    result=u.reg_read(UC_ARM64_REG_X0)
    if u.reg_read(UC_ARM64_REG_PC)!=0x90008000 or u.reg_read(UC_ARM64_REG_SP)!=0x9000f000 or result!=convert(ticks):raise ValueError('Original counter conversion mismatch')
    return {'ticks':hex(ticks),'result':hex(result),'sp':hex(u.reg_read(UC_ARM64_REG_SP)),'writes':writes}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'reports/qhee-offline/counter-static');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    r={'contract':contract(),'conversion_slices':[slice_convert(v) for v in (0,1,FREQUENCY-1,FREQUENCY,FREQUENCY+1,0xffffffff,1<<32,(1<<64)-1)]}
    for name,w in r['contract']['windows'].items():(a.out/(name+'.txt')).write_text(''.join(f"{i['address']}: {i['mnemonic']} {i['operands']}\n" for i in w['instructions']))
    (a.out/'manifest.json').write_text(json.dumps(r,indent=2)+'\n');print('Original counter conversion; next MMIO',hex(STOP))

if __name__=='__main__':main()
