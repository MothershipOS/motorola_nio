"""Loader for the nio QHEE (hyp) image.

QHEE ships as a Qualcomm ELF: a 0x120-byte MBN metadata header, a hash/cert
segment, and one RWE LOAD segment (code+data at 0x80040000, with BSS past
filesz). This maps the loadable segments into a flat address space for static
analysis (capstone) and dynamic emulation (unicorn).
"""
from __future__ import annotations
import struct
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IMAGE = ROOT / 'backups/nio-firmware-20260927T163534Z/hyp_a.img'


@dataclass
class Segment:
    file_off: int
    vaddr: int
    filesz: int
    memsz: int
    flags: int  # PF_X=1, PF_W=2, PF_R=4

    @property
    def executable(self) -> bool:
        return bool(self.flags & 1)

    @property
    def end(self) -> int:
        return self.vaddr + self.memsz


class QheeImage:
    def __init__(self, path: Path = DEFAULT_IMAGE):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        if len(self.data) < 64 or self.data[5] != 1 or self.data[:4] != b'\x7fELF' or self.data[4] != 2:
            raise ValueError(f'{self.path} is not an ELF64')
        if struct.unpack_from('<H', self.data, 18)[0] != 183:
            raise ValueError('ELF is not AArch64')
        self.entry = struct.unpack_from('<Q', self.data, 24)[0]
        phoff = struct.unpack_from('<Q', self.data, 32)[0]
        phentsize = struct.unpack_from('<H', self.data, 54)[0]
        phnum = struct.unpack_from('<H', self.data, 56)[0]
        if phentsize < 56 or phoff + phentsize * phnum > len(self.data):
            raise ValueError('invalid program-header table bounds')
        self.segments: list[Segment] = []
        for i in range(phnum):
            base = phoff + i * phentsize
            p_type, p_flags = struct.unpack_from('<II', self.data, base)
            p_off, p_vaddr, _p_paddr, p_filesz, p_memsz = struct.unpack_from('<QQQQQ', self.data, base + 8)
            if p_off + p_filesz > len(self.data):
                raise ValueError('segment outside input file')
            if p_type == 1 and p_memsz < p_filesz:
                raise ValueError('PT_LOAD filesz exceeds memsz')
            if p_type == 1 and p_memsz:  # PT_LOAD with content
                self.segments.append(Segment(p_off, p_vaddr, p_filesz, p_memsz, p_flags))
        self.segments.sort(key=lambda s: s.vaddr)

    @property
    def code(self) -> Segment:
        return max((s for s in self.segments if s.executable), key=lambda s: s.memsz)

    def read(self, vaddr: int, size: int) -> bytes:
        if size < 0:
            raise ValueError('negative read size')
        for seg in self.segments:
            if seg.vaddr <= vaddr < seg.end and vaddr + size <= seg.end:
                offset = vaddr - seg.vaddr
                out = bytearray(size)
                have = min(size, max(0, seg.filesz - offset))
                if have:
                    out[:have] = self.data[seg.file_off + offset:seg.file_off + offset + have]
                return bytes(out)  # bytes past filesz stay zero (BSS)
        raise ValueError(f'address {vaddr:#x} not mapped')

    def code_bytes(self) -> tuple[int, bytes]:
        seg = self.code
        return seg.vaddr, self.data[seg.file_off:seg.file_off + seg.filesz]


if __name__ == '__main__':
    import sys
    img = QheeImage(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IMAGE)
    print(f'{img.path.name}: entry {img.entry:#x}')
    for seg in img.segments:
        flags = ''.join(c for c, b in zip('RWX', (seg.flags & 4, seg.flags & 2, seg.flags & 1)) if b)
        print(f'  vaddr {seg.vaddr:#012x} filesz {seg.filesz:#x} memsz {seg.memsz:#x} [{flags}]')
