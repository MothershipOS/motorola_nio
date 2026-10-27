#!/usr/bin/env python3
"""Pinned SEC cache startup through its second buffer request; no new reply."""
import argparse,hashlib,json,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
from xbl_target import payload
from qhee import ROOT

STOP=0x9fc28468
POINTS={0x9fc17b90:'sec-cache-startup-entry',0x9fc18200:'sec-setway-loop-entry',
 0x9fc0cf3c:'sec-cache-invalidate-return',0x9fc0cf40:'sec-icache-enabled',
 0x9fc0cf44:'sec-dcache-enabled',0x9fc0cd44:'sec-canary-init-entry',
 0x9fc1aa88:'sec-canary-source-entry'}
WINDOWS=(('cache-startup',0x9fc17b90,0x1c),('cache-dispatch',0x9fc17b4c,0x44),
 ('irq-state',0x9fc17bd0,0x10),('irq-mask',0x9fc17d64,0x18),
 ('setway-loop',0x9fc18200,0xa8),('setway-op',0x9fc17db0,8),
 ('instruction-cache-enable',0x9fc18070,0x68),('data-cache-enable',0x9fc17f6c,0x68),
 ('canary-init',0x9fc0cd44,0x1c),('canary-source',0x9fc1aa88,4),('sec-next-calls',0x9fc0cf38,0x20))


def contract():
    b,m=payload();md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);windows={}
    for name,a,n in WINDOWS:
        data=b[a-0x9fc00000:a-0x9fc00000+n];ins=[{'address':hex(i.address),'mnemonic':i.mnemonic,'operands':i.op_str} for i in md.disasm(data,a)]
        if len(ins)*4!=n:raise ValueError('Incomplete original cache window '+name)
        windows[name]={'address':hex(a),'size':n,'sha256':hashlib.sha256(data).hexdigest(),'instructions':ins}
    for name,index,mnemonic,operand in (('cache-startup',2,'bl','#0x9fc182b0'),
      ('setway-op',0,'dc','isw, x0'),('canary-source',0,'b','#0x9fc2849c')):
        i=windows[name]['instructions'][index]
        if (i['mnemonic'],i['operands'])!=(mnemonic,operand):raise ValueError('Unexpected original cache/canary contract')
    return {'firmware_sha256':m['firmware_sha256'],'fv_sha256':m['segment_sha256'],
      'windows':windows,'stop_before':hex(STOP),'stop_occurrence':2,'canary_store_address':'0x9fc350a8','initial_canary_word':hex(struct.unpack_from('<Q',b,0x350a8)[0]),
      'setway_callback':'0x9fc17db0','expected_second_sp':'0x9ffcfce0',
      'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'scope':'Original SEC data-cache set/way invalidation, I/D cache enabling at existing EL, and canary source dispatch to second eight-byte buffer SMC. Paused before SMC; no second buffer reply/canary store, physical cache/coherency proof, complete SEC/UEFI/ABL/Linux boot or physical KVM.'}


def geometry(raw):
    if not 0<=raw<=0xffffffffffffffff:raise ValueError('Invalid CCSIDR word')
    return {'raw_ccsidr':hex(raw),'line_bytes':1<<((raw&7)+4),
      'ways':((raw>>3)&0x3ff)+1,'sets':((raw>>13)&0x7fff)+1,
      'setway_operations':(((raw>>3)&0x3ff)+1)*(((raw>>13)&0x7fff)+1),
      'scope':'Decoded with masks/shifts from pinned original loop, not a physical cache-size measurement.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'reports/qhee-offline/cache-startup-static');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);r=contract()
    for name,w in r['windows'].items():(a.out/(name+'.txt')).write_text(''.join(f"{i['address']}: {i['mnemonic']} {i['operands']}\n" for i in w['instructions']))
    (a.out/'manifest.json').write_text(json.dumps(r,indent=2)+'\n');print('Second buffer boundary',r['stop_before'])

if __name__=='__main__':main()
