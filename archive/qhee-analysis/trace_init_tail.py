#!/usr/bin/env python3
"""Read-only GDB checkpoints of the pinned original QHEE init tail; offline only."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import socket
import subprocess

from qhee import DEFAULT_IMAGE
from run_qemu import environment
from smmu_config import PINNED_HYP

CHECKPOINTS = {
    0x80065ce8: 'command-database-setup-return',
    0x800440b4: 'memory-init-return',
    0x80044108: 'enter-log-sharing',
    0x800422a4: 'hypervisor-log-map-return',
    0x800422d8: 'tz-log-map-return',
    0x8004410c: 'log-sharing-return',
    0x8004415c: 'enter-pmic-init',
    0x80060d40: 'first-pmic-arbiter-table-read',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--through-late-scm', action='store_true', help='trace past late PRNG setup to SCM 0xc2000c1e')
    parser.add_argument('--through-main-return', action='store_true', help='trace main init return through final publication to handoff PRNG request')
    parser.add_argument('--through-pmic-return', action='store_true', help='record all 241 map requests, PMIC return, and subsequent SCM 0x4200020e')
    parser.add_argument('--through-pmic-scm', action='store_true', help='continue through both table scans to SCM 0xc2000c19')
    parser.add_argument('--through-pmic-tables', action='store_true', help='continue through the APID/owner scan to the second table read')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    points = dict(CHECKPOINTS)
    if args.through_pmic_tables or args.through_pmic_scm or args.through_pmic_return or args.through_main_return or args.through_late_scm:
        points.update({0x80061020:'first-pmic-owner-read',
                       0x80060d74:'apid-scan-complete',
                       0x80060d98:'second-pmic-table-read'})
    if args.through_pmic_scm:
        points[0x80041aa0] = 'pmic-secure-monitor-call'
    if args.through_pmic_return or args.through_main_return or args.through_late_scm:
        points.pop(0x80041aa0,None)
        points[0x80044160] = 'pmic-init-return'
        points[0x80041aa0] = 'post-pmic-secure-monitor-call'
    target_fid = 0x4200020e if args.through_pmic_return else 0xc2000c19
    if args.through_main_return or args.through_late_scm:
        points.pop(0x80041aa0,None)
        points.update({0x800441cc:'before-ready-publication',0x800441d0:'after-ready-publication',0x80040170:'main-init-return',0x80041aa0:'handoff-prng-request'})
        target_fid=0xc2000a02
    if args.through_late_scm:
        points.pop(0x80041aa0,None)
        points[0x80041aa0] = 'late-secure-monitor-call'
        target_fid=0xc2000c1e
    manifest = json.loads(args.manifest.read_text())
    if manifest['image_sha256'] != PINNED_HYP or hashlib.sha256(DEFAULT_IMAGE.read_bytes()).hexdigest() != PINNED_HYP:
        parser.error('Requires the pinned original QHEE image')
    model_symbols = {}
    el3 = args.manifest.resolve().parent/'el3.elf'
    if args.through_late_scm:
        symbols = subprocess.check_output(['aarch64-linux-gnu-nm',str(el3)],text=True)
        model_symbols = {n:int(a,16) for a,n in re.findall(r'^([0-9a-f]+) . (\w+)$',symbols,re.M)
                         if n in ('pmic_region_map_count','pmic_region_map_ledger','pil_empty_regions_count','handoff_prng_count')}
        if len(model_symbols) != 4: parser.error('Late trace requires all four model ledger symbols')
    command = manifest['command'][:]
    for flag in ('-d', '-D'):
        if flag in command:
            index = command.index(flag)
            del command[index:index+2]
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    script = '''set architecture aarch64
set pagination off
set confirm off
set remotetimeout 5
target remote 127.0.0.1:PORT
python
import gdb,json,struct,re
from pathlib import Path
points=POINTS
records=[];maps=[];late_prng=[]
target_fid=TARGET_FID
capture_maps=CAPTURE_MAPS
model_symbols=MODEL_SYMBOLS
def reg(name): return int(gdb.parse_and_eval('$'+name)) & ((1<<64)-1)
def physical_word(address):
    text=gdb.execute('monitor xp /1gx '+hex(address),to_string=True)
    match=re.search(r'[0-9a-fA-F]+:\\s+(0x[0-9a-fA-F]+)',text)
    if not match: raise RuntimeError('Cannot parse physical ledger read')
    return int(match.group(1),16)
class Checkpoint(gdb.Breakpoint):
    def stop(self):
        pc=reg('pc')
        if pc==0x80041aa0 and capture_maps and reg('x0')==0xc2000c19:
            if reg('x5')!=0x801cc390: raise RuntimeError('Unexpected PMIC mapping argument buffer')
            extended=struct.unpack('<2Q',bytes(gdb.selected_inferior().read_memory(0x801cc390,16)))
            maps.append([reg('x2'),reg('x3'),reg('x4'),*extended])
            Path(MAP_OUTPUT).write_text(json.dumps(maps,indent=2)+'\\n')
            return False
        if pc==0x80041aa0 and reg('x0')==0xc2000a02 and reg('x2') in (0x80095a60,0x801ccaa8,0x801ccaaa):
            late_prng.append([reg('x2'),reg('x3')])
        if pc==0x80041aa0 and reg('x0')!=target_fid: return False
        if pc==0x80041aa0 and target_fid==0xc2000a02 and reg('x2')!=0x80095a60: return False
        regs={n:hex(reg(n)) for n in [f'x{i}' for i in range(31)]+['sp','pc','SCTLR_EL2','TCR_EL2','TTBR0_EL2','HCR_EL2','SPSR_EL2','ELR_EL2']}
        frames=[]; fp=reg('x29'); seen=set()
        for _ in range(24):
            if fp in seen or fp & 15 or not 0x80040000 <= fp <= 0x8028aff0: break
            seen.add(fp)
            prev,lr=struct.unpack('<QQ',bytes(gdb.selected_inferior().read_memory(fp,16)))
            frames.append({'fp':hex(fp),'return_pc':hex(lr)})
            if prev<=fp: break
            fp=prev
        record={'name':points[pc],'registers':regs,'candidate_frame_chain':frames}
        if pc==0x80060d98:
            address=reg('x8')
            if not 0x80040000 <= address <= 0x8028afe0: raise RuntimeError('Unexpected descriptor address')
            record['pmic_descriptor_u16']=list(struct.unpack('<16H',bytes(gdb.selected_inferior().read_memory(address,32))))
        if pc==0x80041aa0 and reg('x0')==0xc2000c19:
            structure=bytes(gdb.selected_inferior().read_memory(0x800a4f68,56))
            record['pmic_channel_struct_hex']=structure.hex()
            pointer=struct.unpack_from('<Q',structure,24)[0]
            if 0x80040000 <= pointer <= 0x8028b000-3072:
                record['pmic_channel_records_hex']=bytes(gdb.selected_inferior().read_memory(pointer,3072)).hex()
                record['pmic_channel_records_address']=hex(pointer)
            else:
                record['pmic_channel_records_unread']='Pointer outside bounded QHEE image/BSS RAM'
            address=reg('x5')
            if 0x80040000 <= address <= 0x8028afe0:
                record['extended_words']=[hex(v) for v in struct.unpack('<4Q',bytes(gdb.selected_inferior().read_memory(address,32)))]
            else:
                record['extended_words_unread']='Pointer outside bounded QHEE image/BSS RAM'
        if pc==0x80041aa0 and reg('x0')==0xc2000c1e:
            record['late_prng_words']=[hex(struct.unpack('<I',bytes(gdb.selected_inferior().read_memory(address,4)))[0]) for address in (0x80095a60,0x801ccaa8)]
        if pc==0x80041aa0 and reg('x0')==0xc2000c1e:
            record['bridge_region_first32_hex']=bytes(gdb.selected_inferior().read_memory(0x800ab000,32)).hex()
            record['late_prng_calls']=late_prng
            record['model_counts']={n:physical_word(a) for n,a in model_symbols.items() if n.endswith('_count')}
            record['pmic_map_ledger']=[physical_word(model_symbols['pmic_region_map_ledger']+8*i) for i in range(241)]
        records.append(record)
        self.enabled=False
        Path(OUTPUT).write_text(json.dumps(records,indent=2)+'\\n')
        return pc==list(points)[-1]
for pc in points: Checkpoint('*'+hex(pc))
end
continue
detach
quit
'''.replace('PORT', str(port)).replace('POINTS', repr(points)).replace('MAP_OUTPUT',repr(str(out/'map-calls.json'))).replace('OUTPUT', repr(str(out/'checkpoints.json'))).replace('MODEL_SYMBOLS',repr(model_symbols)).replace('TARGET_FID',str(target_fid)).replace('CAPTURE_MAPS',repr(args.through_pmic_return or args.through_main_return or args.through_late_scm))
    (out/'trace.gdb').write_text(script)
    (out/'checkpoints.json').unlink(missing_ok=True)
    (out/'map-calls.json').unlink(missing_ok=True)
    with (out/'stdout.txt').open('w') as stdout, (out/'stderr.txt').open('w') as stderr:
        proc = subprocess.Popen(command+['-S','-gdb',f'tcp:127.0.0.1:{port}'],stdout=stdout,stderr=stderr,env=environment()[1])
        try:
            run = subprocess.run(['gdb-multiarch','-q','-nx','-batch','-x',str(out/'trace.gdb')],capture_output=True,text=True,timeout=30)
            (out/'gdb.txt').write_text(run.stdout+run.stderr)
            if run.returncode or not (out/'checkpoints.json').exists():
                raise SystemExit('Trace failed; see '+str(out/'gdb.txt'))
        finally:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
    records=json.loads((out/'checkpoints.json').read_text())
    report={'input_manifest':str(args.manifest.resolve()),
            'input_manifest_sha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
            'tool_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'el3_sha256':hashlib.sha256(el3.read_bytes()).hexdigest() if args.through_late_scm else None,
            'image_sha256':PINNED_HYP,'checkpoints':records,
            'pmic_map_calls':json.loads((out/'map-calls.json').read_text()) if args.through_pmic_return or args.through_main_return or args.through_late_scm else None,
            'scope':'Read-only register/stack inspection of original firmware under explicit synthetic models. Stops at the selected init boundary; pending stack return addresses are not executed checkpoints. No physical device access.'}
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in records: print(r['name'],r['registers']['pc'], 'x0='+r['registers']['x0'])
    if [int(r['registers']['pc'],16) for r in records] != list(points):
        raise SystemExit('Incomplete or unexpected checkpoint sequence')


if __name__=='__main__': main()
