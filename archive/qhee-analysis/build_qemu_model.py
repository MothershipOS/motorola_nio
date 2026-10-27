#!/usr/bin/env python3
"""Build project-local upstream QEMU with optional nio diagnostic devices."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

from qhee import ROOT

VERSION = '8.2.2'
ARCHIVE_SHA256 = '847346c1b82c1a54b2c38f6edbd85549edeb17430b7d4d3da12620e2962bc4f3'
URL = f'https://download.qemu.org/qemu-{VERSION}.tar.xz'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 64:
        parser.error('--jobs must be 1..64')
    base = ROOT / 'kernel-work/emulation'
    base.mkdir(parents=True, exist_ok=True)
    archive = base / f'qemu-{VERSION}.tar.xz'
    if not archive.exists():
        partial = archive.with_suffix('.partial')
        urllib.request.urlretrieve(URL, partial)
        if sha(partial) != ARCHIVE_SHA256:
            raise SystemExit('archive SHA-256 mismatch')
        partial.rename(archive)
    if sha(archive) != ARCHIVE_SHA256:
        raise SystemExit('archive SHA-256 mismatch')
    src = base / f'qemu-{VERSION}'
    if not src.exists():
        with tarfile.open(archive) as tar:
            tar.extractall(base, filter='data')
    devices = [Path(__file__).resolve().parent / ('emulator/'+name)
               for name in ('nio-soc-version.c','nio-smem.c','nio-gcc-mmu.c','nio-qfprom.c','nio-cmd-db-pointer.c','nio-tz-log-pointer.c','nio-pmic-arb.c','nio-tz-fixture-ram.c')]
    for device in devices:
        shutil.copyfile(device, src / 'hw/arm' / device.name)
    meson = src / 'hw/arm/meson.build'
    original = "arm_ss.add(when: 'CONFIG_ARM_VIRT', if_true: files('virt.c'))"
    previous = "arm_ss.add(when: 'CONFIG_ARM_VIRT', if_true: files('virt.c', 'nio-soc-version.c'))"
    previous_smem = "arm_ss.add(when: 'CONFIG_ARM_VIRT', if_true: files('virt.c', 'nio-soc-version.c', 'nio-smem.c'))"
    previous_gcc = "arm_ss.add(when: 'CONFIG_ARM_VIRT', if_true: files('virt.c', 'nio-soc-version.c', 'nio-smem.c', 'nio-gcc-mmu.c'))"
    previous_qfprom = previous_gcc.replace("'nio-gcc-mmu.c'", "'nio-gcc-mmu.c', 'nio-qfprom.c'")
    previous_cmd_db = previous_qfprom.replace("'nio-qfprom.c'", "'nio-qfprom.c', 'nio-cmd-db-pointer.c'")
    previous_tz_log = previous_cmd_db.replace("'nio-cmd-db-pointer.c'", "'nio-cmd-db-pointer.c', 'nio-tz-log-pointer.c'")
    patched = previous_tz_log.replace("'nio-tz-log-pointer.c'", "'nio-tz-log-pointer.c', 'nio-pmic-arb.c'")
    previous_pmic = patched
    patched = previous_pmic.replace("'nio-pmic-arb.c'", "'nio-pmic-arb.c', 'nio-tz-fixture-ram.c'")
    contents = meson.read_text()
    if not any(line in contents for line in (original,previous,previous_smem,previous_gcc,previous_qfprom,previous_cmd_db,previous_tz_log,previous_pmic,patched)):
        raise SystemExit('unexpected QEMU meson source')
    meson.write_text(contents.replace(original, patched).replace(previous, patched).replace(previous_smem,patched).replace(previous_gcc,patched).replace(previous_qfprom,patched).replace(previous_cmd_db,patched).replace(previous_tz_log,patched).replace(previous_pmic,patched))
    build = base / 'qemu-build'
    build.mkdir(exist_ok=True)
    configure = [str(src / 'configure'), '--target-list=aarch64-softmmu',
        '--with-devices-aarch64=minimal', '--without-default-features',
        '--enable-tcg', '--enable-fdt=internal', '--disable-docs', '--disable-tools']
    if not (build / 'build.ninja').exists():
        with (build / 'configure.log').open('w') as log:
            subprocess.run(configure, cwd=build, stdout=log, stderr=subprocess.STDOUT, check=True)
    with (build / 'build.log').open('w') as log:
        subprocess.run(['ninja', '-j', str(args.jobs), 'qemu-system-aarch64'], cwd=build,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    binary = build / 'qemu-system-aarch64'
    report = {'upstream_url': URL, 'archive_sha256': ARCHIVE_SHA256,
        'verification': 'Pinned SHA-256 of HTTPS download; detached signature not checked',
        'configure':configure, 'device_source_sha256':{device.name:sha(device) for device in devices},
        'meson_sha256':sha(meson), 'binary_sha256':sha(binary),
        'binary':str(binary.relative_to(ROOT)),
        'scope':'Nio SoC, sparse SMEM and bounded GCC/MMU and read-only QFPROM/command-database/TZ-log pointer and PMIC APID devices, plus optional RAM backing for original TZ monitor fixtures; no QHEE firmware patches',
        'reference': 'Nio live captures under reports/nio-scm-live-20260928-direct and reports/nio-smem-layout-20260928-v2'}
    (base / 'qemu-model-build.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
