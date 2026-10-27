"""Firmware-derived SMMU count hypothesis; never a raw hardware capture.

Use enabled private reservations excluding VMID 1 in the pinned QHEE table
and require their projected Linux-visible counts to match the capture. Unknown
ID0 feature bits remain zero. This reconstructs a minimal control-path model,
not raw EL2 capabilities, context contents or DMA translation.
"""
import hashlib
import struct

from qhee import QheeImage

PINNED_HYP = 'f69538bf3fded342bb1679c3d01f0b2ad4ba930b235c11fda210efcf0240d8b2'


def firmware_counts(properties, image):
    digest=hashlib.sha256(image.data).hexdigest()
    if digest != PINNED_HYP:
        raise ValueError('SMMU descriptor layout requires the pinned nio QHEE image')
    pointer,=struct.unpack('<Q',image.read(0x800a2108,8))
    if pointer != 0x8009aa08:raise ValueError('Unexpected SMMU descriptor pointer')
    result=dict(properties);banks=[]
    for index,(name,base) in enumerate((('apps',0x15000000),('gpu',0x3da0000))):
        address=pointer+index*0x3b7c
        block=image.read(address,0x3b7c)
        if struct.unpack_from('<I',block)[0]!=base:raise ValueError('SMMU base mismatch')
        entries=[]
        for cb in range(96):
            offset=0xfc+cb*0x9c
            vmid=struct.unpack_from('<I',block,offset)[0]
            mode=struct.unpack_from('<I',block,offset+8)[0]
            enabled=block[offset+5]
            streams=struct.unpack_from('<H',block,offset+14)[0]
            entries.append({'index':cb,'vmid':vmid,'enabled':enabled,'mode':mode,
                            'streams':streams,'address':hex(address+offset)})
        reserved=[e for e in entries if e['mode']==0 and e['enabled'] and e['vmid']!=1]
        if not reserved:raise ValueError('No firmware-reserved contexts')
        total=1+max(e['index'] for e in reserved)
        if any(block[0xfc+e['index']*0x9c+4]!=e['index'] for e in entries[:total]):
            raise ValueError('Context descriptor indices mismatch')
        visible_contexts=properties[name+'-id1'] & 255
        if total-len(reserved)!=visible_contexts:raise ValueError('Firmware context count does not project to capture')
        reserved_streams=sum(e['streams'] for e in reserved)
        visible_streams=properties[name+'-id0'] & 255
        configured_visible=sum(e['streams'] for e in entries[:total] if e['mode']==3)
        raw_streams=visible_streams+reserved_streams
        if raw_streams>255 or min(configured_visible,raw_streams-reserved_streams)!=visible_streams:
            raise ValueError('Firmware stream count does not project to capture')
        result[name+'-id0']=(properties[name+'-id0'] & ~255)|raw_streams
        result[name+'-id1']=(properties[name+'-id1'] & ~255)|total
        banks.append({'name':name,'descriptor_address':hex(address),
                      'descriptor_sha256':hashlib.sha256(block).hexdigest(),
                      'model_contexts':total,'visible_contexts':visible_contexts,
                      'reserved_contexts':reserved,'reserved_streams':reserved_streams,
                      'model_streams':raw_streams,'visible_streams':visible_streams})
    return result, {'kind':'firmware-derived minimum-count hypothesis','image_sha256':digest,
        'banks':banks,'properties':{k:hex(v) for k,v in result.items()},
        'limitations':['Not a raw hardware measurement',
            'Assumes all enabled non-secure-only reservation descriptors apply',
            'ID0 hidden feature bits remain zero; no stage-2 capability is inferred',
            'No DMA translation or boot-time register contents reconstructed']}
