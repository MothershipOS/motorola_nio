"""Pinned finite PMIC channel requests derived from captures and QHEE records."""
import hashlib
import struct
from pmic import sample, owner_sample, secondary_sample
from smmu_config import PINNED_HYP

CAPTURE_HASHES = {
    'apid': '86d0f725380ef57781944e1cb77c386bea237497f9a2b6606f87acc290dd8c05',
    'owners': '2e78b6db19c0ec567c8a4472bfdc9d594a83b9907b2b98d4bceba277083a3182',
    'secondary': '5bfe627a2605aad0988b2ecbbdb16ea6b82f35df6e67b6386953fa223d9b7db1',
}


def inventory(image, apid_path, owner_path, secondary_path):
    if hashlib.sha256(image.data).hexdigest() != PINNED_HYP:
        raise ValueError('PMIC region model requires pinned nio QHEE')
    data = {}
    metadata = {}
    for name, parser, path in [('apid',sample,apid_path),('owners',owner_sample,owner_path),('secondary',secondary_sample,secondary_path)]:
        blob, meta = parser(path)
        if meta['sha256'] != CAPTURE_HASHES[name]:
            raise ValueError('PMIC region model requires pinned '+name+' capture')
        data[name] = blob
        metadata[name] = meta
    # Firmware table: EE4 -> mask16 -> VMID2; VMID2 uses TZ mapping type 1.
    if struct.unpack('<7H',image.read(0x800a4f38,14)) != (1,2,4,8,16,32,64):
        raise ValueError('Unexpected PMIC EE-mask table')
    if struct.unpack('<5I',image.read(0x800a2948,20)) != (2,36,36,1,0):
        raise ValueError('Unexpected VMID2 mapping policy')
    apids = struct.unpack('<512I',data['apid'])
    owners = struct.unpack('<512I',data['owners'])
    indices = [i for i,v in enumerate(apids) if v&0xff00 and owners[i]&15 == 4]
    if len(indices) != 241 or indices[0] != 111 or indices[-1] != 353:
        raise ValueError('Unexpected pinned secure-channel inventory')
    requests = [(0xc600000+i*0x10000,0xc600000+(i+1)*0x10000,2,6,1) for i in indices]
    return requests, {'captures':metadata, 'count':len(requests), 'channel_indices':indices,
        'scope':'Finite PMIC mappings inferred from pinned firmware policy and measured metadata; cross-checked against original QHEE records and execution. TZ success assumed; no access enforcement.'}
