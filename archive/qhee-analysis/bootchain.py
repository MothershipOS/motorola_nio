#!/usr/bin/env python3
"""Bounded static XBL SEC / ABL image inventory; no boot-chain execution claims."""
import argparse
import hashlib
import json
import lzma
from pathlib import Path
import struct
import uuid
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from qhee import ROOT

PINNED={'xbl_a.img':'c6ea293817ab2803a12067e6bcd631a660ae9a132a96f3fba2e9107e0eea666d',
        'abl_a.img':'fdd4a5da347ca312901cf927d75b9f77d80f095cd4de54bad301088a77f1f43c'}
LZMA_GUID='ee4e5898-3914-4259-9d6e-dc7bd79403cf'
LIMIT=16*1024*1024


def loads(data):
    if len(data)<64 or data[:4]!=b'\x7fELF' or data[5]!=1:raise ValueError('Not supported little-endian ELF')
    if data[4]==2:
        entry,phoff=struct.unpack_from('<QQ',data,24);phsize,count=struct.unpack_from('<HH',data,54);minimum=56
    elif data[4]==1:
        entry,phoff=struct.unpack_from('<II',data,24);phsize,count=struct.unpack_from('<HH',data,42);minimum=32
    else:raise ValueError('Unsupported ELF class')
    if phsize<minimum or count>64 or phoff+count*phsize>len(data):raise ValueError('Invalid program-header bounds')
    result=[]
    for i in range(count):
        pos=phoff+i*phsize
        if data[4]==2:
            t,flags,off,va,pa,size,mem,align=struct.unpack_from('<II6Q',data,pos)
        else:t,off,va,pa,size,mem,flags,align=struct.unpack_from('<8I',data,pos)
        if off+size>len(data):raise ValueError('Segment outside file')
        if t==1:
            if mem<size:raise ValueError('Segment filesz exceeds memsz')
            result.append({'offset':off,'address':va,'size':size,'memsz':mem,'flags':flags})
    return entry,result


def sections(data,base,depth=0):
    if depth>8 or len(data)>LIMIT:raise ValueError('Section recursion/size bound')
    pos=0;result=[]
    while pos+4<=len(data):
        size=int.from_bytes(data[pos:pos+3],'little');kind=data[pos+3]
        if size<4 or size==0xffffff or pos+size>len(data):raise ValueError('Invalid section bounds')
        body=data[pos+4:pos+size];address=None if base is None else base+pos+4
        if kind in (0x10,0x12):result.append({'kind':kind,'address':address,'data':body})
        elif kind==0x15:result.append({'name':body.decode('utf-16-le').rstrip('\0')})
        elif kind==0x17:result+=volume(body,address,depth+1)
        elif kind==2:
            if size<24:raise ValueError('Short guided section')
            guid=str(uuid.UUID(bytes_le=body[:16]));offset,attrs=struct.unpack_from('<HH',body,16)
            if not 24<=offset<size:raise ValueError('Invalid guided payload offset')
            if guid==LZMA_GUID:
                payload=data[pos+offset:pos+size]
                decoder=lzma.LZMADecompressor(format=lzma.FORMAT_ALONE,memlimit=128*1024*1024)
                decompressed=decoder.decompress(payload,max_length=LIMIT+1)
                if len(decompressed)>LIMIT or not decoder.eof:raise ValueError('LZMA stream exceeds bound or is truncated')
                result+=sections(decompressed,None,depth+1)
        pos=(pos+size+3)&~3
    if any(data[pos:]):raise ValueError('Invalid section trailing bytes')
    return result


