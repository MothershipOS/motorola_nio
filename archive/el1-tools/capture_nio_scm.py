#!/usr/bin/env python3
"""Read fixed firmware-state queries from the nio diagnostic USB shell."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import nio_console

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--boot-image', type=Path, required=True)
    parser.add_argument('--direct-register', action='store_true',
                        help='also read the fixed hardware-version register through /dev/mem')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    shell = nio_console.Shell(nio_console.wait_port(15))
    commands = {
        'uname':'uname -a',
        'compatible':'tr "\\000" "\\n" < /sys/firmware/devicetree/base/compatible',
        'secure_state':'cat /sys/devices/platform/firmware:scm/nio_secure_state',
        'soc_hw_version':'cat /sys/devices/platform/firmware:scm/nio_soc_hw_version',
    }
    if args.direct_register:
        commands['soc_hw_version_direct'] = 'busybox devmem 0x01fc8000 32'
    results = {}
    for name, cmd in commands.items():
        rc, stdout = shell.run(cmd, timeout=15)
        (out / (name+'.txt')).write_text(stdout)
        results[name] = {'command':cmd, 'exit':rc, 'stdout':stdout}
        print(name, 'exit', rc, stdout.strip())
    record = {'captured_at':datetime.now(timezone.utc).isoformat(),
        'transport':'nio diagnostic USB shell; Linux running at EL1 under QHEE',
        'boot_image_sha256':hashlib.sha256(args.boot_image.read_bytes()).hexdigest(),
        'scope':'Fixed read-only SCM INFO/GET_SECURE_STATE and IO_READ queries',
        'checks':results,
        'caveat':'EL1-visible result may be mediated by QHEE; not a direct capture of the EL2 caller response'}
    text = results['secure_state']['stdout']
    match = re.search(r'status=(-?\d+) r1=(0x[0-9a-f]+) r2=(0x[0-9a-f]+) r3=(0x[0-9a-f]+)',text)
    if results['secure_state']['exit'] == 0 and match:
        record['secure_state'] = {'service':'0x42000604', 'status':int(match[1]),
                                  'r1':match[2],'r2':match[3],'r3':match[4]}
    match = re.search(r'status=(-?\d+) address=0x01fc8000 value=(0x[0-9a-f]+)',results['soc_hw_version']['stdout'])
    if results['soc_hw_version']['exit'] == 0 and match:
        record['soc_hw_version'] = {'method':'SCM_IO_READ', 'status':int(match[1]), 'value':match[2]}
    direct = results.get('soc_hw_version_direct')
    if direct and direct['exit'] == 0:
        match = re.search(r'^(?:~ # )?(0x[0-9a-fA-F]{8})$', direct['stdout'], re.M)
        if match:
            record['soc_hw_version_direct'] = {'method':'read-only /dev/mem, 32 bits',
                'address':'0x01fc8000', 'value':match[1].lower()}
    (out / 'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
    if not record.get('secure_state') or record['secure_state']['status'] != 0:
        raise SystemExit('Secure-state query did not succeed; see saved evidence')


if __name__ == '__main__':
    main()
