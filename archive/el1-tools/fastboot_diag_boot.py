#!/usr/bin/env python3
"""RAM-boot the diagnostic image on nio and collect every available log.

Uses `fastboot boot` only; never flashes, erases or changes slots.

Log sources, in the order they become useful:
  1. USB CDC-ACM shell (1d6b:0104) exposed by the diagnostic initramfs:
     dmesg, pstore from the previous boot, device/clock/regulator state.
  2. ABL/UEFI logs in the `logfs` FAT partition (CurBoot.txt names the
     current LogNN.txt; the previous cycle holds the failed attempt).
  3. `fastboot oem logdump` (XBL boot log, PON/reset reasons, TZ log).
  4. ramoops at 0xaf000000, same layout as stock: the next diagnostic boot or
     rooted Android reads the previous kernel log from /sys/fs/pstore.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import nio_console  # noqa: E402


def run(argv, timeout=60, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **kwargs)


def state(serial):
    if serial in run(['fastboot', 'devices']).stdout:
        return 'fastboot'
    if nio_console.find_port():
        return 'diagnostic'
    adb = run(['adb', '-s', serial, 'get-state'])
    return adb.stdout.strip() or 'absent'


def wait_state(serial, wanted, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = state(serial)
        if current in wanted:
            return current
        time.sleep(1)
    return state(serial)


def android_logs(serial, out):
    """Pull ABL logs and pstore from rooted Android (read-only)."""
    for _ in range(90):
        if run(['adb', '-s', serial, 'shell', 'getprop', 'sys.boot_completed']).stdout.strip() == '1':
            break
        time.sleep(2)
    time.sleep(10)  # Magisk root is not ready immediately after boot_completed.
    adb = ['adb', '-s', serial, 'exec-out', 'su', '-c']
    image = subprocess.run(adb + ['cat /dev/block/by-name/logfs'], capture_output=True, timeout=120).stdout
    if image:
        (out / 'logfs.img').write_bytes(image)
        os.chmod(out / 'logfs.img', 0o600)
        subprocess.run(['7z', 'x', '-y', '-o' + str(out / 'logfs'), str(out / 'logfs.img')],
                       capture_output=True, check=False)
    for name in ['console-ramoops-0', 'pmsg-ramoops-0']:
        data = subprocess.run(adb + [f'cat /sys/fs/pstore/{name} 2>/dev/null'], capture_output=True, timeout=60).stdout
        if data:
            (out / f'android-pstore-{name}.txt').write_bytes(data)
    current = out / 'logfs/CurBoot.txt'
    if current.exists():
        # "cycle N, LogNN.txt": the previous cycle is the failed attempt.
        name = current.read_text().split()[-1]
        index = int(name.removeprefix('Log').removesuffix('.txt'))
        previous = out / 'logfs' / f'Log{index - 1:02d}.txt'
        if previous.exists():
            text = previous.read_text(errors='replace')
            start = text.find('cmd: boot')
            print(f'ABL log of the attempt: {previous.relative_to(ROOT)}')
            print(text[start:start + 4000] if start >= 0 else text[-3000:])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--image', type=Path, default=ROOT / 'kernel-work/out/diagnostic/boot-v2.img')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--gadget-timeout', type=float, default=90)
    parser.add_argument('--after', choices=['stay', 'bootloader', 'android'], default='stay',
                        help='what the phone does after collection (default: keep the diagnostic shell)')
    args = parser.parse_args()
    args.image = args.image.resolve()
    if args.out:
        args.out = args.out.resolve()
    metadata = json.loads(args.image.with_suffix('.json').read_text())
    digest = hashlib.sha256(args.image.read_bytes()).hexdigest()
    if digest != metadata['sha256']:
        raise SystemExit('Image hash does not match its packaging metadata')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = args.out or ROOT / 'reports' / f'nio-diag-boot-{stamp}'
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    record = {'image': str(args.image.relative_to(ROOT)), 'sha256': digest, 'started': stamp,
              'partition_writes': False}

    current = state(args.serial)
    if current == 'device':
        run(['adb', '-s', args.serial, 'reboot', 'bootloader'])
    elif current == 'diagnostic':
        nio_console.Shell(nio_console.find_port()).serial.write(b'nio-diag reboot bootloader\n')
    if wait_state(args.serial, {'fastboot'}, 90) != 'fastboot':
        raise SystemExit(f'phone did not reach fastboot (state: {state(args.serial)})')
    record['fastboot_reason'] = run(['fastboot', '-s', args.serial, 'getvar', 'reason']).stderr.splitlines()[0]
    boot = run(['fastboot', '-s', args.serial, 'boot', str(args.image)], timeout=180)
    record['fastboot_boot'] = {'exit': boot.returncode, 'output': boot.stderr.strip()}
    print(boot.stderr.strip())

    # ABL keeps its fastboot USB device up briefly after replying to `boot`.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and args.serial in run(['fastboot', 'devices']).stdout:
        time.sleep(0.5)
    landed = wait_state(args.serial, {'diagnostic', 'fastboot', 'device'}, args.gadget_timeout)
    record['landed'] = landed
    if landed == 'diagnostic':
        subprocess.run([sys.executable, str(ROOT / 'tools/nio_console.py'), 'collect', str(out / 'linux')], check=True)
        record['result'] = 'diagnostic initramfs reached; USB shell available'
        if args.after != 'stay':
            mode = ['bootloader'] if args.after == 'bootloader' else []
            subprocess.run([sys.executable, str(ROOT / 'tools/nio_console.py'), 'reboot', *mode], check=True)
    elif landed == 'fastboot':
        dump = run(['fastboot', '-s', args.serial, 'oem', 'logdump'], timeout=60)
        (out / 'fastboot-logdump.txt').write_text(dump.stdout + dump.stderr)
        record['result'] = 'returned to fastboot: ABL rejected the image or the kernel reset early'
        print('Returned to fastboot. Rebooting to Android to read ABL logs and pstore...')
        run(['fastboot', '-s', args.serial, 'reboot'], timeout=30)
        wait_state(args.serial, {'device'}, 180)
        android_logs(args.serial, out)
    else:
        record['result'] = f'no diagnostic shell; phone state {landed}'
        if landed == 'device':
            android_logs(args.serial, out)
    (out / 'attempt.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))
    print('Logs:', out.relative_to(ROOT))


if __name__ == '__main__':
    main()
