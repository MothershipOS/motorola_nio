#!/usr/bin/env python3
"""Validate captured PMIC metadata replays, rejection guards, and QHEE progress."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

from qhee import ROOT, QheeImage
from pmic import sample, owner_sample, secondary_sample
from run_qemu import compile_elf, environment

CAPTURES = [
    ('apid',sample,'nio-pmic-arbiter-20261005','apid_table',0xc440900,512,'snapshot'),
    ('owner',owner_sample,'nio-pmic-owners-20261005','owner_table',0xc40a700,512,'owners'),
    ('secondary',secondary_sample,'nio-pmic-secondary-map-20261005','secondary_table',0xc442300,256,'secondary'),
]


def main():
    out=ROOT/'kernel-work/out/qhee-pmic-tests';out.mkdir(parents=True,exist_ok=True)
    qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    sources=Path(__file__).resolve().parent/'emulator';results=[];tables={};paths={}
    for label,parser,folder,key,start,count,prop in CAPTURES:
        blob,metadata=parser(ROOT/'reports'/folder/'manifest.json')
        paths[label]=out/(label+'.bin');paths[label].write_bytes(blob)
        tables[label]=list(struct.unpack('<'+str(count)+'I',blob))
    machine=[str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3','-cpu','cortex-a76',
        '-m','2G','-smp','1','-accel','tcg','-display','none','-serial','stdio','-monitor','none','-nic','none',
        '-semihosting-config','enable=on,target=native','-no-reboot']
    device='nio-pmic-arb,'+','.join(f'{prop}={paths[label]}' for label,_,_,_,_,_,prop in CAPTURES)
    for label,parser,folder,key,start,count,prop in CAPTURES:
        cases=[('first',start,0,tables[label][0]),('last',start+4*(count-1),0,tables[label][-1]),
            ('middle',start+4*(count//2),0,tables[label][count//2]),
            ('previous',start-4,0,None),('next',start+count*4,0,None),
            ('unaligned',start+1,0,None),('read8',start,3,None),('read16',start,5,None),
            ('read64',start,4,None),('write8',start,7,None),('write32',start,1,None),('write64',start,8,None)]
        for name,addr,access,expected in cases:
            elf=out/(label+'-'+name+'.elf');compile_elf(sources/'register_probe.S',0x40200000,elf,[f'-DADDRESS={addr:#x}',f'-DACCESS={access}'])
            run=subprocess.run(machine+['-device',device,'-device',f'loader,file={elf},cpu-num=0'],capture_output=True,text=True,env=env,timeout=5)
            lines=run.stdout.splitlines()
            passed=(lines==['READ',f'{expected:016x}'] if expected is not None else len(lines)==3 and lines[0]=='ABORT'
                and int(lines[1],16)>>26==0x25 and int(lines[1],16)&0x3f==0x10 and int(lines[2],16)==addr)
            results.append({'case':label+'/'+name,'passed':passed and run.returncode==0,'stdout':run.stdout,'stderr':run.stderr})
        # Read every entry twice; proves exact endian/order/content and immutable repeated reads.
        assembly=(sources/'register_probe.S').read_text().replace('    ldr w19, [x8]\n#elif ACCESS == 1',f'''    mov x22, x8
    mov x20, #0
    mov x21, #{2*count}
    adr x0, read_message
    bl puts
all_words:
    and x23, x20, #{count-1}
    ldr w19, [x22, x23, lsl #2]
    mov x0, x19
    bl hex64
    add x20, x20, #1
    cmp x20, x21
    b.lo all_words
    b exit
#elif ACCESS == 1''')
        src=out/(label+'-all.S');src.write_text(assembly);elf=src.with_suffix('.elf')
        compile_elf(src,0x40200000,elf,[f'-DADDRESS={start:#x}','-DACCESS=0'])
        run=subprocess.run(machine+['-device',device,'-device',f'loader,file={elf},cpu-num=0'],capture_output=True,text=True,env=env,timeout=5)
        results.append({'case':label+'/all-words-twice','passed':run.returncode==0 and run.stdout.splitlines()==['READ']+[f'{v:016x}' for v in tables[label]*2]})
        capture=json.loads((ROOT/'reports'/folder/'manifest.json').read_text())
        for name in ('failed','boolean-status','wrong-command','wrong-version','short','long','reordered','duplicate','wrong-address','overflow','negative','junk','missing','wrong-width'):
            report=copy.deepcopy(capture);check=report['checks'][key];rows=[s for s in check['stdout'].splitlines() if s.strip() and s.strip()!='~ #']
            if name=='failed':check['status']=1
            if name=='boolean-status':check['status']=False
            if name=='wrong-command':check['command']='devmem 0 32'
            if name=='wrong-version':report['checks']['version']['stdout']='0x70000000\n'
            if name=='short':rows=rows[:-1]
            if name=='long':rows+=rows[-1:]
            if name=='reordered':rows[0],rows[1]=rows[1],rows[0]
            if name=='duplicate':rows[1]=rows[0]
            if name=='wrong-address':rows[0]='00000000 '+rows[0].split()[1]
            if name=='overflow':rows[0]=rows[0].split()[0]+' 0x100000000'
            if name=='negative':rows[0]=rows[0].split()[0]+' -1'
            if name=='junk':rows[0]+=' extra'
            if name=='missing':del report['checks'][key]
            if name=='wrong-width':check['command']=check['command'].replace('32','64')
            check['stdout']='\n'.join(rows)+'\n'
            path=out/'bad-capture.json';path.write_text(json.dumps(report))
            try:parser(path)
            except ValueError:passed=True
            else:passed=False
            results.append({'case':label+'/capture-'+name,'passed':passed})
        for length in (0,count*4-1,count*4+1):
            bad=out/'bad-snapshot.bin';bad.write_bytes(bytes(length))
            bad_device=device.replace(f'{prop}={paths[label]}',f'{prop}={bad}')
            run=subprocess.run(machine+['-device',bad_device],capture_output=True,text=True,env=env,timeout=5)
            results.append({'case':label+'/blob-length-'+str(length),'passed':run.returncode!=0 and 'must contain exactly' in run.stderr})
    for name,addr,options in [('device-disabled',0xc440900,[]),
            ('owners-disabled',0xc40a700,['-device',f'nio-pmic-arb,snapshot={paths["apid"]}']),
            ('secondary-disabled',0xc442300,['-device',f'nio-pmic-arb,snapshot={paths["apid"]},owners={paths["owner"]}']),
            ('core-unlisted',0xc440000,['-device',device]),('config-unlisted',0xc40a000,['-device',device])]:
        elf=out/(name+'.elf');compile_elf(sources/'register_probe.S',0x40200000,elf,[f'-DADDRESS={addr:#x}','-DACCESS=0'])
        run=subprocess.run(machine+options+['-device',f'loader,file={elf},cpu-num=0'],capture_output=True,text=True,env=env,timeout=5)
        lines=run.stdout.splitlines()
        results.append({'case':name,'passed':run.returncode==0 and len(lines)==3 and lines[0]=='ABORT' and int(lines[2],16)==addr})
    im=QheeImage()
    results.append({'case':'pinned-table-bounds','passed':struct.unpack('<H',im.read(0x800a4f46,2))[0]==512 and struct.unpack('<H',im.read(0x800a4f54,2))[0]==256})
    report={'results':results,'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__).resolve(),Path(__file__).with_name('pmic.py').resolve(),sources/'nio-pmic-arb.c']},
        'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
        'scope':'Exact read-only PMIC metadata; no PMIC transactions, register writes or access enforcement'}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):raise SystemExit('PMIC replay regression failed')


if __name__=='__main__':main()
