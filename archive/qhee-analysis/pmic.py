"""Validate the bounded, read-only nio v5 PMIC APID capture."""
import hashlib
import json
from pathlib import Path
import re
import struct

APID_COMMAND = 'i=0; while [ "$i" -lt 512 ]; do a=$((0x0c440900 + i * 4)); printf "%08x " "$a"; devmem "$a" 32 || break; i=$((i+1)); done; test "$i" -eq 512'

OWNER_COMMAND = APID_COMMAND.replace("0x0c440900", "0x0c40a700")
SECONDARY_COMMAND = APID_COMMAND.replace("512", "256").replace("0x0c440900", "0x0c442300")

def lines(check, command):
    if check['command'] != command or type(check['status']) is not int or check['status'] != 0:
        raise ValueError('PMIC capture requires the exact successful read command')
    return [s.strip() for s in check['stdout'].splitlines() if s.strip() and s.strip() != '~ #']


def _sample(path: Path, *, kind='apid'):
    data = path.read_bytes()
    try:
        report = json.loads(data)
        checks = report['checks']
        version_lines = lines(checks['version'], 'devmem 0x0c440000 32')
        if len(version_lines) != 1 or not re.fullmatch(r'0x[0-9a-fA-F]{8}', version_lines[0]):
            raise ValueError('PMIC version must be one uint32')
        version = int(version_lines[0], 16)
        if version != 0x50010000:
            raise ValueError('Requires the captured nio v5 arbiter version')
        key, command, start, count = {
            'apid':('apid_table', APID_COMMAND, 0xc440900, 512),
            'owners':('owner_table', OWNER_COMMAND, 0xc40a700, 512),
            'secondary':('secondary_table', SECONDARY_COMMAND, 0xc442300, 256),
        }[kind]
        rows = lines(checks[key], command)
        if len(rows) != count:
            raise ValueError(f'PMIC {kind} table must have exactly {count} words')
        words = []
        for index, row in enumerate(rows):
            match = re.fullmatch(r'([0-9a-fA-F]{8}) (0x[0-9a-fA-F]{8})', row)
            if not match or int(match[1], 16) != start + 4 * index:
                raise ValueError('PMIC APID rows must be exact ordered address/uint32 pairs')
            words.append(int(match[2], 16))
        if kind == 'apid':
            first = lines(checks['first_apid'], 'devmem 0x0c440900 32')
            if len(first) != 1 or not re.fullmatch(r'0x[0-9a-fA-F]{8}', first[0]) or int(first[0],16) != words[0]:
                raise ValueError('PMIC first-entry capture mismatch')
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('Incomplete PMIC capture') from error
    blob = struct.pack('<'+str(count)+'I', *words)
    return blob, {'path':str(path.resolve()), 'sha256':hashlib.sha256(data).hexdigest(),
        'table_sha256':hashlib.sha256(blob).hexdigest(), 'version':hex(version),
        'start':hex(start), 'words':count, 'nonzero_words':sum(v != 0 for v in words),
        'capture_time':report.get('table_capture_time', report.get('timestamp')),
        'caveat':'EL1 postboot table replayed at EL2; equality is assumed. Read-only APID metadata, no PMIC transactions or ownership enforcement.'}


def sample(path: Path):
    return _sample(path)


def owner_sample(path: Path):
    return _sample(path, kind='owners')


def secondary_sample(path: Path):
    return _sample(path, kind='secondary')
