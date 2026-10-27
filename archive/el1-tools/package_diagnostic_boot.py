#!/usr/bin/env python3
"""Package a self-contained header-v2 fastboot test image; never flashes a phone."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    inputs = {}
    for key, folder in [('kernel', 'lts'), ('dtb', 'nio-dtb-diagnostic'), ('ramdisk', 'diagnostic')]:
        directory = ROOT / 'kernel-work/out' / folder
        manifest = json.loads((directory / ('build-manifest.json' if key == 'kernel' else 'manifest.json')).read_text())
        path = ROOT / manifest['artifact']
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['sha256']:
            raise SystemExit('Artifact hash mismatch: ' + key)
        inputs[key] = {'path':str(path.relative_to(ROOT)), 'sha256':manifest['sha256']}
    output = ROOT / 'kernel-work/out/diagnostic/boot-v2.img'
    metadata_path = output.with_suffix('.json')
    metadata_path.unlink(missing_ok=True)
    tool = ROOT / 'kernel-work/tools/mkbootimg.py'
    provenance = json.loads((tool.parent / 'mkbootimg-provenance.json').read_text())
    for name, record in provenance['files'].items():
        if hashlib.sha256((tool.parent / name).read_bytes()).hexdigest() != record['sha256']:
            raise SystemExit('Packaging tool hash mismatch: ' + name)
    # Must stay empty: Motorola MBM budgets its command-line buffer from the v3
    # header cmdline offset, so any v2 header cmdline trips a SafeString assert.
    # Kernel parameters come from the diagnostic DTB's /chosen/bootargs instead.
    cmdline = ''
    argv = ['python3', str(tool), '--header_version', '2', '--pagesize', '4096',
            '--base', '0', '--kernel_offset', '0x8000', '--ramdisk_offset', '0x1000000',
            '--tags_offset', '0x100', '--dtb_offset', '0x1f00000',
            '--output', str(output)]
    for key in ['kernel', 'ramdisk', 'dtb']:
        argv += ['--' + key, str(ROOT / inputs[key]['path'])]
    subprocess.run(argv, check=True)
    data = output.read_bytes()
    if data[:8] != b'ANDROID!' or struct.unpack_from('<I', data, 40)[0] != 2:
        raise SystemExit('Invalid boot image header')
    page = struct.unpack_from('<I', data, 36)[0]
    kernel_size = struct.unpack_from('<I', data, 8)[0]
    ramdisk_size = struct.unpack_from('<I', data, 16)[0]
    dtb_size = struct.unpack_from('<I', data, 1648)[0]
    align = lambda value: (value + page - 1) // page * page
    offset = page
    for key, size in [('kernel', kernel_size), ('ramdisk', ramdisk_size), ('dtb', dtb_size)]:
        if hashlib.sha256(data[offset:offset+size]).hexdigest() != inputs[key]['sha256']:
            raise SystemExit('Embedded payload mismatch: ' + key)
        offset += align(size)
    if offset != len(data):
        raise SystemExit('Unexpected trailing image content')
    metadata = {'artifact':str(output.relative_to(ROOT)), 'sha256':hashlib.sha256(data).hexdigest(),
                'bytes':len(data), 'header_version':2, 'inputs':inputs, 'cmdline':cmdline,
                'packager':provenance,
                'scope':'RAM-only fastboot boot experiment; legacy header acceptance and DT handoff unverified',
                'reason':'v2 carries our own DTB in one image; v3 requires a separate vendor_boot DTB',
                'limits':'Logs: simple-framebuffer console, USB CDC-ACM shell, best-effort ramoops; DTB carries a sink for the stock ABL dtbo overlay'}
    metadata_path.write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
