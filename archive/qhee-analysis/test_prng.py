#!/usr/bin/env python3
"""Check bounded deterministic PRNG replies, preservation and rejection."""
import hashlib
import json
from pathlib import Path
import subprocess

from qhee import ROOT
from run_qemu import compile_elf, decode_stop, environment
from test_replay import caller_source


def main():
    out = ROOT/'kernel-work/out/qhee-prng-tests'
    out.mkdir(parents=True,exist_ok=True)
    qemu,env = environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    source = Path(__file__).resolve().parent/'emulator/start.S'
    results = []
    seed = 0x736d656d
    cases = [('word',0x80095a28,4,0x22,2,0,True),
             ('half-low',0x801cc5d0,2,0x22,2,0,True),
             ('half-high',0x801cc5d2,2,0x22,2,0,True),
             ('wrong-buffer',0x801cc5d4,2,0x22,2,0,True),
             ('wrong-word-size',0x80095a28,8,0x22,2,0,True),
             ('wrong-half-size',0x801cc5d0,4,0x22,2,0,True),
             ('wrong-arginfo',0x80095a28,4,0x12,2,0,True),
             ('wrong-el',0x80095a28,4,0x22,1,0,True),
             ('wrong-immediate',0x80095a28,4,0x22,2,1,True),
             ('disabled',0x80095a28,4,0x22,2,0,False)]
    for name,address,size,arginfo,el,immediate,enabled in cases:
        dest = out/name
        dest.mkdir(exist_ok=True)
        assembly,initial = caller_source(0xc2000a02,arginfo,el,immediate)
        assembly = assembly.replace('ldr x2, =0x1202',f'ldr x2, ={address:#x}')
        assembly = assembly.replace('ldr x3, =0x1203',f'ldr x3, ={size:#x}')
        aligned = address & ~7
        assembly = assembly.replace('mov x9, #0xa0000000',
            f'ldr x9, ={aligned:#x}\nldr x10, =0xa5a5a5a5a5a5a5a5\nstr x10, [x9]\nmov x9, #0xa0000000')
        assembly = assembly.replace('mov x20, sp',
            f'ldr x0, ={aligned:#x}\nldr x0, [x0]\nstr x0, [sp, #264]\nmov x20, sp')
        assembly = assembly.replace('mov x21, #33','mov x21, #34')
        initial[2:4] = [address,size]
        (dest/'caller.S').write_text(assembly)
        compile_elf(dest/'caller.S',0x80040000,dest/'caller.elf')
        compile_elf(source,0x40200000,dest/'el3.elf',[f'-DPRNG_MODEL_WORD={seed:#x}'] if enabled else [])
        command = [str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3',
            '-cpu','cortex-a76','-m','2G','-smp','1','-accel','tcg',
            '-display','none','-serial','stdio','-monitor','none','-nic','none',
            '-semihosting-config','enable=on,target=native','-no-reboot',
            '-device',f'loader,file={dest/"el3.elf"},cpu-num=0',
            '-device',f'loader,file={dest/"caller.elf"}']
        run = subprocess.run(command,capture_output=True,env=env,timeout=5)
        text = run.stdout.decode(errors='replace')
        if name in ('word','half-low','half-high'):
            memory = bytearray(b'\xa5'*8)
            value = seed >> 16 if name == 'half-high' else seed
            memory[address-aligned:address-aligned+size] = (value & ((1<<(8*size))-1)).to_bytes(size,'little')
            expected = [0]+initial[1:]+[0x803f0000,0xa0000000,int.from_bytes(memory,'little')]
            lines = text.splitlines()
            passed = (len(lines)==35 and lines[0]=='MODEL_PRNG_FIXED_WORD_NOT_ENTROPY'
                      and [int(line,16) for line in lines[1:]] == expected)
        else:
            regs = (decode_stop(run.stdout) or {}).get('registers',{})
            passed = ('MODEL_PRNG' not in text and regs.get('x0')=='0xc2000a02'
                      and regs.get('x1')==hex(arginfo) and regs.get('x2')==hex(address)
                      and regs.get('x3')==hex(size))
        results.append({'case':name,'passed':passed and run.returncode==0,'stdout':text,
                        'stderr':run.stderr.decode(errors='replace')})
    report = {'results':results,'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
              'el3_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'scope':'Deterministic emulator replies only; no cryptographic entropy or phone TZ replacement'}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results: print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results): raise SystemExit('PRNG model regression failed')


if __name__ == '__main__':
    main()
