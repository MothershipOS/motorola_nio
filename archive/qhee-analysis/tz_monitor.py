#!/usr/bin/env python3
"""Bounded original TZ monitor restore/ERET fixture; no phone access."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import struct
import subprocess
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from qhee import ROOT
from run_qemu import compile_elf, environment
from tz_handoff import image, run as handoff, PINNED_TZ
from xbl_target import read

RAM=((0x14680000,0x10000),(0x1c018000,0x18000))
WINDOWS=(('layout-initializer',0x1c01e310,0x124),('context-prepare',0x1c01d444,0x17c),
         ('secure-boot-tail',0x1c01de44,0x1cc),('context-restore',0x1c0194b0,0xb4),
         ('smc-handler-return',0x1c019200,0xac),('secure-context-save',0x1c01eb74,0x84),('early-gic-and-el2-reset',0x146805dc,0x48),
         ('cpu-helper-selector',0x1468384c,0xd0))


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory():
    data,segments=image();md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);windows={}
    for name,a,size in WINDOWS:
        blob=read(data,segments,a,size)
        ins=[{'address':hex(i.address),'mnemonic':i.mnemonic,'operands':i.op_str} for i in md.disasm(blob,a)]
        if len(ins)*4!=size:raise ValueError('Incomplete monitor window '+name)
        windows[name]={'address':hex(a),'size':size,'sha256':hashlib.sha256(blob).hexdigest(),'instructions':ins}
    return {'firmware_sha256':PINNED_TZ,'windows':windows,
            'per_cpu_scr_table':hex(struct.unpack('<Q',read(data,segments,0x1c019318,8))[0]),
            'cpu0_secure_sp_candidate':hex(struct.unpack('<Q',read(data,segments,0x1c119670,8))[0]),
            'scope':'Original monitor windows; startup state and boot records remain synthetic.'}


def prepare(out,initial_hcr=0x80000000,hyp=True,cpu="cortex-a55"):
    if cpu not in ("cortex-a55","cortex-a55,midr=0x51df805e","cortex-a76"):raise ValueError("Unsupported fixture CPU")
    if initial_hcr not in (0,0x80000000):raise ValueError('Unsupported fixture HCR')
    out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    data,segments=image();base_frame=handoff(hyp);frame=bytearray(0x110)
    struct.pack_into('<14Q',frame,0,*[int(v,16) for v in base_frame['frame']])
    # Complete the unexecuted context-SP output with the original CPU0 literal.
    struct.pack_into('<Q',frame,0x60,int(inventory()['cpu0_secure_sp_candidate'],16))
    (out/'frame.bin').write_bytes(frame)
    regions=[]
    for base,size in RAM:
        blob=bytearray(size)
        for segment in segments:
            start=max(base,segment["address"]);end=min(base+size,segment["address"]+segment["size"])
            if start<end:blob[start-base:end-base]=read(data,segments,start,end-start)
        path=out/f'ram-{base:x}.bin';path.write_bytes(blob)
        regions.append({'base':hex(base),'size':size,'path':str(path),'sha256':sha(path),
                        'scope':'Original file-backed bytes; uncovered RAM initially zero.'})
    source=Path(__file__).with_name('emulator')/'tz_monitor_fixture.S';elf=out/'fixture.elf'
    compile_elf(source,0x40200000,elf,[f'-DINITIAL_HCR={initial_hcr}'])
    symbols={name:int(a,16) for a,name in re.findall(r'^([0-9a-f]+) . (\w+)$',subprocess.check_output(['aarch64-linux-gnu-nm',str(elf)],text=True),re.M)}
    target=int(base_frame['selected']['next_pc'],16)
    # Independent diagnostic instructions are not original TZ or QHEE code.
    probe=struct.pack("<4I",0xd5384254,0xd53b4235,0xd53c1016 if hyp else 0xd5381016,0xd503201f)
    # Diagnostic MRS CurrentEL/DAIF/SCTLR, followed by NOP; no QHEE code.
    (out/'arrival.bin').write_bytes(probe)
    qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    command=[str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3','-cpu',cpu,'-m','2G','-smp','1',
             '-accel','tcg','-display','none','-serial','none','-monitor','none','-nic','none',
             '-semihosting-config','enable=on,target=native','-no-reboot','-device','nio-tz-fixture-ram',
             '-device',f'loader,file={elf},cpu-num=0','-device',f'loader,file={out / "frame.bin"},addr=0x403d8000,force-raw=on',
             '-device',f'loader,file={out / "arrival.bin"},addr={target:#x},force-raw=on']
    for region in regions:command+=['-device',f'loader,file={region["path"]},addr={region["base"]},force-raw=on']
    cpu_sample=ROOT/'reports/nio-diag-boot-20261004-kvm/linux/cpuinfo.txt'
    cpu_identity={'sample':str(cpu_sample.relative_to(ROOT)),'sha256':sha(cpu_sample),
                  'midr_from_fields':'0x51df805e','scope':'Measured implementer/variant/part/revision replay only. QEMU remains a Cortex-A55 TCG model, not Kryo/SM8250 hardware.'}
    return command,env,{'firmware_sha256':PINNED_TZ,'cpu_identity_control':cpu_identity,'frame_source':base_frame,'frame_sha256':sha(out/'frame.bin'),
        'cpu':cpu,'initial_hcr':hex(initial_hcr),'target':hex(target),'symbols':symbols,'ram_regions':regions,
        'inventory':inventory(),'fixture_elf_sha256':sha(elf),'arrival_sha256':sha(out/'arrival.bin'),
        'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in (Path(__file__),Path(__file__).with_name('tz_handoff.py'),source,
            Path(__file__).with_name('emulator')/'nio-tz-fixture-ram.c',Path(__file__).with_name('build_qemu_model.py'),Path(__file__).with_name('run_qemu.py'),Path(__file__).with_name('bootchain.py'),Path(__file__).with_name('xbl_target.py'),qemu)},
        'scope':'Original monitor layout initializer, dispatch, context handling, restore and ERET with a synthetic saved SMC frame. CPU0/HCR/stack/EL1-EL2 state and records are fixtures. CPU0 context SP is seeded from the original literal, not from executed secure startup. No XBL/bootstrap, full TZ startup, QHEE initialization, physical phone or KVM execution.'}


def run(out,initial_hcr=0x80000000,hyp=True,cpu="cortex-a55"):
    inventory()
    out=out.resolve();command,env,report=prepare(out,initial_hcr,hyp,cpu)
    points={report['symbols']['after_layout_init']:'layout-initialized',0x1c019200:'original-smc-entry',
            0x1c01e084:'before-context-prepare',0x1c01d5ac:'after-context-prepare',
            0x1c01de44:'before-nonsecure-restore',0x1c019538:'before-el3-control-restore',
            0x1c019560:'after-el3-control-restore',0x1c0192a8:'before-original-eret',
            int(report['target'],16):'next-context-entry'}
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
def snap():
    names=[f'x{i}' for i in range(31)]+['pc','sp','cpsr','SCR_EL3','SPSR_EL3','ELR_EL3','HCR_EL2','SCTLR_EL2','ESR_EL3','FAR_EL3','SCTLR']
    return {n:hex(int(gdb.parse_and_eval('$'+n))&((1<<64)-1)) for n in names}
def memory(a,n):return bytes(gdb.selected_inferior().read_memory(a,n)).hex()
class Point(gdb.Breakpoint):
    def stop(self):
        pc=int(gdb.parse_and_eval('$pc'))
        records.append({'name':points[pc],'registers':snap(),'layout_flag':memory(0x1c028158,1),'offsets':memory(0x1c029770,16),'ns_context':memory(0x1c028760,0x200),'scr_table':memory(0x1c0280e8,0x20),'saved_frame':memory(0x403d8000,0x110)})
        self.enabled=False
        return pc==TARGET
for pc in points:Point('*'+hex(pc))
class Failure(gdb.Breakpoint):
    def stop(self):
        records.append({'name':'terminal-failure','registers':snap()});return True
Failure('*'+hex(FAULT))
Failure('*'+hex(FAIL))
Failure('*0x146838e4')
end
continue
python
result={'checkpoints':records,'terminal':snap()}
if int(result['terminal']['pc'],16)==TARGET:
    for _ in range(3):gdb.execute('stepi',to_string=True)
    result['after_diagnostic_reads']=snap()
Path(OUTPUT).write_text(json.dumps(result,indent=2)+'\\n')
end
monitor quit
quit
'''.replace('PORT',str(port)).replace('POINTS',repr(points)).replace('TARGET',str(int(report['target'],16))).replace('FAULT',str(report['symbols']['faults'])).replace('FAIL',str(report['symbols']['fail'])).replace('OUTPUT',repr(str(out/'inspection.json')))
    (out/'trace.gdb').write_text(script);(out/'inspection.json').unlink(missing_ok=True)
    with (out/'stdout.txt').open('w') as stdout,(out/'stderr.txt').open('w') as stderr:
        proc=subprocess.Popen(command+['-S','-gdb',f'tcp:127.0.0.1:{port}','-d','in_asm','-D',str(out/'instructions.txt')],env=env,stdout=stdout,stderr=stderr)
        try:
            try:
                r=subprocess.run(['gdb-multiarch','-q','-nx','-batch','-x',str(out/'trace.gdb')],capture_output=True,text=True,timeout=25)
            except subprocess.TimeoutExpired as error:
                (out/'gdb.txt').write_bytes((error.stdout or b'')+(error.stderr or b''))
                raise ValueError('Bounded monitor trace timed out; inspect '+str(out)) from error
            (out/'gdb.txt').write_text(r.stdout+r.stderr)
            if not (out/'inspection.json').exists():raise ValueError('TZ monitor trace failed; inspect '+str(out/'gdb.txt'))
        finally:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
    report['command']=command;report['trace']=json.loads((out/'inspection.json').read_text())
    terminal=report['trace']['terminal'];diagnostic=report['trace'].get('after_diagnostic_reads',{})
    expected={'pc':report['target'],'cpsr':'0x89' if hyp else '0x85','SCR_EL3':'0x535' if hyp else '0x435',
              'SPSR_EL3':'0x89' if hyp else '0x85','ELR_EL3':report['target'],
              'HCR_EL2':hex(initial_hcr) if hyp else '0x80000000','SCTLR_EL2':'0x0'}
    expected.update({'x'+str(i):report['frame_source']['selected']['next_x'+str(i)] for i in range(4)})
    report['expected_terminal']=expected
    report['passed']=([int(c['registers']['pc'],16) for c in report['trace']['checkpoints']]==list(points)
        and all(terminal[k]==v for k,v in expected.items())
        and diagnostic.get('pc')==hex(int(report['target'],16)+12)
        and diagnostic.get('x20')==('0x8' if hyp else '0x4')
        and diagnostic.get('x21')=='0x80' and diagnostic.get('x22')=='0x0'
        and all(c['layout_flag']=='01' and c['offsets']=='00000000000000000801000000000000' for c in report['trace']['checkpoints'] if 'layout_flag' in c))
    # QEMU logs each translated instruction block's actual input bytes.
    data,segments=image();blocks=[]
    for address,raw in re.findall(r'0x([0-9a-f]+):[^\n]*\nOBJD-T: ([0-9a-f]+)',(out/'instructions.txt').read_text()):
        address=int(address,16);blob=bytes.fromhex(raw)
        if any(base<=address<base+size for base,size in RAM):
            original=read(data,segments,address,len(blob))
            if original!=blob:raise ValueError('Translated monitor bytes differ from pinned TZ')
            blocks.append({'address':hex(address),'size':len(blob),'sha256':hashlib.sha256(blob).hexdigest()})
    report['original_translated_blocks']=blocks
    report['trace_inspection']='Read-only GDB checkpoints, then three normal diagnostic MRS steps; monitor quit while paused. No in-flight register or memory edits.'
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    if not report['passed']:raise ValueError('Unexpected original monitor checkpoint order; inspect '+str(out))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'reports/qhee-offline/tz-monitor')
    p.add_argument('--cpu',choices=('cortex-a55','cortex-a55,midr=0x51df805e','cortex-a76'),default='cortex-a55')
    p.add_argument('--initial-hcr',type=lambda v:int(v,0),default=0x80000000);p.add_argument('--qhee-absent',action='store_true')
    a=p.parse_args();r=run(a.out,a.initial_hcr,not a.qhee_absent,a.cpu);print('Original monitor restore/ERET passed:',r['trace']['terminal'])
