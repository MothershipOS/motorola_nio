"""Validate nio's captured metadata and build a sparse, read-only SMEM image."""
import hashlib
import json
from pathlib import Path
import struct

BASE, SIZE = 0x80900000, 0x200000
MAGIC = b'NIOSMEM1'


def snapshot(manifest, output):
    manifest = Path(manifest).resolve()
    raw = manifest.read_bytes()
    report = json.loads(raw)
    if report.get('status') != 'captured':
        raise ValueError('SMEM capture is incomplete')
    if (int(report['reservation']['base'],0), int(report['reservation']['size'],0)) != (BASE,SIZE):
        raise ValueError('SMEM reservation does not match nio')
    data, valid = bytearray(SIZE), bytearray(SIZE)
    ranges, blocks = [], {}
    names = ('pointer','target_info','partition_table_header','partition_entries','global_header')
    if 'global_partition_header' in report['reads']:
        names += ('global_partition_header',)
    inventory = report.get('global_items',[])
    if len(inventory) > 625:
        raise ValueError('too many SMEM item headers')
    names += tuple(f'item_header_{i:03d}' for i in range(len(inventory)))
    payloads = {'board_info':(137,48,512),'ram_partitions':(402,24,4096)}
    names += tuple(name for name in payloads if name in report['reads'])
    for name in names:
        entry = report['reads'][name]
        block = (manifest.parent / (name+'.bin')).read_bytes()
        address, size = int(entry['address'],0), entry['size']
        if entry['exit'] != 0 or size != len(block) or hashlib.sha256(block).hexdigest() != entry['sha256']:
            raise ValueError('SMEM capture block is invalid: '+name)
        blocks[name] = block
        if name == 'pointer':
            if (address,size) != (0x1fd4000,8):
                raise ValueError('invalid SMEM pointer register pair')
            pointer, = struct.unpack('<Q',block)
            continue
        offset = address - BASE
        if size <= 0 or offset < 0 or offset + size > SIZE or any(valid[offset:offset+size]):
            raise ValueError('overlapping or out-of-bounds SMEM metadata: '+name)
        data[offset:offset+size], valid[offset:offset+size] = block, bytes([1])*size
        ranges.append({'name':name,'address':hex(address),'size':size,'sha256':entry['sha256']})
    info = blocks['target_info']
    toc = blocks['partition_table_header']
    if len(info) != 24 or struct.unpack_from('<4sIQ',info) != (b'SIII',SIZE,BASE):
        raise ValueError('invalid SMEM target info')
    if len(toc) != 32 or struct.unpack_from('<4sI',toc) != (b'$TOC',1):
        raise ValueError('unsupported SMEM partition table')
    count, = struct.unpack_from('<I',toc,8)
    if not 1 <= count <= 80 or len(blocks['partition_entries']) != count*48:
        raise ValueError('invalid SMEM partition count')
    expected = {'target_info':pointer,'partition_table_header':BASE+SIZE-4096,
                'partition_entries':BASE+SIZE-4096+32,'global_header':BASE}
    if pointer != BASE+SIZE-4096+32+count*48 or len(blocks['global_header']) != 208:
        raise ValueError('invalid SMEM metadata layout')
    if any(int(report['reads'][name]['address'],0) != addr for name,addr in expected.items()):
        raise ValueError('SMEM metadata address mismatch')
    if 'global_partition_header' in blocks:
        part = blocks['global_partition_header']
        if (len(part) != 32 or struct.unpack_from('<4sHHI',part) != (b'$PRT',0xfffe,0xfffe,0x146000)
                or int(report['reads']['global_partition_header']['address'],0) != BASE+0x1000):
            raise ValueError('invalid nio global partition header')
        if inventory:
            address = BASE+0x1020
            end = BASE+0x1000+struct.unpack_from('<I',part,12)[0]
            for i,entry in enumerate(inventory):
                name = f'item_header_{i:03d}'
                b = blocks[name]
                if len(b) != 16:
                    raise ValueError('invalid item header length')
                canary,item,size,padding,pad_header,_ = struct.unpack('<HHIHHI',b)
                if (canary != 0xa5a5 or item >= 625 or size % 8 or padding > size or pad_header
                        or int(report['reads'][name]['address'],0) != address
                        or address+16+size > end):
                    raise ValueError('invalid item header chain')
                address += 16+size
            if address != end:
                raise ValueError('incomplete item header chain')
    for payload,(item_id,minimum,maximum) in payloads.items():
        if payload not in blocks:
            continue
        matches = [i for i,b in enumerate(blocks[n] for n in names if n.startswith('item_header_'))
                   if struct.unpack_from('<H',b,2)[0] == item_id]
        if len(matches) != 1:
            raise ValueError(f'{payload} requires one captured item {item_id} header')
        header = report['reads'][f'item_header_{matches[0]:03d}']
        size = struct.unpack_from('<I',blocks[f'item_header_{matches[0]:03d}'],4)[0]
        padding = struct.unpack_from('<H',blocks[f'item_header_{matches[0]:03d}'],8)[0]
        if (not minimum <= len(blocks[payload]) <= maximum or len(blocks[payload]) != size-padding
                or int(report['reads'][payload]['address'],0) != int(header['address'],0)+16):
            raise ValueError(f'{payload} does not match its header')
    payload = struct.pack('<8sQII',MAGIC,pointer,BASE,SIZE) + data + valid
    output.write_bytes(payload)
    return {'manifest':str(manifest),'manifest_sha256':hashlib.sha256(raw).hexdigest(),
            'snapshot_sha256':hashlib.sha256(payload).hexdigest(),'pointer':hex(pointer),
            'ranges':ranges,'captured_bytes':sum(r['size'] for r in ranges),
            'policy':'Only captured bytes readable; all writes and uncaptured bytes abort',
            'caveat':report.get('caveat')}
