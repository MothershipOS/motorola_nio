#!/usr/bin/env python3
"""Pinned XBL APPSBL configuration candidate, not captured QHEE arguments."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from bootchain import PINNED, loads
from qhee import ROOT


def read(data,segments,address,size):
    if size<0:raise ValueError('Negative XBL read')
    matches=[s for s in segments if s['address']<=address and address+size<=s['address']+s['size']]
    if len(matches)!=1:raise ValueError('XBL read needs one file-backed segment')
    segment=matches[0];offset=segment['offset']+address-segment['address']
    if offset+size>len(data):raise ValueError('XBL read outside file')
    return data[offset:offset+size]


def payload():
    """Original complete FV segment only; configured target is still a hypothesis."""
    path=ROOT/'backups/nio-firmware-20260927T163534Z/xbl_a.img';data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=PINNED['xbl_a.img']:raise ValueError('Requires pinned XBL')
    _,segments=loads(data)
    matches=[s for s in segments if s['address']==0x9fc00000]
    if len(matches)!=1 or (matches[0]['size'],matches[0]['memsz'],matches[0]['flags'])!=(0x300000,0x300000,7):
        raise ValueError('Unexpected XBL FV segment')
    s=matches[0];blob=read(data,segments,s['address'],s['size'])
    contract=inventory()
    if contract['configured_entry_branch']!={'address':'0x9fc00000','word':'0x14003314','target':'0x9fc0cc50'}:
        raise ValueError('Unexpected XBL configured entry')
    return blob,{'firmware_sha256':PINNED['xbl_a.img'],'segment':s,'segment_sha256':hashlib.sha256(blob).hexdigest(),
        'configured_entry_branch':contract['configured_entry_branch'],
        'scope':'Original 3 MiB XBL FV; other XBL segments not loaded. Synthetic QHEE incoming x0=0x9fc00000, x1=2, x2=0; actual secure handoff unmeasured.'}


def inventory():
    path=ROOT/'backups/nio-firmware-20260927T163534Z/xbl_a.img';data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=PINNED['xbl_a.img']:raise ValueError('Requires pinned XBL')
    _,segments=loads(data);rows=[];table=0x14884690;stride=0x88
    for i in range(32):
        address=table+stride*i;row=read(data,segments,address,stride)
        if struct.unpack_from('<I',row)[0]==0:break
        label=struct.unpack_from('<Q',row,0x58)[0]
        name=read(data,segments,label,64).split(b'\0')[0].decode('ascii') if label else None
        rows.append({'index':i,'address':hex(address),'image_id':struct.unpack_from('<I',row,0x10)[0],
            'name':name,'callback':hex(struct.unpack_from('<Q',row,0x48)[0]),
            'configured_address':hex(struct.unpack_from('<Q',row,0x70)[0]),'raw_hex':row.hex(),'sha256':hashlib.sha256(row).hexdigest()})
    else:raise ValueError('No bounded XBL table terminator')
    matches=[r for r in rows if r['name']=='APPSBL']
    if len(matches)!=1:raise ValueError('Unexpected APPSBL table entry')
    target=matches[0];address=int(target['configured_address'],16);word=struct.unpack('<I',read(data,segments,address,4))[0]
    if word&0xfc000000!=0x14000000:raise ValueError('Expected configured entry branch')
    imm=word&0x3ffffff;imm=imm-(1<<26) if imm&(1<<25) else imm
    md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);windows={}
    for label,a,n in (('appsbl-callback',0x14817b14,0xd8),('interface-config-branch',0x14817bec,0x2c),
            ('interface-getter',0x14826f34,0x44),('interface-setter',0x14826ee4,0x50),
            ('interface-initializer',0x14827648,0x84),('interface-slot-target',0x14827850,4),
            ('interface-descriptor-copy',0x148278cc,0x50),('secure-handoff',0x14817908,0x22c),
            ('memcpy',0x148248c4,0x20),('smc-wrapper',0x1482c4e8,0x68)):
        blob=read(data,segments,a,n);ins=[{'address':hex(x.address),'mnemonic':x.mnemonic,'operands':x.op_str} for x in md.disasm(blob,a)]
        if len(ins)*4!=n:raise ValueError('Incomplete XBL callback window')
        windows[label]={'address':hex(a),'size':n,'sha256':hashlib.sha256(blob).hexdigest(),'instructions':ins}
    slot=0x1488b9f0+0x48;slot_target=struct.unpack('<Q',read(data,segments,slot,8))[0]
    if slot_target!=0x14827850:raise ValueError('Unexpected interface configuration slot')
    descriptor=read(data,segments,0x1488bb70,20)
    return {'firmware_sha256':PINNED['xbl_a.img'],'table_base':hex(table),'stride':stride,'rows':rows,
        'terminator_address':hex(table+len(rows)*stride),'appsbl':target,'configured_entry_branch':{'address':hex(address),'word':hex(word),'target':hex(address+4*imm)},
        'windows':windows,'interface_configuration':{'getter_global':'0x148b6270','initialized_object':'0x148b67a0',
            'vtable':'0x1488b9f0','slot_address':hex(slot),'slot_target':hex(slot_target),
            'descriptor_source':'0x1488bb70','descriptor_destination':'0x1488bb48','descriptor_size':20,
            'original_source_hex':descriptor.hex(),'original_source_sha256':hashlib.sha256(descriptor).hexdigest(),
            'scope':'Conditional static dataflow along the successful initializer path; no runtime capture. Slot branches to descriptor memcpy, not a secure transfer.'},
        'later_secure_call':{'caller':'0x14817908','call_site':'0x14817acc','smc_instruction':'0x1482c50c',
            'x0':'0x82000114','x1':'0x22','x2':'0x80716100','x3':'0xe00','x4_x7':'zero',
            'scope':'Conditional static call after copying 0xe00 bytes from input context+0x18 and cache maintenance; pointer/size are fixed, buffer contents and TZ dispatch unmeasured.'},
        'sec_literals':{hex(a):hex(struct.unpack('<Q',read(data,segments,a,8))[0]) for a in (0x9fc0cd68,0x9fc0cd70,0x9fc0cfa0,0x9fc0cfa8)},
        'tool_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope':'Static XBL configuration and bounded instruction windows. 0x9fc00000 is a configured candidate that branches to SEC, not a capture or proof of QHEE incoming x0, width or arguments. The earlier indirect slot configures a descriptor; the later 0x82000114 SMC and TZ-to-QHEE register setup require separate evidence.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'reports/qhee-offline/xbl-target-static')
    out=p.parse_args().out;out.mkdir(parents=True,exist_ok=True);m=inventory()
    for name,w in m['windows'].items():
        (out/(name+'.txt')).write_text(''.join(f"{i['address']}: {i['mnemonic']} {i['operands']}\n" for i in w['instructions']))
    (out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
    print('APPSBL configured candidate',m['appsbl']['configured_address'],'branch',m['configured_entry_branch']['target'])
