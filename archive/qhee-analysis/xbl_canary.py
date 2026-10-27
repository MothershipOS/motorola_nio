#!/usr/bin/env python3
"""Finite second-buffer fixture and original SEC canary/first readiness boundary."""
import argparse,hashlib,json,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
from qhee import ROOT
from xbl_target import payload
from tz_buffer import run,reply_model as first_reply

STOP=0x9fc0e37c
POINTS={0x9fc2846c:'canary-buffer-return',0x9fc28484:'canary-buffer-invalidate-return',
 0x9fc28494:'canary-buffer-source-ready',0x9fc0cd50:'sec-canary-source-return',
 0x9fc0cd58:'sec-canary-stored',0x9fc0cf48:'sec-canary-init-return',
 0x9fc0cf50:'sec-main-before-call',0x9fc0e308:'sec-main-entry',
 0x9fc0e33c:'sec-readiness-entry',STOP:'sec-readiness-before-load'}
WORDS={
 'stock':[0x2000a01,0x22,0x9fc356c0,8,7,0x1d,0,3,0x800a5018,0x80208dd8,0x801cc7e0,0x801cc7f0,0,0x801cc8b0],
 'el2':[0x2000a01,0x22,0x9fc356c0,8,7,0x1d,0x82000023,0xffffffffffffffff,0x444444dd444444cc,0xffffffffffffffff,4,0,0x707fe03a,0]}


def reply_model():
    first=first_reply();derivations={}
    for name,words in WORDS.items():
        r=run(words)
        if r['decode']['stop']!='0x1c065b0c' or r['reply_x0_x7'][:4]!=first['reply_x0_x3'] or r['fifo']['buffer_hex']!=first['buffer_hex']:
            raise ValueError('Unexpected second buffer derivation')
        derivations[name]={'input_x0_x13':[hex(v) for v in words],
          'derivation_sha256':hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest(),
          'validation_status':r['decode']['validation_status'],'decode_stop':r['decode']['stop']}
    return {'firmware_sha256':first['firmware_sha256'],'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'buffer_word':first['buffer_word'],'buffer_hex':first['buffer_hex'],'reply_x0_x3':first['reply_x0_x3'],
      'first_shifted_cache':hex(int(first['buffer_word'],16)>>4),'initial_canary_word':'0xc0c0c0c0',
      'query_count':1,'first_buffer_count':1,'canary_count_before':0,'canary_count_after':1,
      'stock_return_site':'0x80041aa4','stock_sp':'0x80208db0','el2_return_site':'0x9fc2846c','el2_sp':'0x9ffcfce0',
      'derivations':derivations,'joins':first['joins'],
      'scope':'Separately opted-in one-shot second buffer reply, derived from original TZ slices using captured stock/direct-EL2 register contracts and repeated finite FIFO fixtures. Same bytes as first fixture by design, not entropy or a secure production canary. Ownership/setup/release/cache/monitor return remain assumptions.'}


def contract():
    b,m=payload();md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);windows={}
    for name,a,n in (('canary-store',0x9fc0cd44,0x1c),('sec-main-call',0x9fc0cf44,0x10),
                     ('sec-main',0x9fc0e308,0x34),('readiness-poll',0x9fc0e33c,0x5c)):
        data=b[a-0x9fc00000:a-0x9fc00000+n];ins=[{'address':hex(i.address),'mnemonic':i.mnemonic,'operands':i.op_str} for i in md.disasm(data,a)]
        if len(ins)*4!=n:raise ValueError('Incomplete canary/readiness window')
        windows[name]={'address':hex(a),'size':n,'sha256':hashlib.sha256(data).hexdigest(),'instructions':ins}
    def word(a,n):return int.from_bytes(b[a-0x9fc00000:a-0x9fc00000+n],'little')
    base=word(0x9fc2f2c8,4);offset=word(0x9fc2f2d8,8);sentinel=word(0x9fc2f2e0,4)
    if (base,offset,sentinel)!=(0x146bf000,0x944,0x55444247) or (windows['canary-store']['instructions'][4]['mnemonic'],windows['canary-store']['instructions'][4]['operands'])!=('str','x0, [x8, #0xa8]'):
        raise ValueError('Unexpected original canary/readiness contract')
    return {'firmware_sha256':m['firmware_sha256'],'fv_sha256':m['segment_sha256'],'windows':windows,
      'canary_address':'0x9fc350a8','initial_canary_word':hex(word(0x9fc350a8,8)),
      'canary_guard_before_hex':b[0x350a0:0x350a8].hex(),'canary_guard_after_hex':b[0x350b0:0x350b8].hex(),
      'stop_before':hex(STOP),'readiness_address':hex(base+offset),'readiness_width':4,'wait_while_value':hex(sentinel),
      'readiness_literals':{'base_address':'0x9fc2f2c8','offset_address':'0x9fc2f2d8','sentinel_address':'0x9fc2f2e0'},
      'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'scope':'Original second buffer return, source load, canary store and SEC-main entry. Stop before first external readiness load; no readiness value/model, complete SEC/UEFI/ABL/Linux boot, phone entropy/cache coherency or physical KVM.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'reports/qhee-offline/canary-return-static');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    r={'contract':contract(),'reply_model':reply_model()}
    for name,w in r['contract']['windows'].items():(a.out/(name+'.txt')).write_text(''.join(f"{i['address']}: {i['mnemonic']} {i['operands']}\n" for i in w['instructions']))
    for name,words in WORDS.items():(a.out/(name+'-tz-slices.json')).write_text(json.dumps(run(words),indent=2)+'\n')
    (a.out/'manifest.json').write_text(json.dumps(r,indent=2)+'\n');print('SEC readiness boundary',r['contract']['stop_before'])

if __name__=='__main__':main()
