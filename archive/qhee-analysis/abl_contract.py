"""Pinned ABL launch boundary and a bounded PE32+ relocation loader."""
import hashlib
import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from bootchain import PINNED, loads, volume, image_info
from qhee import ROOT

BASE=0x90000000
PREPARE=0x5e2e0
LAUNCH=0x61da0
WINDOWS={'prepare':(PREPARE,0x34),'aarch64-launch':(LAUNCH,0x18),
    'bootservices':(0x5e140,0x1a0),'launch-callsite':(0x61bec,0x40),
    'dcache-off':(0x95ea0,0x70),'icache-off':(0x95f80,0x70),'mmu-off':(0x95d08,0x7c),
    'dcache-setway':(0x960b8,0xc4),'cache-callback':(0x95c50,0x10),'tlbi':(0x96538,0x3c),
    'hyp-uart-call':(0x70b20,0x90),'smc-wrapper':(0x9c368,0x2c)}


def pinned_image():
    path=ROOT/'backups/nio-firmware-20260927T163534Z/abl_a.img';data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=PINNED['abl_a.img']:raise ValueError('Requires pinned ABL')
    _,segments=loads(data);matches=[s for s in segments if s['address']==0x9fa00000]
    if len(matches)!=1:raise ValueError('Unexpected ABL container')
    seg=matches[0];records=[r for r in volume(data[seg['offset']:seg['offset']+seg['size']],seg['address']) if 'data' in r]
    if len(records)!=1 or records[0]['names']!=['MotoBootModule']:raise ValueError('Unexpected ABL executable')
    image=image_info(records[0])
    if image['format']!='PE32+' or image['machine']!='0xaa64':raise ValueError('Requires AArch64 PE32+')
    return records[0]['data'],image


def map_pe(data,base=BASE):
    # This loader is for the offline fixture; the physical runtime base is unknown.
    image_info({'kind':0x10,'address':None,'data':data})
    pe=struct.unpack_from('<I',data,60)[0];opt=pe+24
    machine,count=struct.unpack_from('<HH',data,pe+4);opt_size=struct.unpack_from('<H',data,pe+20)[0]
    if machine!=0xaa64 or opt_size<160:raise ValueError('Unsupported PE mapping header')
    preferred=struct.unpack_from('<Q',data,opt+24)[0];size,headers=struct.unpack_from('<II',data,opt+56)
    if base&4095 or base<0 or size==0 or size>16*1024*1024 or base+size>1<<64:
        raise ValueError('Invalid PE mapping base/size')
    if not 0<headers<=min(size,len(data)):raise ValueError('Invalid PE header mapping')
    mapped=bytearray(size);mapped[:headers]=data[:headers];ranges=[(0,headers)]
    for i in range(count):
        pos=opt+opt_size+40*i;vs,va,n,off=struct.unpack_from('<4I',data,pos+8);span=max(vs,n)
        if va+span>size or off+n>len(data) or any(va<a+s and a<va+span for a,s in ranges):
            raise ValueError('Invalid/overlapping PE mapped section')
        ranges.append((va,span));mapped[va:va+n]=data[off:off+n]
    if struct.unpack_from('<I',data,opt+108)[0]<6:raise ValueError('Missing relocation directory')
    rva,n=struct.unpack_from('<II',data,opt+112+5*8)
    if not n or rva+n>size:raise ValueError('Invalid relocation directory bounds')
    reloc=bytes(mapped[rva:rva+n]);pos=0;targets=[];seen=set()
    while pos<len(reloc):
        if pos+8>len(reloc):raise ValueError('Short relocation block')
        page,length=struct.unpack_from('<II',reloc,pos)
        if length<8 or length&3 or pos+length>len(reloc):raise ValueError('Invalid relocation block bounds')
        for at in range(pos+8,pos+length,2):
            word=struct.unpack_from('<H',reloc,at)[0];kind=word>>12;target=page+(word&4095)
            if kind==0:continue
            if kind!=10:raise ValueError('Unsupported relocation type')
            if target+8>size or target in seen or target<rva+n and rva<target+8:
                raise ValueError('Invalid relocation target')
            old=struct.unpack_from('<Q',mapped,target)[0];value=old+base-preferred
            if not 0<=value<1<<64:raise ValueError('Relocation value overflow')
            struct.pack_into('<Q',mapped,target,value);seen.add(target);targets.append(target)
        pos+=length
    metadata={'base':hex(base),'size':size,'preferred_base':hex(preferred),'relocations':len(targets),
        'relocation_targets':list(map(hex,targets)),'mapped_sha256':hashlib.sha256(mapped).hexdigest(),
        'scope':'Offline PE mapping with DIR64 relocations; chosen base is synthetic, not captured on nio.'}
    return bytes(mapped),metadata


def inventory():
    data,image=pinned_image();mapped,mapping=map_pe(data);md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);windows={}
    for name,(start,n) in WINDOWS.items():
        if not any(off<=start and start+n<=off+size and va==off for off,size,va in image['executable_ranges']):
            raise ValueError('Unexpected ABL executable RVA/file-offset layout')
        if mapped[start:start+n]!=data[start:start+n]:raise ValueError('Relocation changed an instruction window')
        instructions=[{'rva':hex(i.address),'mnemonic':i.mnemonic,'operands':i.op_str} for i in md.disasm(data[start:start+n],start)]
        if len(instructions)*4!=n:raise ValueError('Incomplete ABL instruction window')
        windows[name]={'rva':hex(start),'size':n,'sha256':hashlib.sha256(data[start:start+n]).hexdigest(),'instructions':instructions}
    return data,mapped,{'firmware_sha256':PINNED['abl_a.img'],'executable_sha256':image['sha256'],
        'mapping':mapping,'windows':windows,
        'launch_contract':{'kernel_pointer':'[x23-0x70] -> x8','dtb_pointer':'[x23-0x58] -> x0','x1_x2_x3':'zero','transfer':'blr x8 at RVA 0x61db4'},
        'scope':'Pinned static launch/preparation windows and isolated execution fixture. Not a full ABL CFG or earlier UEFI/boot-chain EL2 validation.'}
