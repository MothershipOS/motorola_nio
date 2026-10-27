#!/usr/bin/env python3
"""Capture bounded nio SMEM metadata, optionally board info; never write MMIO."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct

import nio_console

BASE, SIZE = 0x80900000, 0x200000
TOC = BASE + SIZE - 0x1000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--boot-image', type=Path, required=True)
    parser.add_argument('--global-partition-header', action='store_true',
                        help='also capture the 32-byte global partition header, not its items')
    parser.add_argument('--global-item-headers', action='store_true',
                        help='walk bounded uncached item headers, skipping every item payload')
    parser.add_argument('--board-info', action='store_true',
                        help='also capture identified item 137 (board information), at most 512 bytes')
    parser.add_argument('--ram-partitions', action='store_true',
                        help='also capture identified item 402 (RAM partition table), at most 4096 bytes')
    args = parser.parse_args()
    image_hash = hashlib.sha256(args.boot_image.read_bytes()).hexdigest()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    shell = nio_console.Shell(nio_console.wait_port(15))
    record = {'captured_at':datetime.now(timezone.utc).isoformat(),
              'boot_image_sha256':image_hash, 'transport':'nio diagnostic USB shell at EL1',
              'scope':'Read-only pointer pair, target info, partition table and global headers; item payloads only when explicitly selected',
              'reservation':{'base':hex(BASE),'size':hex(SIZE),
                  'evidence':'reports/nio-kernel-20260927T103955324089Z/live.dts, smem_region@80900000'},
              'reads':{}, 'caveat':'Post-boot snapshot, not an atomic capture of pre-QHEE cold-boot state'}
    if args.board_info:
        record['scope'] += '; explicitly selected board-information item 137 included'
    if args.ram_partitions:
        record['scope'] += '; explicitly selected RAM partition item 402 included'

    def read_words(name, address, size):
        if address & 3 or size & 3 or not 0 < size <= 4096:
            raise ValueError('invalid bounded word read')
        if not (BASE <= address and address + size <= BASE + SIZE) and (address,size) != (0x1fd4000,8):
            raise ValueError('outside fixed SMEM reservation and pointer pair')
        command = (f'a={address}; while [ "$a" -lt {address+size} ]; do '
                   'busybox devmem "$a" 32 || exit; a=$((a+4)); done')
        rc, stdout = shell.run(command, timeout=30)
        (out / (name+'.txt')).write_text(stdout)
        words = re.findall(r'^(?:~ # )?0x([0-9A-Fa-f]{8})$', stdout, re.M)
        entry = {'address':hex(address),'size':size,'command':command,'exit':rc}
        record['reads'][name] = entry
        if rc != 0 or len(words) != size//4:
            raise ValueError(f'{name}: incomplete read; see raw evidence')
        data = b''.join(struct.pack('<I',int(word,16)) for word in words)
        (out / (name+'.bin')).write_bytes(data)
        entry['sha256'] = hashlib.sha256(data).hexdigest()
        return data

    try:
        pointer, = struct.unpack('<Q',read_words('pointer',0x1fd4000,8))
        record['target_info_address'] = hex(pointer)
        # Target info follows the partition table in the final reserved page.
        if not TOC + 32 <= pointer <= BASE + SIZE - 24:
            raise ValueError('pointer is outside the bounded SMEM table page')
        info = read_words('target_info',pointer,24)
        magic,size,base,reserved,items = struct.unpack('<4sIIIH',info[:18])
        if magic != b'SIII' or size != SIZE or base != BASE or reserved:
            raise ValueError('target info does not match nio SMEM reservation')
        record['target_info'] = {'magic':'SIII','base':hex(base),'size':hex(size),
                                 'num_items':items,'tail_hex':info[18:].hex()}
        header = read_words('partition_table_header',TOC,32)
        magic,version,count = struct.unpack_from('<4sII',header)
        if magic != b'$TOC' or count > 80 or TOC + 32 + 48*count != pointer:
            raise ValueError('partition count/layout does not match target-info pointer')
        entries = read_words('partition_entries',TOC+32,48*count) if count else b''
        partitions = []
        for index in range(count):
            offset,size,flags,host0,host1,cacheline = struct.unpack_from('<IIIHHI',entries,index*48)
            table_reservation = host0 == host1 == 0xffff and offset == SIZE-4096 and size == 4096
            if offset + size > SIZE or (size and offset + size > SIZE-4096 and not table_reservation):
                raise ValueError('partition extends outside SMEM data region')
            partitions.append({'offset':hex(offset),'size':hex(size),'flags':hex(flags),
                               'host0':host0,'host1':host1,'cacheline':cacheline})
        record['partition_table'] = {'version':version,'count':count,'partitions':partitions}
        if args.global_partition_header or args.global_item_headers or args.board_info or args.ram_partitions:
            global_parts = [p for p in partitions if p['host0'] == p['host1'] == 0xfffe]
            if len(global_parts) != 1:
                raise ValueError('expected one global partition')
            p = global_parts[0]
            part = read_words('global_partition_header',BASE+int(p['offset'],0),32)
            magic,host0,host1,size,uncached,cached = struct.unpack_from('<4sHHIII',part)
            if (magic,host0,host1,size) != (b'$PRT',0xfffe,0xfffe,int(p['size'],0)):
                raise ValueError('global partition header mismatch')
            if not 32 <= uncached <= cached <= size:
                raise ValueError('invalid global partition free offsets')
            record['global_partition_header'] = {'offset_free_uncached':hex(uncached),
                'offset_free_cached':hex(cached),'size':hex(size)}
            if args.global_item_headers or args.board_info or args.ram_partitions:
                if cached != size:
                    raise ValueError('cached item traversal is not implemented')
                address, end = BASE+int(p['offset'],0)+32, BASE+int(p['offset'],0)+uncached
                inventory = []
                while address < end:
                    if len(inventory) >= items or address+16 > end:
                        raise ValueError('item traversal exceeds bounds')
                    name = f'item_header_{len(inventory):03d}'
                    entry = read_words(name,address,16)
                    canary,item,length,pad_data,pad_header,reserved = struct.unpack('<HHIHHI',entry)
                    if (canary != 0xa5a5 or item >= items or pad_header != 0 or
                            pad_data > length or length % 8 or address+16+length > end):
                        raise ValueError('invalid uncached item header')
                    inventory.append({'name':name,'item':item,'address':hex(address),
                        'payload_address':hex(address+16),'payload_size':length-pad_data,
                        'allocated_size':length})
                    address += 16+length
                # Detect allocation changes during the non-atomic header walk.
                after = read_words('global_partition_header_after',BASE+int(p['offset'],0),32)
                if after != part:
                    raise ValueError('global partition changed during capture')
                record['global_items'] = inventory
                if args.board_info:
                    matches = [item for item in inventory if item['item'] == 137]
                    if len(matches) != 1 or not 48 <= matches[0]['payload_size'] <= 512:
                        raise ValueError('unexpected board-info item size or count')
                    item = matches[0]
                    info = read_words('board_info',int(item['payload_address'],0),item['payload_size'])
                    record['board_info'] = {'item':137,'size':len(info),
                        'format':struct.unpack_from('<I',info)[0],
                        'soc_id':struct.unpack_from('<I',info,4)[0],
                        'soc_version':hex(struct.unpack_from('<I',info,8)[0])}
                if args.ram_partitions:
                    matches = [item for item in inventory if item['item'] == 402]
                    if len(matches) != 1 or not 24 <= matches[0]['payload_size'] <= 4096:
                        raise ValueError('unexpected RAM partition item size or count')
                    item = matches[0]
                    data = read_words('ram_partitions',int(item['payload_address'],0),item['payload_size'])
                    record['ram_partitions'] = {'item':402,'size':len(data),
                        'header_words':[hex(v) for v in struct.unpack_from('<6I',data)]}
        global_header = read_words('global_header',BASE,208)
        record['global_header'] = {'versions':[hex(v) for v in struct.unpack_from('<32I',global_header,64)],
            'initialized':struct.unpack_from('<I',global_header,192)[0]}
        record['status'] = 'captured'
    except Exception as error:
        record['status'] = 'incomplete'
        record['error'] = str(error)
        raise
    finally:
        (out / 'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:record[k] for k in ('status','target_info_address','target_info','partition_table')},indent=2))


if __name__ == '__main__':
    main()
