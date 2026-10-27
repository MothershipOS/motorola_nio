#!/usr/bin/env python3
"""Finite QHEE entry-state controls derived from isolated original TZ execution."""
import hashlib
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from tz_handoff import image, run as handoff, PINNED_TZ
from xbl_target import read

NAMES=('synthetic-masked','tz-frame-hcr-zero','tz-frame-hcr-rw')


def model(name='synthetic-masked',target=0x90000000):
    if name not in NAMES:raise ValueError('Unknown entry-state model')
    if target not in (0x40400000,0x90000000,0x9fc00000):raise ValueError('Unsupported entry-state payload')
    controls={'SCR_EL3':'0x501','SPSR_EL3':'0x3c9','SCTLR_EL2':'0x30c50830','HCR_EL2':'0x80000000'}
    derived=None
    if name!='synthetic-masked':
        data,segments=image();md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);guards={}
        for pc,expected in ((0x14680614,('msr','sctlr_el2, xzr')),
                            (0x1c01ded8,('orr','w9, w9, #1')),
                            (0x1c01d4f8,('cbz','x22, #0x1c01d518'))):
            blob=read(data,segments,pc,4);ins=list(md.disasm(blob,pc))
            if len(ins)!=1 or (ins[0].mnemonic,ins[0].op_str)!=expected:raise ValueError('Unexpected original entry-state instruction')
            guards[hex(pc)]={'bytes':blob.hex(),'mnemonic':expected[0],'operands':expected[1]}
        frame=handoff();selected=frame['selected']
        if selected['spsr']!='0x89' or selected['scr']!='0x504' or selected['hcr_rw_selector']!='0x0':
            raise ValueError('Unexpected original TZ frame controls')
        controls={'SCR_EL3':hex(int(selected['scr'],16)|1),'SPSR_EL3':selected['spsr'],
                  'SCTLR_EL2':'0x0','HCR_EL2':'0x0' if name.endswith('zero') else '0x80000000'}
        derived={'firmware_sha256':PINNED_TZ,'original_instruction_guards':guards,
                 'frame_controls':selected,'synthetic_records_sha256':frame['synthetic_inputs']['boot_records_sha256'],
                 'scope':'Controls derived from the original monitor restore/ERET fixtures for constructed AArch64 records. This runner seeds them; it does not execute TZ or measure the phone bootstrap.'}
    return {'name':name,'controls':controls,'arguments':{'x0':hex(target),'x1':'0x2','x2':'0x0','x3':'0x0'},
            'derived':derived,'diagnostic_target_override':name!='synthetic-masked' and target!=0x9fc00000,
            'scope':'Explicit offline CPU entry-state variation. EL2 stack, CPU model, timer controls, other registers and secure-service replies remain synthetic assumptions.',
            'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def defines(metadata):
    if metadata['name']=='synthetic-masked':return []
    return ['-DENTRY_STATE_DERIVED']+[f'-DENTRY_STATE_{reg}={value}' for reg,value in metadata['controls'].items()]
