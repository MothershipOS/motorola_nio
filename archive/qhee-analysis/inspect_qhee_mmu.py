#!/usr/bin/env python3
"""Read-only GDB inspection of the current QHEE VMID-5/SMEM model failure.

Reuses a locally generated run_qemu manifest. This is a pinned-firmware probe,
not a generic debugger or a phone tool. No register/memory values are changed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess

from qhee import ROOT, DEFAULT_IMAGE
from run_qemu import environment


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=ROOT/'kernel-work/out/qhee-qfprom/manifest.json')
    parser.add_argument('--out',type=Path,default=ROOT/'reports/qhee-offline/qfprom-mmu-inspection')
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text())
    expected='f69538bf3fded342bb1679c3d01f0b2ad4ba930b235c11fda210efcf0240d8b2'
    if manifest['image_sha256']!=expected or hashlib.sha256(DEFAULT_IMAGE.read_bytes()).hexdigest()!=expected:
        raise SystemExit('This inspection requires the original pinned nio QHEE image')
    command=manifest['command'][:]
    for flag in ('-d','-D'):
        if flag in command:
            index=command.index(flag);del command[index:index+2]
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    script='''set architecture aarch64
set pagination off
set confirm off
set remotetimeout 5
target remote 127.0.0.1:PORT
break *0x8006781c if $w0 != 0
continue
python
import gdb,json,re
from pathlib import Path
def reg(name): return int(gdb.parse_and_eval('$'+name))
def phys(addr):
    text=gdb.execute('monitor xp /1gx '+hex(addr),to_string=True)
    match=re.search(r'[0-9a-fA-F]+:\\s+(0x[0-9a-fA-F]+)',text)
    if not match: raise RuntimeError('Cannot parse physical memory read: '+text)
    return int(match.group(1),16)
result={'init_failure':{'pc':hex(reg('pc')),'return_code':reg('x0'),
    'descriptor_address':hex(reg('x24')),'descriptor_words':
    list(__import__('struct').unpack('<5I',bytes(gdb.selected_inferior().read_memory(reg('x24'),20))))}}
end
delete breakpoints
break *0x8005ea9c if ($SCTLR_EL2 & 1)
continue
python
result['cpu']={name:hex(reg(name)) for name in ('pc','TTBR0_EL2','TCR_EL2','SCTLR_EL2')}
if reg('TCR_EL2') != 0x8081351c: raise RuntimeError('Unexpected translation regime')
result['walks']=[]
for va in (0x80040000,0x80900000,0x80901010,0x80aff230,0xb7700000):
    base=reg('TTBR0_EL2') & 0x0000fffffffff000
    walk={'va':hex(va),'entries':[]}
    for level,shift in ((1,30),(2,21),(3,12)):
        address=base+8*((va>>shift)&511)
        pte=phys(address)
        walk['entries'].append({'level':level,'address':hex(address),'value':hex(pte)})
        if pte&3 != 3 or level==3: break
        base=pte & 0x0000fffffffff000
    result['walks'].append(walk)
Path(OUTPUT).write_text(json.dumps(result,indent=2)+'\\n')
end
detach
quit
'''.replace('PORT',str(port)).replace('OUTPUT',repr(str(out/'inspection.json')))
    (out/'inspection.json').unlink(missing_ok=True)
    script_path=out/'inspect.gdb';script_path.write_text(script)
    with (out/'qemu-stdout.txt').open('w') as stdout,(out/'qemu-stderr.txt').open('w') as stderr:
        qemu=subprocess.Popen(command+['-S','-gdb',f'tcp:127.0.0.1:{port}'],
                              stdout=stdout,stderr=stderr,env=environment()[1])
        try:
            run=subprocess.run(['gdb-multiarch','-q','-nx','-batch','-x',str(script_path)],
                               capture_output=True,text=True,timeout=20)
            (out/'gdb.txt').write_text(run.stdout+run.stderr)
            if run.returncode:raise SystemExit('GDB inspection failed; see '+str(out/'gdb.txt'))
        finally:
            qemu.terminate()
            try:qemu.wait(timeout=5)
            except subprocess.TimeoutExpired:qemu.kill();qemu.wait()
    result=json.loads((out/'inspection.json').read_text())
    failed=result['init_failure'];walks={r['va']:r['entries'] for r in result['walks']}
    checks={'vmid5_returns_4':failed['return_code']==4 and failed['descriptor_words']==[5,32,36,0,0],
            'qhee_code_mapped':len(walks['0x80040000'])==3 and walks['0x80040000'][-1]['value']=='0x10000080040787',
            'smem_l2_absent':walks['0x80901010'][-1]=={'level':2,'address':'0xb7701020','value':'0x0'},
            'smem_toc_l2_absent':walks['0x80aff230'][-1]=={'level':2,'address':'0xb7701028','value':'0x0'}}
    result.update({'checks':checks,'input_manifest':str(args.manifest.resolve()),
        'input_manifest_sha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        'inspector_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope':'Offline QHEE state inspection; no edits to guest registers or memory; no phone handoff claim'})
    (out/'inspection.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    if not all(checks.values()):raise SystemExit('Inspection differs from expected boundary')


if __name__=='__main__':main()
