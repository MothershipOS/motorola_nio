#!/usr/bin/env python3
"""Build the deterministic RAM-only diagnostic newc ramdisk; never touches a phone.

Contents: a busybox shell init that exposes a USB CDC-ACM root shell, the
static nio-diag helper (KVM probe, reboot-mode restart), and a verified
static ARM64 busybox from the Ubuntu archive.
"""
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BUSYBOX = {
    'package': 'busybox-static 1:1.36.1-6ubuntu3.1 arm64 (Ubuntu noble-updates)',
    'url': 'https://ports.ubuntu.com/ubuntu-ports/pool/main/b/busybox/busybox-static_1.36.1-6ubuntu3.1_arm64.deb',
    'deb_sha256': 'd96535e0402c011e0ee43449799df2f4504d44b842e4f2b3a6cbc845508eaafc',
    'verification': 'deb hash from noble-updates Packages.xz, whose hash is in gpgv-verified InRelease',
}


def static_arm64(path):
    executable = path.read_bytes()
    if executable[:5] != b'\x7fELF\x02' or struct.unpack_from('<H', executable, 18)[0] != 183:
        raise SystemExit(f'{path.name} is not ARM64 ELF64')
    headers = subprocess.check_output(['aarch64-linux-gnu-readelf', '-l', str(path)], text=True)
    if 'INTERP' in headers:
        raise SystemExit(f'{path.name} requires a dynamic loader')
    return executable


def main():
    out = ROOT / 'kernel-work/out/diagnostic'
    out.mkdir(parents=True, exist_ok=True)
    deb = ROOT / 'kernel-work/downloads/busybox' / Path(BUSYBOX['url']).name
    if not deb.exists() or hashlib.sha256(deb.read_bytes()).hexdigest() != BUSYBOX['deb_sha256']:
        raise SystemExit(f'Missing or unverified {deb}; download it from {BUSYBOX["url"]}')
    extracted = out / 'busybox-deb'
    subprocess.run(['dpkg-deb', '-x', str(deb), str(extracted)], check=True)
    busybox = static_arm64(extracted / 'usr/bin/busybox')
    helper_source = ROOT / 'kernel/initramfs/nio-diag.c'
    helper = out / 'nio-diag'
    subprocess.run(['aarch64-linux-gnu-gcc', '-static', '-Os', '-Wall', '-Wextra', '-Werror',
                    '-o', str(helper), str(helper_source)], check=True)
    helper_bytes = static_arm64(helper)
    init_source = ROOT / 'kernel/initramfs/init'
    init = init_source.read_bytes()
    if not init.startswith(b'#!/bin/busybox sh\n'):
        raise SystemExit('init must be a busybox shell script')
    archive = bytearray()
    inode = 0
    def add(name, mode, data=b''):
        nonlocal inode
        inode += 1
        encoded = name.encode() + b'\0'
        fields = [inode, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0]
        archive.extend(b'070701' + ''.join(f'{value:08x}' for value in fields).encode())
        archive.extend(encoded)
        archive.extend(b'\0' * (-len(archive) % 4))
        archive.extend(data)
        archive.extend(b'\0' * (-len(archive) % 4))
    for name in ['bin', 'dev', 'proc', 'sys', 'tmp']:
        add(name, 0o040755)
    add('dev/console', 0o020600)  # patched below: character device 5:1
    add('bin/busybox', 0o100755, busybox)
    add('bin/sh', 0o120777, b'busybox')
    add('bin/nio-diag', 0o100755, helper_bytes)
    add('init', 0o100755, init)
    add('TRAILER!!!', 0)
    archive.extend(b'\0' * (-len(archive) % 512))
    # Give /dev/console its device numbers (rdevmajor/rdevminor fields).
    console = archive.find(b'dev/console\0')
    header = console - 110
    archive[header + 78:header + 94] = b'%08x%08x' % (5, 1)
    (out / 'initramfs.cpio').write_bytes(archive)
    packed = gzip.compress(bytes(archive), mtime=0)
    (out / 'initramfs.cpio.gz').write_bytes(packed)
    metadata = {'artifact':str((out / 'initramfs.cpio.gz').relative_to(ROOT)),
        'sha256':hashlib.sha256(packed).hexdigest(),
        'init_sha256':hashlib.sha256(init).hexdigest(),
        'helper_source_sha256':hashlib.sha256(helper_source.read_bytes()).hexdigest(),
        'busybox':BUSYBOX | {'binary_sha256':hashlib.sha256(busybox).hexdigest()},
        'status':'static ARM64 userspace; boot test pending',
        'behavior':'USB CDC-ACM root shell; KVM probe; reboots to bootloader if no host attaches in 180 s; no persistent mounts'}
    (out / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
