#!/usr/bin/env python3
"""Execute original QHEE ID filtering instructions; inputs are test vectors.

This proves the transformation and loss of information, not raw phone IDs or
actual reserved-bank counts. No reconstruction is inferred from these vectors.
"""
import hashlib
import json
from pathlib import Path
import subprocess

from qhee import ROOT,QheeImage
from run_qemu import compile_elf,environment


def main():
    image=QheeImage()
    out=ROOT/'kernel-work/out/qhee-smmu-view-tests';out.mkdir(parents=True,exist_ok=True)
    qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    sources=Path(__file__).resolve().parent/'emulator'
    template=(sources/'register_probe.S').read_text()
    before,rest=template.split('#if ACCESS == 0',1);_,after=rest.split('#endif',1)
    cases=[('id0-stage1',0x8005c3e4,16,0x4c017e80,87,0x4c017e57),
           ('id0-stage2-hidden',0x8005c3e4,16,0x6c017e80,87,0x4c017e57),
           ('id0-nested-hidden',0x8005c3e4,16,0x7c017e80,87,0x4c017e57),
           ('id0-stream-count-replaced',0x8005c3e4,16,0x4c017e01,87,0x4c017e57),
           ('id1-no-reservation',0x8005c1a4,8,0x6000004a,0,0x6000004a),
           ('id1-subtract-example',0x8005c1a4,8,0x60000060,22,0x6000004a),
           ('id1-upper-fields-preserved',0x8005c1a4,8,0x60050060,22,0x6005004a)]
    results=[]
    for name,pc,size,raw,adjust,expected in cases:
        code=image.read(pc,size)
        words=[int.from_bytes(code[i:i+4],'little') for i in range(0,size,4)]
        assembly=f'ldr w8, ={raw:#x}\nldr w9, ={adjust:#x}\n'
        assembly+='\n'.join(f'.inst {word:#x}' for word in words)+'\nmov w19, w8\n'
        source=out/(name+'.S');source.write_text(before+assembly+after)
        elf=out/(name+'.elf');compile_elf(source,0x40200000,elf)
        cmd=[str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3',
             '-cpu','cortex-a76','-m','2G','-smp','1','-accel','tcg',
             '-display','none','-serial','stdio','-monitor','none','-nic','none',
             '-semihosting-config','enable=on,target=native','-no-reboot',
             '-device',f'loader,file={elf},cpu-num=0']
        run=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=5)
        passed=run.returncode==0 and run.stdout.splitlines()==['READ',f'{expected:016x}']
        results.append({'case':name,'passed':passed,'slice_pc':hex(pc),'original_bytes':code.hex(),
                        'synthetic_raw_input':hex(raw),'synthetic_adjustment':adjust,
                        'expected':hex(expected),'stdout':run.stdout,'stderr':run.stderr})
    report={'results':results,'image_sha256':hashlib.sha256(image.data).hexdigest(),
            'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
            'scope':__doc__.strip()}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):raise SystemExit('SMMU view instruction checks failed')


if __name__=='__main__':main()
