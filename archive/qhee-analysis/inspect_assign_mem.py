#!/usr/bin/env python3
"""Read-only offline inspection of QHEE memory-assignment calls; never uses USB."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import socket
import subprocess

from qhee import ROOT, DEFAULT_IMAGE
from run_qemu import environment
from smmu_config import PINNED_HYP


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--skip', type=int, default=0, help='number of earlier assignment calls to skip')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if manifest['image_sha256'] != PINNED_HYP or hashlib.sha256(DEFAULT_IMAGE.read_bytes()).hexdigest() != PINNED_HYP:
        parser.error('Inspection requires the original pinned nio QHEE image')
    if not 0 <= args.skip <= 32:
        parser.error('--skip must be 0..32')
    command = manifest['command'][:]
    for flag in ('-d', '-D'):
        if flag in command:
            index = command.index(flag)
            del command[index:index + 2]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    loader = next(v for v in command if v.startswith('loader,file=') and v.endswith('/el3.elf,cpu-num=0'))
    el3 = Path(loader.split('file=',1)[1].split(',',1)[0])
    symbols = subprocess.check_output(['aarch64-linux-gnu-nm',str(el3)],text=True)
    ledgers = {}
    for name in ('smem_toc_ledger','smem_partition_ledger','tz_channel_ledger','tz_channel_21_42_ledger','cmd_db_assign_ledger','hyp_log_share_ledger'):
        match = re.search(r'^([0-9a-f]+) . '+name+r'$',symbols,re.M)
        if match: ledgers[name] = int(match.group(1),16)
    script = '''set architecture aarch64
set pagination off
set confirm off
set remotetimeout 5
target remote 127.0.0.1:PORT
break *0x80041aa0 if $x0 == 0xc2000c16
ignore 1 SKIP
continue
python
import gdb,json,struct,re
from pathlib import Path
def reg(name): return int(gdb.parse_and_eval('$'+name))
def read(addr,size):
    if not (0x80040000 <= addr and 0 <= size <= 4096 and addr+size <= 0x8028b000):
        raise RuntimeError('Argument buffer outside bounded QHEE RAM')
    return bytes(gdb.selected_inferior().read_memory(addr,size))
regs={f'x{i}':reg(f'x{i}') for i in range(8)}
if regs['x0'] != 0xc2000c16 or regs['x1'] != 0x1117 or regs['x3'] != 16:
    raise RuntimeError('Unexpected assignment contract')
frames=[];frame=reg('x29');seen=set()
for _ in range(24):
    if frame in seen or frame & 15 or not 0x80040000 <= frame <= 0x8028aff0: break
    seen.add(frame)
    previous,link=struct.unpack('<QQ',read(frame,16))
    frames.append({'fp':hex(frame),'previous_fp':hex(previous),'return_pc':hex(link)})
    if previous<=frame: break
    frame=previous
extra=struct.unpack('<4Q',read(regs['x5'],32))
source=read(regs['x4'],extra[0])
destination=read(extra[1],extra[2])
if len(source)%4 or len(destination)%24: raise RuntimeError('Invalid descriptor length')
result={'candidate_frame_chain':frames,'current_lr':hex(reg('x30')),'registers':{k:hex(v) for k,v in regs.items()},
        'cpu':{k:hex(reg(k)) for k in ('pc','TTBR0_EL2','SCTLR_EL2')},
        'extended_args':[hex(v) for v in extra],
        'region':list(struct.unpack('<QQ',read(regs['x2'],16))),
        'source_bytes':source.hex(),'destination_bytes':destination.hex(),
        'source_vmids':list(struct.unpack('<'+'I'*(len(source)//4),source)),
        'destinations':[dict(zip(('vmid','permission','context','context_size','reserved'),
                      struct.unpack_from('<IIQII',destination,i))) for i in range(0,len(destination),24)]}
def phys(addr):
    text=gdb.execute('monitor xp /1gx '+hex(addr),to_string=True)
    match=re.search(r'[0-9a-fA-F]+:\\s+(0x[0-9a-fA-F]+)',text)
    if not match: raise RuntimeError('Cannot parse physical read')
    return int(match.group(1),16)
result['ledgers']={}
for name,address in LEDGERS.items():
    size=640 if name=='smem_partition_ledger' else 16
    if not 0x40200000 <= address < address+size <= 0x40300000: raise RuntimeError('Unexpected EL3 ledger address')
    data=b''.join(phys(address+offset).to_bytes(8,'little') for offset in range(0,size,8))
    result['ledgers'][name]={'address':hex(address),'words':list(struct.unpack('<'+'Q'*(size//8),data))}
if reg('SCTLR_EL2') & 1:
    if reg('TCR_EL2') != 0x8081351c: raise RuntimeError('Unexpected translation regime')
    result['walks']=[]
    for va in (0x80900000,0x80901010,0x80aff230):
        base=reg('TTBR0_EL2') & 0x0000fffffffff000
        walk={'va':hex(va),'entries':[]}
        for level,shift in ((1,30),(2,21),(3,12)):
            address=base+8*((va>>shift)&511);pte=phys(address)
            walk['entries'].append({'level':level,'address':hex(address),'value':hex(pte)})
            if pte&3!=3 or level==3: break
            base=pte & 0x0000fffffffff000
        result['walks'].append(walk)
Path(OUTPUT).write_text(json.dumps(result,indent=2)+'\\n')
print(json.dumps(result,indent=2))
end
detach
quit
'''.replace('PORT', str(port)).replace('SKIP', str(args.skip)).replace('OUTPUT', repr(str(out/'buffers.json'))).replace('LEDGERS',repr(ledgers))
    (out/'buffers.json').unlink(missing_ok=True)
    (out/'inspect.gdb').write_text(script)
    with (out/'stdout.txt').open('w') as stdout, (out/'stderr.txt').open('w') as stderr:
        qemu = subprocess.Popen(command+['-S','-gdb',f'tcp:127.0.0.1:{port}'],
                                stdout=stdout,stderr=stderr,env=environment()[1])
        try:
            run = subprocess.run(['gdb-multiarch','-q','-nx','-batch','-x',str(out/'inspect.gdb')],
                                 capture_output=True,text=True,timeout=20)
            (out/'gdb.txt').write_text(run.stdout+run.stderr)
            if run.returncode or not (out/'buffers.json').exists():
                raise SystemExit('Inspection failed; see '+str(out/'gdb.txt'))
        finally:
            qemu.terminate()
            try: qemu.wait(timeout=5)
            except subprocess.TimeoutExpired: qemu.kill(); qemu.wait()
    result=json.loads((out/'buffers.json').read_text())
    result.update({'skip':args.skip,'input_manifest':str(args.manifest.resolve()),
                   'input_manifest_sha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
                   'el3_sha256':hashlib.sha256(el3.read_bytes()).hexdigest(),
                   'inspector_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   'scope':'Read-only offline QHEE call inspection; no guest-memory/register edits or phone access'})
    (out/'buffers.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
