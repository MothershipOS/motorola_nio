#!/usr/bin/env python3
"""Original TZ query decoding, registry and marshalling slices; no policy bypass claim."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE,UC_HOOK_MEM_READ,UC_HOOK_MEM_INVALID
from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X19,UC_ARM64_REG_X20,UC_ARM64_REG_X23,UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC
from tz_handoff import image,PINNED_TZ
from xbl_target import read
from qhee import ROOT

RAM=0x90000000;SP=0x9000f000;RETURN=0x90008000
REGIONS=((0x14682000,0x2000),(0x1c050000,0x2000),(0x1c067000,0x1000),
         (0x1c07b000,0x3000),(0x1c122000,0x2000),(0x1c157000,0x1000))
WINDOWS=(('secure-el1-dispatch',0x1c04bbc4,0x90),('normal-service-branch',0x1c04bd74,0xd4),
         ('argument-decode',0x1c06734c,0x318),('argument-validator',0x1c067118,0x11c),
         ('availability-handler',0x1c06705c,0x88),('handler-marshaller',0x1c06794c,0x1c4),
         ('registry',0x1c07ba00,0x16d4),('safe-copy',0x14682fd4,0x30),
         ('copy',0x14683034,0x280),('clear',0x1c050b8c,0xd0),('reply-copy',0x1c050c88,0x650))


def inventory():
    data,segments=image();md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);windows={}
    for name,a,n in WINDOWS:
        b=read(data,segments,a,n);ins=[{'address':hex(i.address),'mnemonic':i.mnemonic,'operands':i.op_str} for i in md.disasm(b,a)]
        if len(ins)*4!=n:raise ValueError('Incomplete TZ query window '+name)
        windows[name]={'address':hex(a),'size':n,'sha256':hashlib.sha256(b).hexdigest(),'instructions':ins}
    return {'firmware_sha256':PINNED_TZ,'windows':windows,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope':'Pinned original secure EL1 dispatcher dataflow and separately seeded argument/registry/marshaller execution. Does not execute full EL3 context switching, secure startup, policy/accounting/locking wrappers, original SMC return or physical TZ.'}


class Slice:
    def __init__(self):
        data,segments=image();self.u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);self.regions=[]
        for a,n in REGIONS:
            b=read(data,segments,a,n);self.u.mem_map(a,n);self.u.mem_write(a,b)
            self.regions.append({'address':hex(a),'size':n,'sha256':hashlib.sha256(b).hexdigest()})
        self.u.mem_map(RAM,0x10000);self.u.reg_write(UC_ARM64_REG_SP,SP);self.u.reg_write(UC_ARM64_REG_LR,RETURN)
        self.pcs=[];self.writes=[];self.reads=[];self.checkpoints=[]
        def instruction(u,a,n,_):
            if not any(base<=a<base+size for base,size in REGIONS):raise ValueError('Unmodeled TZ query instruction '+hex(a))
            self.pcs.append(hex(a))
            if a in (0x1c06743c,0x1c067448,0x1c067598,0x1c06765c,0x1c067664,0x1c06748c):
                self.checkpoints.append({'pc':hex(a),'x0':hex(u.reg_read(UC_ARM64_REG_X0)),
                    'x23':hex(u.reg_read(UC_ARM64_REG_X23)),'normalized_hex':bytes(u.mem_read(SP+0x80,0x100)).hex(),
                    'descriptor_hex':bytes(u.mem_read(SP+0x18,24)).hex()})
            if a in self.stops:u.emu_stop()
        def write(u,access,a,n,v,_):
            if not (RAM<=a and a+n<=RAM+0x200 or SP-0x2000<=a and a+n<=SP+0x200):
                raise ValueError('Unexpected TZ query write '+hex(a))
            self.writes.append({'address':hex(a),'size':n,'value':hex(v&((1<<(8*n))-1))})
        def memory_read(u,access,a,n,v,_):self.reads.append({'address':hex(a),'size':n})
        def invalid(u,access,a,n,v,_):raise ValueError('Unmapped TZ query access '+hex(a)+' at '+hex(u.reg_read(UC_ARM64_REG_PC)))
        self.u.hook_add(UC_HOOK_CODE,instruction);self.u.hook_add(UC_HOOK_MEM_WRITE,write)
        self.u.hook_add(UC_HOOK_MEM_READ,memory_read);self.u.hook_add(UC_HOOK_MEM_INVALID,invalid)
    def execute(self,start,stops=()):
        self.stops=stops;self.u.emu_start(start,RETURN,count=5000)
        pc=self.u.reg_read(UC_ARM64_REG_PC)
        if pc not in tuple(stops)+(RETURN,):raise ValueError('TZ query instruction bound exhausted')
        return {'start':hex(start),'stop':hex(pc),'x0':hex(self.u.reg_read(UC_ARM64_REG_X0)),
                'pcs':self.pcs,'writes':self.writes,'reads':self.reads,'checkpoints':self.checkpoints,
                'loaded_regions':self.regions}


def lookup(fn):
    f=Slice();f.u.mem_write(RAM,b'\xa5'*64);f.u.reg_write(UC_ARM64_REG_X0,fn);f.u.reg_write(UC_ARM64_REG_X1,RAM)
    r=f.execute(0x1c07ba00);b=bytes(f.u.mem_read(RAM,64));r.update({'function_id':hex(fn),'descriptor_hex':b[:24].hex(),
        'descriptor':dict(zip(('untouched','function_id','arginfo','flags','handler'),[hex(v) for v in struct.unpack('<4IQ',b[:24])])),
        'guard_after_hex':b[24:].hex()});return r


def decode(words):
    if len(words)!=14 or any(v<0 or v>0xffffffffffffffff for v in words):raise ValueError('TZ query fixture requires fourteen uint64 registers')
    f=Slice();f.u.mem_write(RAM,struct.pack('<14Q',*words));f.u.reg_write(UC_ARM64_REG_X19,RAM);f.u.reg_write(UC_ARM64_REG_X20,words[0])
    r=f.execute(0x1c0673b8,(0x1c067664,0x1c06748c))
    r.update({'input':[hex(v) for v in words],'normalized_hex':bytes(f.u.mem_read(SP+0x80,0x100)).hex(),
              'descriptor_hex':bytes(f.u.mem_read(SP+0x18,24)).hex(),'validation_status':hex(f.u.reg_read(UC_ARM64_REG_X23)&0xffffffff),
              'scope':'Starts after owner accounting with synthetic frame/SP. Original copy, normalization, registry and argument validation execute continuously; stops before policy getter 0x1c04c984 or error handling.'})
    return r


def marshal(normalized,descriptor):
    frame=bytearray(bytes.fromhex(normalized));desc=bytes.fromhex(descriptor)
    if len(frame)!=0x100 or len(desc)!=24:raise ValueError('Invalid normalized query/descriptor length')
    _,ident,arginfo,flags,handler=struct.unpack('<4IQ',desc)
    if ident!=0x02000601 or arginfo!=1 or handler!=0x1c06705c:raise ValueError('Marshaller restricted to original availability handler')
    struct.pack_into('<2Q',frame,0,handler,arginfo&15)
    f=Slice();f.u.mem_write(RAM,bytes(frame));f.u.reg_write(UC_ARM64_REG_X0,RAM)
    r=f.execute(0x1c06794c);reply=bytes(f.u.mem_read(RAM,64))
    r.update({'invocation_hex':frame.hex(),'reply_frame_hex':reply.hex(),'reply_x0_x7':[hex(v) for v in struct.unpack('<8Q',reply)],
              'scope':'Separately seeded original callback marshaller invokes the registry-derived availability handler and copies seven return words. Original file-backed stack-canary value; no policy/locking wrapper or EL3 return.'});return r


def run(words=None):
    words=words or [0x02000601,1,0x02000602,0x9ffd0000,0,1,0x801cba78]+[0]*7
    d=decode(words)
    if d['stop']!='0x1c067664' or d['validation_status']!='0x0':raise ValueError('Original TZ query argument validation failed')
    m=marshal(d['normalized_hex'],d['descriptor_hex'])
    return {'inventory':inventory(),'decode':d,'query_registry':lookup(0x02000601),'target_registry':lookup(words[2]),'marshal':m,
            'reply_x0_x3':m['reply_x0_x7'][:4],
            'scope':'Original bounded secure EL1 slices with constructed caller frame. Query lookup, count/type validation, callback and return marshalling; remaining policy/context-switch/return path and physical acceptance unverified.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'reports/qhee-offline/tz-query-static')
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True);r=run()
    for name,w in r['inventory']['windows'].items():
        (args.out/(name+'.txt')).write_text(''.join(f"{i['address']}: {i['mnemonic']} {i['operands']}\n" for i in w['instructions']))
    (args.out/'manifest.json').write_text(json.dumps(r,indent=2)+'\n');print('Original query reply',r['reply_x0_x3'])



def reply_model():
    r=run()
    if r['reply_x0_x3']!=['0x0']*4 or r['target_registry']['x0']!='0x1':
        raise ValueError('Unexpected original TZ availability reply')
    return {'firmware_sha256':PINNED_TZ,'source_sha256':r['inventory']['source_sha256'],
            'request_prefix':['0x2000601','0x1','0x2000602'],'reply_x0_x3':r['reply_x0_x3'],
            'query_handler':'0x1c06705c','queried_function_registered':False,
            'derivation_sha256':hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest(),
            'scope':'Exact one-shot synthetic EL3 reply derived from original bounded TZ decoding/registry/marshalling slices. Policy, secure context switching and physical acceptance assumed; no entropy or generic query service.'}


if __name__=='__main__':main()
