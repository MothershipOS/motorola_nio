#!/usr/bin/env python3
"""Execute pinned original ABL preparation/launch instructions in isolation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
from abl_contract import inventory, BASE, PREPARE
from qhee import ROOT
from run_qemu import compile_elf, environment


def trace(command,env,elf,out):
    symbols={name:int(a,16) for a,name in re.findall(r'^([0-9a-f]+) . (\w+)$',subprocess.check_output(['aarch64-linux-gnu-nm',str(elf)],text=True),re.M)}
    points={symbols['boundary_entry']:'fixture-entry',BASE+PREPARE:'original-prepare-entry',
        symbols['after_prepare']:'original-prepare-return',BASE+0x61db4:'original-kernel-call',symbols['kernel_probe']:'diagnostic-entry'}
    out.mkdir(exist_ok=True)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    script='''set architecture aarch64
set pagination off
set confirm off
set remotetimeout 5
target remote 127.0.0.1:PORT
python
import gdb,json
from pathlib import Path
points=POINTS;records=[]
def snapshot():
    names=[f'x{i}' for i in range(31)]+['pc','sp','cpsr','SCTLR','SCTLR_EL2','HCR_EL2','ESR_EL2']
    result={n:hex(int(gdb.parse_and_eval('$'+n))&((1<<64)-1)) for n in names}
    result['SCTLR_EL1']=result.pop('SCTLR') # QEMU exposes EL1 under this alias.
    return result
class Point(gdb.Breakpoint):
    def stop(self):
        pc=int(gdb.parse_and_eval('$pc'));records.append({'name':points[pc],'registers':snapshot()})
        self.enabled=False
        return pc==PROBE
for pc in points:Point('*'+hex(pc))
end
continue
stepi
python
Path(OUTPUT).write_text(json.dumps({'checkpoints':records,'after_probe_first_step':snapshot()},indent=2)+'\\n')
end
detach
quit
'''.replace('PORT',str(port)).replace('POINTS',repr(points)).replace('PROBE',str(symbols['kernel_probe'])).replace('OUTPUT',repr(str(out/'inspection.json')))
    (out/'trace.gdb').write_text(script);(out/'inspection.json').unlink(missing_ok=True)
    with (out/'stdout.txt').open('w') as stdout,(out/'stderr.txt').open('w') as stderr:
        q=subprocess.Popen(command+['-S','-gdb',f'tcp:127.0.0.1:{port}'],env=env,stdout=stdout,stderr=stderr)
        try:
            r=subprocess.run(['gdb-multiarch','-q','-nx','-batch','-x',str(out/'trace.gdb')],capture_output=True,text=True,timeout=20)
            (out/'gdb.txt').write_text(r.stdout+r.stderr)
            if r.returncode or not (out/'inspection.json').exists():raise ValueError('ABL boundary trace failed; inspect '+str(out/'gdb.txt'))
        finally:
            q.terminate()
            try:q.wait(timeout=5)
            except subprocess.TimeoutExpired:q.kill();q.wait()
    result=json.loads((out/'inspection.json').read_text())
    if [int(c['registers']['pc'],16) for c in result['checkpoints']]!=list(points):raise ValueError('Unexpected ABL checkpoints')
    result['scope']='Isolated pinned ABL instructions with synthetic entry/mapping/stack/frame/payload. Read-only debugger inspection and one normal instruction step; no full UEFI, QHEE or phone execution.'
    return result


def run(out,entry_el=2,mmu='on',qemu=None,with_trace=True,initial_daif='masked'):
    if entry_el not in (1,2) or mmu not in ('off','on') or initial_daif not in ('masked','unmasked'):raise ValueError('Invalid isolated entry state')
    out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    data,mapped,contract=inventory();image=out/'abl-mapped.bin';image.write_bytes(mapped)
    source=Path(__file__).with_name('emulator')/'abl_boundary.S';elf=out/'start.elf'
    compile_elf(source,0x40200000,elf,[f'-DENTRY_EL={entry_el}']+(['-DINITIAL_MMU_ON'] if mmu=='on' else [])+(['-DINITIAL_DAIF_MASKED'] if initial_daif=='masked' else []))
    q,env=environment(qemu or ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    command=[str(q),'-M','virt,secure=on,virtualization=on,gic-version=3','-cpu','cortex-a76','-m','2G',
        '-smp','1','-accel','tcg','-display','none','-serial','none','-monitor','none','-nic','none',
        '-semihosting-config','enable=on,target=native','-no-reboot','-device',f'loader,file={elf},cpu-num=0',
        '-device',f'loader,file={image},addr={BASE:#x},force-raw=on']
    r=subprocess.run(command,env=env,capture_output=True,text=True,timeout=10)
    report={'entry_el':entry_el,'initial_cpu_mmu_cache':mmu,'initial_daif':initial_daif,'command':command,'exit':r.returncode,
        'stdout':r.stdout,'stderr':r.stderr,'passed':r.returncode==0 and r.stderr==f'EL{entry_el}\n' and not r.stdout,
        'contract':contract,'elf_sha256':hashlib.sha256(elf.read_bytes()).hexdigest(),
        'tool_sha256':{str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),Path(__file__).with_name('abl_contract.py'),Path(__file__).with_name('bootchain.py'),Path(__file__).with_name('run_qemu.py'),source,q)},
        'scope':'Isolated preparation/launch boundary, not full ABL/UEFI boot. Synthetic PE base, entry state, stack and boot-parameter frame; DTB-pointer token only, no Linux or KVM. TCG has no physical dirty-cache/system-cache proof.'}
    (out/'stdout.txt').write_text(r.stdout);(out/'stderr.txt').write_text(r.stderr)
    if report['passed'] and with_trace:
        report['trace']=trace(command,env,elf,out/'trace')
        (out/'trace/manifest.json').write_text(json.dumps(report['trace'],indent=2)+'\n')
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    if not report['passed']:raise ValueError('ABL boundary diagnostic did not pass')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--entry-el',type=int,choices=(1,2),default=2)
    p.add_argument('--initial-mmu',choices=('off','on'),default='on');p.add_argument('--qemu',type=Path)
    p.add_argument('--initial-daif',choices=('masked','unmasked'),default='masked')
    p.add_argument('--out',type=Path,default=ROOT/'reports/qhee-offline/abl-boundary')
    args=p.parse_args();r=run(args.out,args.entry_el,args.initial_mmu,args.qemu,initial_daif=args.initial_daif)
    print('original ABL boundary','EL'+str(args.entry_el),args.initial_mmu,'PASS')
