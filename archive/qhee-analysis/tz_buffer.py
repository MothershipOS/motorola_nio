#!/usr/bin/env python3
"""Bounded original TZ buffer/PRNG slices with explicit ownership and FIFO fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_INVALID
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_X23, UC_ARM64_REG_X29, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC
from tz_handoff import image, PINNED_TZ
from xbl_target import read
from qhee import ROOT
from tz_query import lookup

RAM=0x90000000; SP=0x9000f000; RETURN=0x90008000
BUFFER=0x9fc356c0; DRIVER=0x1c11b5a8; MMIO=0x791000
REGIONS=((0x14682000,0x3000),(0x1c03b000,0x8000),(0x1c04d000,0x1000),(0x1c050000,0x7000),
         (0x1c064000,0x4000),(0x1c07b000,0x3000),(0x1c11b000,0x1000),
         (0x1c0c0000,0x2000),(0x1c0c7000,0x1000),(0x1c122000,0x2000),(0x1c157000,0x1000))
WINDOWS=(('typed-argument-validation',0x1c067118,0x11c),('decode',0x1c06734c,0x318),
 ('marshaller',0x1c06794c,0x1c4),('handler',0x1c054b30,0x130),
 ('pointer-front',0x1c065b0c,0x11c),('typed-pointer-front',0x1c065c28,0xbc),('pointer-arithmetic',0x1c065a74,0x98),
 ('ownership-front',0x1c0c0b68,0x160),('backend-selector',0x1c03e058,0xc),
 ('random-wrapper',0x1c03d0d0,0x90),('prng-backend',0x1c042c8c,0x24c),
 ('driver-getters',0x1c03d468,0x10),('four-byte-copy',0x1c03d3dc,0x4c),
 ('backend-state-callback',0x1c0549c8,0x64),('driver-start',0x1c05495c,0x34),
 ('clock-front',0x1c0666dc,0x48),('cache-front',0x1c0c72e4,4))
POINTS=(0x1c067598,0x1c0671d4,0x1c054b30,0x1c054bd8,0x1c03d0d0,
        0x1c042c8c,0x1c042cc0,0x1c042e94,0x1c054bdc,0x1c054bf8)

def inventory():
    data,segments=image();md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);windows={}
    for name,a,n in WINDOWS:
        b=read(data,segments,a,n);ins=[{'address':hex(i.address),'mnemonic':i.mnemonic,'operands':i.op_str} for i in md.disasm(b,a)]
        if len(ins)*4!=n:raise ValueError('Incomplete TZ buffer window '+name)
        windows[name]={'address':hex(a),'size':n,'sha256':hashlib.sha256(b).hexdigest(),'instructions':ins}
    driver=read(data,segments,DRIVER,0x110);selector=struct.unpack('<Q',read(data,segments,0x1c03b050,8))[0]
    base=struct.unpack_from('<I',driver,0x14)[0];copy=struct.unpack_from('<Q',driver,0x78)[0]
    if (selector,base,copy)!=(0x1c042c8c,MMIO,0x1c050c88):raise ValueError('Unexpected pinned PRNG backend')
    return {'firmware_sha256':PINNED_TZ,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'windows':windows,'registry':lookup(0x02000a01),'backend_selector':hex(selector),'driver_address':hex(DRIVER),
      'driver_hex':driver.hex(),'driver_sha256':hashlib.sha256(driver).hexdigest(),'mmio_base':hex(base),
      'copy_callback':hex(copy),'scope':'Original file-backed code/data; driver table and backend pointer are image values, not captured secure runtime state.'}

class Slice:
    def __init__(self,fifo=None):
        data,segments=image();self.u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);self.regions=[]
        for a,n in REGIONS:
            b=read(data,segments,a,n);self.u.mem_map(a,n);self.u.mem_write(a,b)
            self.regions.append({'address':hex(a),'size':n,'sha256':hashlib.sha256(b).hexdigest()})
        self.u.mem_map(RAM,0x10000);self.u.mem_map(BUFFER&~0xfff,0x1000)
        self.u.mem_write(BUFFER-16,b'\xa5'*16+b'\0'*8+b'\xa5'*16)
        self.u.reg_write(UC_ARM64_REG_SP,SP);self.u.reg_write(UC_ARM64_REG_LR,RETURN)
        self.fifo=None if fifo is None else list(fifo);self.samples=[];self.status_reads=0
        if fifo is not None:self.u.mem_map(MMIO,0x1000)
        self.pcs=[];self.writes=[];self.reads=[];self.checkpoints=[]
        def instruction(u,a,n,_):
            if not any(base<=a<base+size for base,size in REGIONS):raise ValueError('Unmodeled TZ buffer instruction '+hex(a))
            self.pcs.append(hex(a))
            if a in POINTS or a in self.stops:self.checkpoints.append({'pc':hex(a),'registers':self.registers()})
            if a in self.stops:u.emu_stop()
        def write(u,access,a,n,v,_):
            if not (RAM<=a and a+n<=RAM+0x200 or SP-0x2000<=a and a+n<=SP+0x200 or BUFFER<=a and a+n<=BUFFER+8):
                raise ValueError('Unexpected TZ buffer write '+hex(a))
            self.writes.append({'address':hex(a),'size':n,'value':hex(v&((1<<(8*n))-1))})
        def memory_read(u,access,a,n,v,_):
            self.reads.append({'address':hex(a),'size':n})
            if MMIO<=a<MMIO+0x1000:
                if self.fifo is None or n!=4 or a not in (MMIO,MMIO+4):raise ValueError('Unknown PRNG MMIO access')
                if a==MMIO+4:
                    if self.status_reads>=4:raise ValueError('PRNG ready-read bound exhausted')
                    value=1;self.status_reads+=1
                else:
                    if not self.fifo:raise ValueError('PRNG FIFO fixture exhausted')
                    value=self.fifo.pop(0);self.samples.append(hex(value))
                u.mem_write(a,struct.pack('<I',value))
        def invalid(u,access,a,n,v,_):raise ValueError('Unmapped TZ buffer access '+hex(a))
        self.u.hook_add(UC_HOOK_CODE,instruction);self.u.hook_add(UC_HOOK_MEM_WRITE,write)
        self.u.hook_add(UC_HOOK_MEM_READ,memory_read);self.u.hook_add(UC_HOOK_MEM_INVALID,invalid)
    def registers(self):
        return {**{'x'+str(i):hex(self.u.reg_read(UC_ARM64_REG_X0+i)) for i in range(29)},
                'x29':hex(self.u.reg_read(UC_ARM64_REG_X29)),'x30':hex(self.u.reg_read(UC_ARM64_REG_LR)),
                'sp':hex(self.u.reg_read(UC_ARM64_REG_SP))}
    def execute(self,start,stops=()):
        offsets=(len(self.pcs),len(self.writes),len(self.reads),len(self.checkpoints))
        self.stops=tuple(stops);self.u.emu_start(start,RETURN,count=5000);pc=self.u.reg_read(UC_ARM64_REG_PC)
        if pc not in self.stops+(RETURN,):raise ValueError('TZ buffer instruction bound exhausted')
        return {'start':hex(start),'stop':hex(pc),'registers':self.registers(),'pcs':self.pcs[offsets[0]:],
          'writes':self.writes[offsets[1]:],'reads':self.reads[offsets[2]:],'checkpoints':self.checkpoints[offsets[3]:],
          'loaded_regions':self.regions,'buffer_hex':bytes(self.u.mem_read(BUFFER,8)).hex(),
          'guard_before_hex':bytes(self.u.mem_read(BUFFER-16,16)).hex(),'guard_after_hex':bytes(self.u.mem_read(BUFFER+8,16)).hex()}

def decode(words):
    if len(words)!=14 or any(v<0 or v>0xffffffffffffffff for v in words):raise ValueError('TZ buffer needs fourteen uint64 registers')
    f=Slice();f.u.mem_write(RAM,struct.pack('<14Q',*words));f.u.reg_write(UC_ARM64_REG_X19,RAM);f.u.reg_write(UC_ARM64_REG_X20,words[0])
    r=f.execute(0x1c0673b8,(0x1c065b0c,0x1c065c28,0x1c067664,0x1c06748c))
    r.update({'input':[hex(v) for v in words],'normalized_hex':bytes(f.u.mem_read(SP+0x80,0x100)).hex(),
      'descriptor_hex':bytes(f.u.mem_read(SP+0x18,24)).hex(),'validator_scratch_x23':hex(f.u.reg_read(UC_ARM64_REG_X23)&0xffffffff),
      'validation_status':None if r['stop'] in ('0x1c065b0c','0x1c065c28') else hex(f.u.reg_read(UC_ARM64_REG_X23)&0xffffffff),
      'scope':'Original decode after accounting, normalization/count/type comparison and typed argument validator. Valid request stops at first pointer checker before interrupt/lock/translation/ownership lookup; validation is pending.'})
    return r

def handler(normalized,descriptor):
    frame=bytearray(bytes.fromhex(normalized));desc=bytes.fromhex(descriptor)
    if len(frame)!=256 or len(desc)!=24:raise ValueError('Invalid buffer frame/descriptor')
    _,ident,info,flags,callback=struct.unpack('<4IQ',desc)
    if (ident,info,flags,callback)!=(0x02000a01,0x22,1,0x1c054b30):raise ValueError('Marshaller restricted to pinned buffer handler')
    struct.pack_into('<2Q',frame,0,callback,info&15)
    f=Slice();f.u.mem_write(RAM,bytes(frame));f.u.reg_write(UC_ARM64_REG_X0,RAM)
    r=f.execute(0x1c06794c,(0x1c065b0c,0x1c04d62c));r['invocation_hex']=frame.hex()
    return f,r

def pointer_arithmetic(address=BUFFER,size=8):
    f=Slice();f.u.reg_write(UC_ARM64_REG_X0,address);f.u.reg_write(UC_ARM64_REG_X0+1,size)
    f.u.reg_write(UC_ARM64_REG_X0+2,8);f.u.reg_write(UC_ARM64_REG_X0+3,0)
    r=f.execute(0x1c065a74,(0x1c0c0b68,));r['scope']='Original overflow/end-bound/page rounding through ownership lookup entry; no ownership result.'
    return r

def backend_setup():
    f=Slice();f.u.reg_write(UC_ARM64_REG_X19,DRIVER);f.u.reg_write(UC_ARM64_REG_X20,8)
    f.u.reg_write(UC_ARM64_REG_X0+21,BUFFER);f.u.reg_write(UC_ARM64_REG_X0,0)
    r=f.execute(0x1c042cc4,(0x1c0666dc,))
    r['scope']='Separately seeded backend after state callback returned zero; original driver callback reaches clock-front dependency with index 4. No clock response or setup MMIO.'
    return r


def fifo_slice(samples=(0x11223344,0x55667788,0x99aabbcc,0xddeeff11)):
    if len(samples)!=4 or any(v<0 or v>0xffffffff for v in samples):raise ValueError('PRNG fixture requires four uint32 FIFO samples')
    f=Slice(samples);f.u.reg_write(UC_ARM64_REG_X19,DRIVER);f.u.reg_write(UC_ARM64_REG_X20,8)
    f.u.reg_write(UC_ARM64_REG_X0+21,BUFFER)
    r=f.execute(0x1c042df8,(0x1c042ec8,))
    if f.fifo:raise ValueError('Unconsumed PRNG FIFO samples')
    r.update({'fifo_samples':f.samples,'ready_reads':f.status_reads,'produced_bytes':int(r['registers']['x23'],16),
      'scope':'Separately seeded eight-byte original FIFO loop after successful clock/state/setup assumptions. Exactly four synthetic FIFO words and four ready reads; original pair filtering/XOR/four-byte copy. Stops before backend release; no physical entropy or hardware initialization.'})
    return r

def run(words=None,produced=None):
    words=words if words is not None else [0x02000a01,0x22,BUFFER,8,0,1,0x801cba78]+[0]*7
    d=decode(words)
    if d['stop'] not in ('0x1c065b0c','0x1c065c28'):raise ValueError('Buffer request does not reach original pointer check')
    args=struct.unpack_from('<2Q',bytes.fromhex(d['normalized_hex']),16)
    if args!=(BUFFER,8):raise ValueError('Joined slices restricted to original eight-byte request')
    f,h=handler(d['normalized_hex'],d['descriptor_hex'])
    if h['stop']!='0x1c065b0c':raise ValueError('Buffer handler rejects request')
    # Explicit slice join: assume both ownership checks and secure policy accept.
    f.u.reg_write(UC_ARM64_REG_X0,1)
    b=f.execute(0x1c054bc0,(0x1c0549c8,))
    call=next(c['registers'] for c in b['checkpoints'] if c['pc']=='0x1c054bd8')
    fifo=fifo_slice();count=fifo['produced_bytes'] if produced is None else produced
    if not 0<=count<=8:raise ValueError('Synthetic produced count outside buffer')
    # Seed backend return at original caller's continuation; backend release and
    # hardware startup were not executed. Restore original pre-call SP.
    for i in range(29):f.u.reg_write(UC_ARM64_REG_X0+i,int(call['x'+str(i)],16))
    f.u.reg_write(UC_ARM64_REG_X29,int(call['x29'],16));f.u.reg_write(UC_ARM64_REG_LR,int(call['x30'],16))
    f.u.reg_write(UC_ARM64_REG_SP,int(call['sp'],16));f.u.reg_write(UC_ARM64_REG_X0,count)
    f.u.mem_write(BUFFER,bytes.fromhex(fifo['buffer_hex'])[:count]+b'\0'*(8-count))
    post=f.execute(0x1c054bdc,(0x1c0c72e4,))
    if post['stop']!='0x1c0c72e4':raise ValueError('Missing original buffer cache boundary')
    result=f.execute(0x1c054bf8,(0x1c04d62c,)) # separately assume cache helper completed
    reply=bytes(f.u.mem_read(RAM,64))
    return {'inventory':inventory(),'decode':d,'handler':h,'backend':b,'pointer_arithmetic':pointer_arithmetic(),
      'backend_setup':backend_setup(),'joins':[
        {'resume':'0x1c054bc0','assumption':'Original typed pointer check and handler pointer check both accept, and secure policy permits the callback; seed handler pointer-check result x0=1.'},
        {'resume':'0x1c042df8','assumption':'Original backend clock/state and setup succeeded; finite ready/FIFO fixtures replace physical MMIO reads.'},
        {'resume':'0x1c054bdc','assumption':'Backend completes release and returns the fixture-derived byte count; restore pre-call registers/SP and seed the requested buffer bytes.'},
        {'resume':'0x1c054bf8','assumption':'Original cache helper completed; physical cache effects are unverified.'}],
      'fifo':fifo,'post_backend':post,'return':result,'produced_fixture':count,'reply_frame_hex':reply.hex(),
      'reply_x0_x7':[hex(v) for v in struct.unpack('<8Q',reply)] if result['stop']==hex(RETURN) else None,
      'scope':'Separately seeded original slices with explicit successful ownership/policy, backend setup/release and cache-completion assumptions. FIFO values are synthetic fixtures. No EL3 reply added, original TZ context switch/return, phone entropy, firmware write or physical acceptance.'}

def reply_model():
    r=run();fifo=r['fifo'];reply=r['reply_x0_x7'][:4]
    if reply!=['0x0','0x8','0x0','0x0'] or fifo['produced_bytes']!=8:
        raise ValueError('Unexpected original buffer slice result')
    return {'firmware_sha256':PINNED_TZ,'source_sha256':r['inventory']['source_sha256'],
      'request_prefix':['0x2000a01','0x22','0x9fc356c0','0x8'],'reply_x0_x3':reply,
      'buffer_hex':fifo['buffer_hex'],'buffer_word':hex(int.from_bytes(bytes.fromhex(fifo['buffer_hex']),'little')),
      'fifo_samples':fifo['fifo_samples'],'ready_reads':fifo['ready_reads'],'joins':r['joins'],
      'derivation_sha256':hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest(),
      'scope':'Exact one-shot offline buffer reply from original slices and finite synthetic FIFO inputs. Ownership/policy, setup/release, cache completion and monitor context/return remain assumptions; fixture bytes are not entropy.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'reports/qhee-offline/tz-buffer-static')
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);r=run()
    for name,w in r['inventory']['windows'].items():
        (a.out/(name+'.txt')).write_text(''.join(f"{i['address']}: {i['mnemonic']} {i['operands']}\n" for i in w['instructions']))
    (a.out/'manifest.json').write_text(json.dumps(r,indent=2)+'\n');print('Fixture-derived buffer reply',r['reply_x0_x7'][:4])

if __name__=='__main__':main()
