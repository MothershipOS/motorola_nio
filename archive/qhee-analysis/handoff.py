"""Finite loaded-code experiments on pinned QHEE; never builds a flash image."""
import hashlib
import struct
from hyp_patch import PATCHES
from smmu_config import PINNED_HYP
from transition import build, START, END, ORIGINAL


def loaded_code(image, experiment=None):
    base, original=image.code_bytes()
    code=bytearray(original)
    changes=[]
    if experiment is not None:
        if experiment not in ('spsr-el2h','el2-diag-mmu-off','el2-xbl-mmu-off','el2-diag-masked-mmu-off','el2-xbl-masked-mmu-off'):raise ValueError('Unknown handoff experiment')
        if hashlib.sha256(image.data).hexdigest()!=PINNED_HYP:raise ValueError('Handoff experiment requires pinned original QHEE')
        address,expected,replacement,description=PATCHES['spsr-el2h']
        offset=address-base
        if struct.unpack_from('<I',code,offset)[0]!=expected:raise ValueError('Unexpected original handoff instruction')
        struct.pack_into('<I',code,offset,replacement)
        changes=[{'address':hex(address),'original':hex(expected),'replacement':hex(replacement),'description':description}]
    transition=None
    if experiment in ('el2-diag-mmu-off','el2-xbl-mmu-off','el2-diag-masked-mmu-off','el2-xbl-masked-mmu-off'):
        if image.code.vaddr!=0x80040000 or image.code.end!=0x8028b000:raise ValueError('Unexpected QHEE transition clean range')
        if original[START-base:END-base]!=ORIGINAL:raise ValueError('Unexpected original terminal register-clearing block')
        variant='xbl-prefix' if 'xbl' in experiment else 'diagnostic'
        if '-masked-' in experiment:variant+='-masked'
        stub,transition=build(variant);code[START-base:END-base]=stub
        changes.append({'address':hex(START),'size':len(stub),'original_sha256':hashlib.sha256(ORIGINAL).hexdigest(),
            'replacement_sha256':hashlib.sha256(stub).hexdigest(),'description':'Diagnostic identity-mapped PoC clean and M/C/I-disable terminal block'})
    metadata={'experiment':experiment,'original_code_sha256':hashlib.sha256(original).hexdigest(),
        'loaded_code_sha256':hashlib.sha256(code).hexdigest(),'changes':changes,
        'scope':'Loaded emulator code copy only; original firmware backup untouched. No image integrity metadata updated or flashable candidate created.'}
    if transition is not None:metadata['terminal_transition']=transition
    return bytes(code),metadata
