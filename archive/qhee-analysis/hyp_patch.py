#!/usr/bin/env python3
"""Create an OFFLINE-ONLY QHEE instruction experiment; never flashes a phone.

The AArch64 return at 0x80040328 uses SPSR_EL2=0x85. The named change selects
0x3c9 (EL2h, DAIF masked). It does not implement a valid Linux EL2 handoff:
MMU/cache teardown, firmware ownership, PSCI and payload identity are unresolved.
QHEE enables SCTLR_EL2.M/C conditionally, depending on its saved TTBR state.

This changes only code, leaving embedded hashes and signatures stale. Engineering
or secure=no bootloader status does not prove XBL will accept the result.
See kernel/EL2-offline-results.md (archived: backups/stale-docs-20261008.tar.gz). Output is an exclusive-create analysis copy.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qhee import QheeImage, DEFAULT_IMAGE, ROOT  # noqa: E402

MD = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)


def movz_x5(imm16: int) -> int:
    return 0xD2800000 | ((imm16 & 0xffff) << 5) | 5


# Named patches. Each: vaddr -> (expected_original_u32, new_u32, description).
PATCHES = {
    'spsr-el2h': (0x800401d8, movz_x5(0x85), movz_x5(0x3c9),
                  'AArch64 return SPSR_EL2 EL1h(0x85) -> EL2h(0x3c9)'),
    # 'sctlr-off' is intentionally NOT preset: the safe way to enter MMU-off is
    # still being determined (clear SCTLR_EL2.M/C at 0x800400e8, or add a stub
    # that disables it right before the 0x80040328 eret). See STATUS/analysis.
}


def decode(u32: int) -> str:
    ins = next(MD.disasm(struct.pack('<I', u32), 0), None)
    return f'{ins.mnemonic} {ins.op_str}' if ins else '<data>'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--image', type=Path, default=DEFAULT_IMAGE)
    parser.add_argument('--out', type=Path, help='write patched image here (omit for dry-run)')
    parser.add_argument('--apply', nargs='+', choices=sorted(PATCHES), default=['spsr-el2h'])
    args = parser.parse_args()
    image = QheeImage(args.image)
    seg = image.code
    if args.out:
        target = args.out.resolve()
        if target == image.path.resolve() or target.is_relative_to((ROOT / 'backups').resolve()):
            raise SystemExit('refusing to overwrite an input or write inside backups')
        if args.out.exists() or args.out.is_symlink():
            raise SystemExit('output already exists; choose a new analysis-copy path')
    data = bytearray(image.data)
    print(f'{image.path.name}: entry {image.entry:#x}\n')
    for name in args.apply:
        vaddr, expect, new, desc = PATCHES[name]
        foff = seg.file_off + (vaddr - seg.vaddr)
        original = struct.unpack_from('<I', data, foff)[0]
        if original != expect:
            raise SystemExit(f'{name}: {vaddr:#x} is {original:#010x} ({decode(original)}), '
                             f'expected {expect:#010x} — image differs, aborting')
        struct.pack_into('<I', data, foff, new)
        print(f'[{name}] {desc}')
        print(f'   {vaddr:#010x}: {original:#010x} {decode(original):<20} -> {new:#010x} {decode(new)}')
    old_digest = hashlib.sha384(image.code_bytes()[1]).digest()
    digest_offset = image.data.find(old_digest)
    integrity = {'code_sha384': old_digest.hex(),
                 'embedded_digest_offset': hex(digest_offset) if digest_offset >= 0 else None,
                 'metadata_updated': False, 'flash_ready': False}
    print('\nOFFLINE ONLY: embedded hashes/signatures are not updated; NOT flash-ready.')
    print('Integrity evidence: ' + json.dumps(integrity))
    if not args.out:
        print('\nDry run (no --out): nothing written.')
        return
    if len(data) != len(image.data):
        raise SystemExit('size changed — refusing to write')
    with args.out.open('xb') as output:
        output.write(data)
    changed = sum(a != b for a, b in zip(data, image.data))
    print(f'\nwrote {args.out} ({changed} bytes changed)')
    print(f'  original sha256 {hashlib.sha256(image.data).hexdigest()}')
    print(f'  patched  sha256 {hashlib.sha256(bytes(data)).hexdigest()}')
    print('  Analysis copy only. Firmware acceptance and recovery are unverified.')


if __name__ == '__main__':
    main()