def volume(data,base=None,depth=0,skip_compressed=False):
    if depth>8 or len(data)<56 or data[40:44]!=b'_FVH':raise ValueError('Invalid firmware volume')
    size=struct.unpack_from('<Q',data,32)[0];header=struct.unpack_from('<H',data,48)[0]
    if not 56<=header<=size<=len(data) or header&1:raise ValueError('Invalid FV bounds')
    if sum(struct.unpack('<'+'H'*(header//2),data[:header]))&65535:raise ValueError('Invalid FV checksum')
    pos=(header+7)&~7;result=[]
    while pos+24<=size:
        h=data[pos:pos+24]
        if h==b'\xff'*24 or h==b'\0'*24:break
        n=int.from_bytes(h[20:23],'little');kind=h[18]
        if n<24 or n==0xffffff or pos+n>size:raise ValueError('Invalid FFS bounds')
        if kind!=0xf0:
            payload=data[pos+24:pos+n]
            if not (skip_compressed and kind==0xb):
                records=sections(payload,None if base is None else base+pos+24,depth)
                names=[r['name'] for r in records if 'name' in r]
                for r in records:
                    if 'data' in r:r.update({'file_guid':str(uuid.UUID(bytes_le=h[:16])),'file_type':kind,'names':names})
                result+=records
        pos=(pos+n+7)&~7
    return result


def image_info(record):
    data=record['data'];address=record['address'];kind=record['kind']
    if kind==0x12:
        if len(data)<40 or data[:2]!=b'VZ':raise ValueError('Invalid TE image')
        machine=struct.unpack_from('<H',data,2)[0];stripped=struct.unpack_from('<H',data,6)[0]
        entry=struct.unpack_from('<I',data,8)[0];preferred=struct.unpack_from('<Q',data,16)[0]
        adjusted=entry-stripped+40
        if not 40<=adjusted<len(data):raise ValueError('Invalid TE entry')
        count=data[4];executable=[]
        if count>64 or 40+count*40>len(data):raise ValueError('Invalid TE section header bounds')
        for i in range(count):
            s=40+40*i;vs,va,n,raw=struct.unpack_from('<4I',data,s+8)
            off=raw-stripped+40;flags=struct.unpack_from('<I',data,s+36)[0]
            if off<0 or off+n>len(data):raise ValueError('Invalid TE section bounds')
            if flags&0x20000000:executable.append((off,n,preferred+va))
    else:
        if len(data)<64 or data[:2]!=b'MZ':raise ValueError('Invalid PE image')
        pe=struct.unpack_from('<I',data,60)[0]
        if pe+24>len(data) or data[pe:pe+4]!=b'PE\0\0':raise ValueError('Invalid PE signature')
        machine,count=struct.unpack_from('<HH',data,pe+4);opt=pe+24;opt_size=struct.unpack_from('<H',data,pe+20)[0]
        if opt_size<32 or opt+opt_size+count*40>len(data) or count>64:raise ValueError('Invalid PE header bounds')
        if struct.unpack_from('<H',data,opt)[0]!=0x20b:raise ValueError('Not PE32+')
        entry=struct.unpack_from('<I',data,opt+16)[0];preferred=struct.unpack_from('<Q',data,opt+24)[0]
        executable=[];adjusted=None
        for i in range(count):
            s=opt+opt_size+40*i;vs,va,n,off=struct.unpack_from('<4I',data,s+8);flags=struct.unpack_from('<I',data,s+36)[0]
            if off+n>len(data):raise ValueError('Invalid PE section bounds')
            if flags&0x20000000:executable.append((off,n,preferred+va))
            if va<=entry<va+n:adjusted=off+entry-va
        if adjusted is None:raise ValueError('PE entry outside file-backed sections')
    return {k:v for k,v in record.items() if k!='data'}|{'format':'TE' if kind==0x12 else 'PE32+',
        'machine':hex(machine),'preferred_base':hex(preferred),'entry_rva':hex(entry),
        'entry_file_offset':hex(adjusted),'physical_entry':hex(address+adjusted) if address is not None else None,
        'sha256':hashlib.sha256(data).hexdigest(),'executable_ranges':executable}


def analyze(out):
    out.mkdir(parents=True,exist_ok=True);files={};images={};md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    for name,address in (('xbl_a.img',0x9fc00000),('abl_a.img',0x9fa00000)):
        path=ROOT/'backups/nio-firmware-20260927T163534Z'/name;data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=PINNED[name]:raise ValueError('Requires pinned '+name)
        entry,segments=loads(data);matches=[s for s in segments if s['address']==address]
        if len(matches)!=1:raise ValueError('Unexpected firmware segment')
        seg=matches[0];blob=data[seg['offset']:seg['offset']+seg['size']]
        records=volume(blob,address,skip_compressed=name.startswith('xbl'))
        images[name]=[]
        for i,record in enumerate(r for r in records if 'data' in r):
            info=image_info(record);images[name].append(info)
            path=out/(name+'.'+str(i)+'.bin');path.write_bytes(record['data'])
            info['extracted_path']=str(path.resolve());candidates=[]
            if info['machine']=='0xaa64':
                for off,n,va in info['executable_ranges']:
                    # Aligned executable section sweep: candidate instructions, not CFG proof.
                    for at in range(off,off+n-3,4):
                        ins=next(md.disasm(record['data'][at:at+4],va+at-off),None)
                        if ins and (ins.mnemonic=='eret' or any(reg in ins.op_str for reg in ('currentel','spsr_el2','elr_el2','sctlr_el2'))):
                            candidates.append({'address':hex(ins.address),'mnemonic':ins.mnemonic,'operands':ins.op_str,'file_offset':hex(at)})
            info['transition_instruction_candidates']=candidates
            if name.startswith('xbl') and info['format']=='TE' and info['physical_entry']=='0x9fc0cc50':
                # Fixed windows in this pinned SEC image, not a recovered CFG.
                windows={}
                for label,va,n in (('entry',0x9fc0cc50,160),('startup',0x9fc0cd80,512),
                    ('tlbi',0x9fc17d24,56),('disable-mci',0x9fc17ecc,128),('vbar-hcr',0x9fc182c0,64)):
                    off=va-record['address']
                    if not any(a<=off and off+n<=a+size for a,size,_ in info['executable_ranges']):
                        raise ValueError('SEC window outside executable section')
                    instructions=[{'address':hex(ins.address),'mnemonic':ins.mnemonic,'operands':ins.op_str}
                        for ins in md.disasm(record['data'][off:off+n],va)]
                    path=out/('xbl-sec-'+label+'.txt')
                    path.write_text(''.join(f"{i['address']}: {i['mnemonic']} {i['operands']}\n" for i in instructions))
                    windows[label]={'address':hex(va),'size':n,'path':str(path.resolve()),
                        'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'instructions':instructions}
                info['sec_instruction_windows']=windows
        branch=None
        if name.startswith('xbl'):
            word=struct.unpack_from('<I',blob)[0]
            if word&0xfc000000==0x14000000:
                imm=word&0x3ffffff;imm=imm-(1<<26) if imm&(1<<25) else imm
                branch=hex(address+imm*4)
        files[name]={'sha256':PINNED[name],'elf_entry':hex(entry),'firmware_segment':seg,'fv_entry_branch':branch}
    report={'files':files,'images':images,'tool_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope':'Pinned static ELF/FV/TE/PE inventory and aligned instruction candidates, not a CFG proof or actual XBL/TZ target capture. XBL compressed DXE volume deliberately not expanded.'}
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'reports/qhee-offline/bootchain-static')
    r=analyze(p.parse_args().out)
    for name,records in r['images'].items():
        for record in records:print(name,record['names'],record['format'],record['machine'],record['physical_entry'],len(record['transition_instruction_candidates']))
