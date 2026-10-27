#!/usr/bin/env python3
"""Package the pinned masked EL2/XBL transition; never flashes or activates it.

Repairs the executable SHA-384 hash-table entry, preserving the existing OEM
signature/certificates. That signature is stale, not a valid new signature.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from handoff import loaded_code
from qhee import QheeImage, DEFAULT_IMAGE, ROOT
from smmu_config import PINNED_HYP
from transition import START, END

EXPERIMENT = 'el2-xbl-masked-mmu-off'
HASH_OFFSET = 0x1138


def candidate(image):
    original = image.data
    if hashlib.sha256(original).hexdigest() != PINNED_HYP:
        raise ValueError('Requires pinned original hyp image')
    # Exact MBN v6 container layout: 48-byte header, 120-byte OEM metadata,
    # four SHA-384 entries, 256-byte OEM signature, 6144-byte certificates.
    if struct.unpack_from('<12I', original, 0x1000) != (
            0, 6, 0, 0, 0x19c0, 0xc0, 0xffffffff, 0x100,
            0xffffffff, 0x1800, 0, 0x78):
        raise ValueError('Unexpected pinned MBN header')
    base, old_code = image.code_bytes()
    old_digest = hashlib.sha384(old_code).digest()
    if original[HASH_OFFSET:HASH_OFFSET+48] != old_digest:
        raise ValueError('Original executable hash-table entry mismatch')
    if original[0x10a8:0x10d8] != hashlib.sha384(original[:0x120]).digest():
        raise ValueError('Original ELF/header hash-table entry mismatch')
    code, transition = loaded_code(image, EXPERIMENT)
    new_digest = hashlib.sha384(code).digest()
    result = bytearray(original)
    offset = image.code.file_off
    result[offset:offset+len(code)] = code
    result[HASH_OFFSET:HASH_OFFSET+48] = new_digest
    ranges = [(offset+0x1d8, offset+0x1dc),
              (offset+START-base, offset+END-base),
              (HASH_OFFSET, HASH_OFFSET+48)]
    changed = [i for i, (a,b) in enumerate(zip(original, result)) if a != b]
    if len(result) != len(original) or any(not any(lo <= i < hi for lo,hi in ranges) for i in changed):
        raise ValueError('Changes outside the two instruction ranges and code hash')
    if result[0x1168:0x2a68] != original[0x1168:0x2a68]:
        raise ValueError('OEM signature/certificates unexpectedly changed')
    metadata = {
        'experiment': EXPERIMENT, 'bytes': len(result),
        'original_sha256': hashlib.sha256(original).hexdigest(),
        'candidate_sha256': hashlib.sha256(result).hexdigest(),
        'changed_bytes': len(changed),
        'allowed_file_ranges': [[hex(lo),hex(hi)] for lo,hi in ranges],
        'original_code_sha384': old_digest.hex(), 'candidate_code_sha384': new_digest.hex(),
        'code_hash_offset': hex(HASH_OFFSET),
        'oem_signature': 'PRESERVED BUT STALE: signed hash table changed; not re-signed',
        'authentication_acceptance': 'Unknown; fastboot write acceptance is not early-boot authentication',
        'purpose': 'Experimental CPU0 EL2 handoff to original XBL; not a complete KVM firmware',
        'hardware_boot_validated': False,
        'limitations': [
            'Actual cold entry target and intervening UEFI path remain unmeasured',
            'Physical cache coherency, firmware services, PSCI, other CPUs and KVM ownership unproved',
            'A pre-ABL failure can remove fastboot; independent EDL recovery unverified'],
        'transition': transition,
        'disassembly': [f'{i.address:#x}: {i.mnemonic} {i.op_str}' for i in
                        Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN).disasm(code[START-base:END-base], START)]}
    return bytes(result), metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_IMAGE)
    parser.add_argument('--out', type=Path, required=True, help='New directory; never overwrites')
    args = parser.parse_args()
    if args.out.resolve().is_relative_to((ROOT/'backups').resolve()):
        parser.error('Output may not be under backups')
    image = QheeImage(args.input)
    data, metadata = candidate(image)
    args.out.mkdir(parents=True, exist_ok=False)
    output = args.out/'hyp-el2-xbl-masked.img'
    with output.open('xb') as stream:
        stream.write(data)
    metadata['input'] = str(args.input.resolve())
    metadata['output'] = str(output.resolve())
    metadata['builder_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (args.out/'manifest.json').write_text(json.dumps(metadata, indent=2)+'\n')
    (args.out/'transition.txt').write_text('\n'.join(metadata['disassembly'])+'\n')
    print(json.dumps({k: metadata[k] for k in ('output','bytes','candidate_sha256','changed_bytes','oem_signature')}, indent=2))


if __name__ == '__main__':
    main()
