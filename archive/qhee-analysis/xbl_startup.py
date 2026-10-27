#!/usr/bin/env python3
"""Finite original SEC workspace contract; synthetic RAM is not a phone capture."""
import hashlib
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from xbl_target import payload

STOP = 0x9fc0cf28
POINTS = {0x9fc0ceb8: 'sec-mpidr-read', 0x9fc0cee4: 'sec-vectors-filled', 0x9fc0cf00: 'sec-before-simd-zero',
          0x9fc0cf20: 'sec-bss-cleared', STOP: 'sec-temporary-stack-ready'}
RANGES = ((0x9ff8c000, 0x800, 'vectors'), (0x9ff90000, 0x40000, 'bss'))
GUARD = 16


def contract():
    blob, metadata = payload()
    def read(a, n): return blob[a-0x9fc00000:a-0x9fc00000+n]
    literals = {a: struct.unpack('<Q', read(a, 8))[0] for a in
                (0x9fc0cd68, 0x9fc0cd70, 0x9fc0cfa0, 0x9fc0cfa8, 0x9fc0cf58)}
    if list(literals.values()) != [0x9ff90000, 0x40000, 0x9ff8c000,
                                  0x9fc0cd60, 0xaa0403f314000000]:
        raise ValueError('Unexpected SEC workspace literals')
    windows = {}
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    for name, a, n in (('workspace', 0x9fc0ceb4, 0x78),
                       ('stack-sizing', 0x9fc21ce8, 0x28),
                       ('stack-nibble', 0x9fc21c6c, 0x7c),
                       ('indirect-source', 0x9fc2849c, 0x1c)):
        code = read(a, n)
        instructions = [{'address': hex(i.address), 'mnemonic': i.mnemonic,
                         'operands': i.op_str} for i in md.disasm(code, a)]
        if len(instructions)*4 != n: raise ValueError('Incomplete SEC workspace window')
        windows[name] = {'address': hex(a), 'size': n,
                         'sha256': hashlib.sha256(code).hexdigest(),
                         'instructions': instructions}
    return {'firmware_sha256': metadata['firmware_sha256'],
            'fv_sha256': metadata['segment_sha256'], 'stop_before': hex(STOP),
            'windows': windows, 'literals': {hex(a): hex(v) for a, v in literals.items()},
            'ranges': [{'address': hex(a), 'size': n, 'name': name} for a, n, name in RANGES],
            'vector_word': hex(literals[0x9fc0cf58]), 'timestamp_address': '0x9fc0cd60',
            'temporary_sp': '0x9ffd0000', 'next_call': '0x9fc21ce8',
            'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope': 'Original CPU0 vector/BSS/temporary-stack setup through 0x9fc0cf28, before stack-sizing call. QEMU virt RAM only; no SEC instruction replacement, platform service, full UEFI or physical RAM/coherency evidence.'}


def sentinel():
    """Two bounded loader images, including guards outside the original writes."""
    return [(a-GUARD, bytes([0xa5])*(n+2*GUARD), name) for a, n, name in RANGES]


def sentinel_metadata():
    return {'byte': '0xa5', 'guard_size': GUARD,
            'regions': [{'address': hex(a), 'size': len(b), 'name': name,
                         'sha256': hashlib.sha256(b).hexdigest()} for a, b, name in sentinel()],
            'scope': 'Synthetic pre-execution QEMU RAM sentinel; original SEC must overwrite vectors/BSS. Guards test bounded writes; not firmware bytes or captured hardware contents.'}
