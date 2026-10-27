#!/usr/bin/env python3
"""Pinned SEC stack-sizing dispatcher through its first SMC; no reply model."""
import hashlib
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from xbl_target import payload

STOP = 0x9fc284dc
POINTS = {0x9fc21ce8: 'stack-sizing-entry', 0x9fc21c6c: 'stack-nibble-entry',
          0x9fc21c84: 'stack-cache-read', 0x9fc2849c: 'stack-source-entry',
          0x9fc284b4: 'stack-source-dispatch', 0x9fc284d0: 'stack-query-entry',
          STOP: 'stack-before-availability-smc'}


def contract():
    blob, metadata = payload()
    def read(a, n): return blob[a-0x9fc00000:a-0x9fc00000+n]
    literals = {a: struct.unpack('<Q', read(a, 8))[0] for a in
                (0x9fc28560, 0x9fc28568, 0x9fc28570, 0x9fc28578)}
    table = list(struct.unpack('<3Q', read(0x9fc284b8, 24)))
    if list(literals.values()) != [0x9fc356c8, 0x02000601, 0x02000602, 0x9fc356c8] or table != [0x9fc284d0, 0x9fc283f0, 0x9fc28444]:
        raise ValueError('Unexpected XBL stack-source contract')
    if read(STOP, 4) != bytes.fromhex('030000d4'):
        raise ValueError('Expected original stack-source SMC')
    windows = {}
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    for name, a, n in (('stack-sizing', 0x9fc21ce8, 0x28),
                       ('stack-nibble', 0x9fc21c6c, 0x7c),
                       ('dispatcher', 0x9fc2849c, 0x1c),
                       ('availability', 0x9fc284d0, 0x3c),
                       ('legacy-buffer', 0x9fc283f0, 0x54),
                       ('arm-smc-buffer', 0x9fc28444, 0x58)):
        code = read(a, n)
        instructions = [{'address': hex(i.address), 'mnemonic': i.mnemonic,
                         'operands': i.op_str} for i in md.disasm(code, a)]
        if len(instructions)*4 != n: raise ValueError('Incomplete XBL stack window')
        windows[name] = {'address': hex(a), 'size': n,
                         'sha256': hashlib.sha256(code).hexdigest(),
                         'instructions': instructions}
    return {'firmware_sha256': metadata['firmware_sha256'],
            'fv_sha256': metadata['segment_sha256'], 'stop_before': hex(STOP),
            'windows': windows, 'literals': {hex(a): hex(v) for a, v in literals.items()},
            'table_address': '0x9fc284b8', 'table': [hex(v) for v in table],
            'globals': {hex(a): hex(struct.unpack('<Q', read(a, 8))[0]) for a in (0x9fc3d710, 0x9fc356c8)},
            'expected_sp': '0x9ffcffb0', 'temporary_stack_top': '0x9ffd0000',
            'request_prefix': ['0x2000601', '0x1', '0x2000602'],
            'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope': 'Original stack prologue, empty nibble cache and zero-selector dispatch to first availability SMC. Stops before the SMC unless one architectural routing step is requested. No response, entropy, stack-sizing result or subsequent firmware execution modeled.'}

BUFFER_STOP=0x9fc28468
BUFFER_POINTS={0x9fc284e0:'stack-query-return',0x9fc28444:'stack-new-buffer-path',
               0x9fc28458:'stack-buffer-clean-return',BUFFER_STOP:'stack-before-buffer-smc'}


def buffer_contract():
    blob,m=payload()
    values=[struct.unpack_from('<Q',blob,a-0x9fc00000)[0] for a in (0x9fc28538,0x9fc28540,0x9fc28548)]
    if values!=[0x9fc356c0,0x02000a01,0x9fc356c0] or blob[BUFFER_STOP-0x9fc00000:BUFFER_STOP-0x9fc00000+4]!=bytes.fromhex('030000d4'):
        raise ValueError('Unexpected original XBL buffer query contract')
    return {'firmware_sha256':m['firmware_sha256'],'stop_before':hex(BUFFER_STOP),
            'request_prefix':['0x2000a01','0x22','0x9fc356c0','0x8'],'buffer_address':'0x9fc356c0',
            'selector_address':'0x9fc356c8','selected_offset':'0x10',
            'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope':'Original XBL after exact modeled availability reply through modern eight-byte buffer call; original selector store, buffer zeroing and cache helper. Stops before buffer SMC; no entropy, buffer reply, stack-sizing completion or physical TZ acceptance.'}

RETURN_STOP=0x9fc0cf38
RETURN_POINTS={0x9fc2846c:'stack-buffer-return',0x9fc28484:'stack-buffer-invalidate-return',
 0x9fc28494:'stack-buffer-source-ready',0x9fc21ca4:'stack-source-return',
 0x9fc21cc0:'stack-nibble-cache-published',0x9fc21ce0:'stack-nibble-consumed',
 0x9fc21d00:'stack-sizing-nibble-return',0x9fc21d08:'stack-size-computed',
 0x9fc0cf2c:'stack-sizing-return',RETURN_STOP:'sec-adjusted-stack-before-next-call'}


def return_contract(word):
    blob,m=payload();base=struct.unpack_from('<Q',blob,0x9fc0cd68-0x9fc00000)[0]
    if base!=0x9ff90000 or blob[RETURN_STOP-0x9fc00000:RETURN_STOP-0x9fc00000+4]!=bytes.fromhex('162b0094'):
        raise ValueError('Unexpected original SEC stack adjustment/next call')
    nibble=word&15;size=0x40000-(nibble<<6)
    return {'firmware_sha256':m['firmware_sha256'],'stop_before':hex(RETURN_STOP),
      'fixture_word':hex(word),'consumed_nibble':hex(nibble),'shifted_cache':hex(word>>4),
      'original_workspace_size':'0x40000','stack_size':hex(size),'stack_base':hex(base),'adjusted_sp':hex(base+size),
      'next_call_target':'0x9fc17b90','source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'scope':'Original XBL buffer return/cache helper, nibble publication/consumption, stack-sizing return and SEC SP adjustment. Stops before next helper call; finite fixture is not entropy, physical cache/coherency and full platform/UEFI/ABL/Linux entry unverified.'}
