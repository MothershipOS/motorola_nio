#!/usr/bin/env python3
"""Original TZ boot-record selectors and cold handoff-frame slice, offline only."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from unicorn import Uc, UcError, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_INVALID
from unicorn.arm64_const import UC_ARM64_REG_SP, UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_PC, UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2
from bootchain import loads
from qhee import ROOT
from xbl_target import read, inventory as xbl_inventory

PINNED_TZ='74c85ae47fc470021db7d84eabc16e4089ab17727c677a9c528c051a00d2d7d8'
TABLE=0x1c179c18
FRAME=0x90000000
STACK=0x9000f000
START=0x1c04b710
STOP=0x1c04b7e4
RANGES=((START,STOP),(0x1c04bf4c,0x1c04bfb0),(0x1c04f48c,0x1c04f570),
        (0x1c04f570,0x1c04f60c),(0x1c04f630,0x1c04f6a8))
WINDOWS=(('early-buffer-copy',0x146804f8,0xa4),('early-buffer-getter',0x14684014,0xc),
    ('entry-input-pointers',0x146800d4,0x18),
    ('secure-entry',0x1c04baa8,0x11c),('secure-table-copy',0x1c04f470,0x1c),
    ('cold-init-tail',0x1c05d60c,0x4c),('handoff-frame-tail',0x1c04b6a8,0x180),
    ('boot-target-selection',0x1c04bf4c,0x64),('appsbl-target',0x1c04f48c,0x9c),
    ('record-search',0x1c04f528,0x48),('hyp-target',0x1c04f5c4,0x48),
    ('record-available',0x1c04f630,0x78),('monitor-boot-dispatch',0x1c01d8f4,0x50),
    ('monitor-context-inputs',0x1c01d444,0x138))


def image():
    data=(ROOT/'backups/nio-firmware-20260927T163534Z/tz_a.img').read_bytes()
    if hashlib.sha256(data).hexdigest()!=PINNED_TZ:raise ValueError('Requires pinned TZ')
    _,segments=loads(data)
    return data,segments


def boot_records(hyp=True,apps_width=2,hyp_width=2,version=2,selected_index=0):
    """Synthetic buffer layout inferred from original selectors, never a live capture."""
    if apps_width not in (1,2) or hyp_width not in (1,2):raise ValueError('Only explicit AArch32/AArch64 record widths')
    if version not in (2,3) or selected_index not in (0,1):raise ValueError('Bounded boot-record fixture')
    target=int(xbl_inventory()['appsbl']['configured_address'],16)
    blob=bytearray(0xe00)
    struct.pack_into('<II',blob,8,version,2 if hyp else 1)
    for index,ident,width,entry in ((0,9,apps_width,target),(1,21,hyp_width,0x80040000)):
        if index==1 and not hyp:continue
        struct.pack_into('<IIQ',blob,0x18+0x110*index,ident,width,entry)
    struct.pack_into('<I',blob,0xdf8,selected_index)
    return bytes(blob)


def inventory():
    data,segments=image();md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);windows={}
    for name,a,size in WINDOWS:
        blob=read(data,segments,a,size)
        instructions=[{'address':hex(i.address),'mnemonic':i.mnemonic,'operands':i.op_str} for i in md.disasm(blob,a)]
        if len(instructions)*4!=size:raise ValueError('Incomplete TZ instruction window: '+name)
        windows[name]={'address':hex(a),'size':size,'sha256':hashlib.sha256(blob).hexdigest(),'instructions':instructions}
    return {'firmware_sha256':PINNED_TZ,'windows':windows,
        'buffer_chain':{'entry_pointer_global':hex(struct.unpack('<Q',read(data,segments,0x14680220,8))[0]),'early_table':'0x1c02c008','secure_table':hex(TABLE),'size':'0xe00','version_offset':'0x8','count_offset':'0xc',
            'records_offset':'0x18','record_stride':'0x110','id_offset':'0x0','width_offset':'0x4','entry_offset':'0x8','selected_index_offset':'0xdf8'},
        'monitor_boot_subdispatch':{'command':1,'selector':'0x81','first_table':'0x1c021af0','first_target':hex(0x1c01d674+4*struct.unpack('<H',read(data,segments,0x1c021af0,2))[0]),
            'second_table':'0x1c021b7e','second_target':hex(0x1c01d924+4*struct.unpack('<H',read(data,segments,0x1c021b7e,2))[0])},
        'scope':'Pinned static dataflow and boot-record layout. Early buffer population from the XBL SMC remains untraced; secure initializer and full monitor restore/ERET path are not executed here.'}


def argument_copy(data,segments,frame_bytes):
    """Second independent fixture: first four context stores before system-register setup."""
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for base,size in ((0x1c01d000,0x2000),(0x1c028000,0x1000)):
        uc.mem_map(base,size);uc.mem_write(base,read(data,segments,base,size))
    uc.mem_map(FRAME,0x10000);uc.mem_write(FRAME,frame_bytes)
    uc.reg_write(UC_ARM64_REG_SP,STACK);uc.reg_write(UC_ARM64_REG_X0,FRAME+0x200)
    uc.reg_write(UC_ARM64_REG_X1,FRAME+0x400);uc.reg_write(UC_ARM64_REG_X2,FRAME)
    pcs=[];writes=[];stopped=False
    def code(u,pc,size,_):
        nonlocal stopped
        if pc==0x1c01d4a4:stopped=True;u.emu_stop();return
        if not (0x1c01d444<=pc<0x1c01d4a4 or 0x1c01e434<=pc<0x1c01e440):raise RuntimeError('Unexpected monitor argument-copy instruction')
        pcs.append(hex(pc))
    def write(u,access,address,size,value,_):
        if not ((FRAME+0x200<=address and address+size<=FRAME+0x220) or (FRAME+0xb000<=address and address+size<=FRAME+0x10000)):
            raise RuntimeError('Unexpected monitor argument-copy write')
        writes.append({'address':hex(address),'size':size,'value':hex(value&((1<<(8*size))-1))})
    uc.hook_add(UC_HOOK_CODE,code);uc.hook_add(UC_HOOK_MEM_WRITE,write)
    uc.emu_start(0x1c01d444,0x1c01d4a8,count=200)
    if not stopped:raise RuntimeError('Monitor argument copy failed to reach bounded stop')
    return {'start':'0x1c01d444','stop':'0x1c01d4a4','context_address':hex(FRAME+0x200),
        'x0_x3':[hex(v) for v in struct.unpack('<4Q',bytes(uc.mem_read(FRAME+0x200,32)))],
        'pcs':pcs,'writes':writes,'scope':'Separate original-instruction fixture seeded with the emitted frame. Stops before ELR/HCR/SPSR/SCR/context-stack handling; no monitor ERET.'}


def run(hyp=True,apps_width=2,hyp_width=2,version=2,selected_index=0,records=None):
    data,segments=image();blob=boot_records(hyp,apps_width,hyp_width,version,selected_index) if records is None else records
    if len(blob)!=0xe00:raise ValueError('Boot-record fixture must be exactly 0xe00 bytes')
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    # Map only original code pages used by this finite slice, with original backing.
    for base,size in ((0x1c04b000,0x5000),(0x1c178000,0x4000)):
        uc.mem_map(base,size);uc.mem_write(base,read(data,segments,base,size))
    uc.mem_map(FRAME,0x10000)
    uc.mem_write(TABLE,blob)
    uc.mem_write(0x1c1788c0,struct.pack('<Q',FRAME))
    uc.reg_write(UC_ARM64_REG_SP,STACK);uc.reg_write(UC_ARM64_REG_X19,0);uc.reg_write(UC_ARM64_REG_X20,0x1c1788c0)
    pcs=[];writes=[];stopped=False
    def instruction(u,pc,size,_):
        nonlocal stopped
        if pc==STOP:stopped=True;u.emu_stop();return
        if not any(a<=pc<b for a,b in RANGES):raise RuntimeError('Unmodeled TZ instruction '+hex(pc))
        pcs.append(hex(pc))
    def write(u,access,address,size,value,_):
        if not ((FRAME<=address and address+size<=FRAME+0x70) or
                (FRAME+0xb000<=address and address+size<=FRAME+0x10000) or
                (0x1c178984<=address and address+size<=0x1c17898c)):
            raise RuntimeError('Unexpected TZ slice write '+hex(address))
        writes.append({'address':hex(address),'size':size,'value':hex(value&((1<<(8*size))-1))})
    uc.hook_add(UC_HOOK_CODE,instruction);uc.hook_add(UC_HOOK_MEM_WRITE,write)
    def invalid(u,access,address,size,value,_):
        raise RuntimeError(f'Unmapped TZ slice access {address:#x}/{size} at PC {u.reg_read(UC_ARM64_REG_PC):#x}')
    uc.hook_add(UC_HOOK_MEM_INVALID,invalid)
    try:uc.emu_start(START,STOP+4,count=2000)
    except UcError as error:raise RuntimeError(f'TZ slice stopped at {uc.reg_read(UC_ARM64_REG_PC):#x}: {error}; last PCs {pcs[-6:]}') from error
    if not stopped:raise RuntimeError('TZ slice did not reach bounded stop within 2000 instructions')
    frame_bytes=bytes(uc.mem_read(FRAME,0x70));frame=list(struct.unpack('<14Q',frame_bytes))
    return {'firmware_sha256':PINNED_TZ,'synthetic_inputs':{'hyp_present':hyp,'apps_width':apps_width,'hyp_width':hyp_width,'version':version,'selected_index':selected_index,
        'boot_records_hex':blob.hex(),'boot_records_sha256':hashlib.sha256(blob).hexdigest(),'cpu_index':0,'frame':hex(FRAME),'stack':hex(STACK),'x20_per_cpu_pointer_table':'0x1c1788c0'},
        'start':hex(START),'stop':hex(STOP),'executed_instructions':len(pcs),'pcs':pcs,'writes':writes,'frame':[hex(v) for v in frame],
        'selected':{'next_x0':hex(frame[2]),'next_x1':hex(frame[3]),'next_x2':hex(frame[4]),'next_x3':hex(frame[5]),
            'next_pc':hex(frame[7]),'hcr_rw_selector':hex(frame[8]),'spsr':hex(frame[9]),'scr':hex(frame[10])},
        'monitor_argument_copy':argument_copy(data,segments,frame_bytes),
        'tool_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope':'Unchanged original TZ target selectors and frame-building instructions, with synthetic boot records, CPU0, frame pointer and stack. No instruction replacement or in-flight register/memory edits. Stops before stack/context helper 0x1c1195f4; no full TZ startup, physical handoff, monitor ERET or KVM execution.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'reports/qhee-offline/tz-handoff-static')
    out=p.parse_args().out;out.mkdir(parents=True,exist_ok=True);m=inventory()
    for name,w in m['windows'].items():(out/(name+'.txt')).write_text(''.join(f"{i['address']}: {i['mnemonic']} {i['operands']}\n" for i in w['instructions']))
    (out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
    for hyp in (False,True):(out/('qhee-present.json' if hyp else 'qhee-absent.json')).write_text(json.dumps(run(hyp),indent=2)+'\n')
    print('Original TZ selectors and frame slice recorded; synthetic records only')


if __name__=='__main__':main()
