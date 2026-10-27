#!/usr/bin/env python3
"""Differential original-QHEE init-tail tests and read-only execution checkpoints."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from qhee import ROOT
from run_qemu import environment


def main():
    out=ROOT/'kernel-work/out/qhee-init-tail-tests';out.mkdir(parents=True,exist_ok=True)
    qemu,_=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    results=[]
    base=[sys.executable,str(Path(__file__).with_name('run_qemu.py')),
          '--qemu',str(qemu),'--soc-hw-version','0x60080201',
          '--devcfg',str(ROOT/'backups/nio-firmware-20260927T163534Z/devcfg_a.img'),
          '--secure-state-sample',str(ROOT/'reports/nio-scm-live-20260928-direct/manifest.json'),
          '--psci-version','0x10001','--smem-sample',str(ROOT/'reports/nio-smem-layout-20260928-v7/manifest.json'),
          '--smem-version-write','--smem-rlock-zero','--smem-mutex','--smem-ram-table-write',
          '--prng-word','0x736d656d','--gcc-mmu-clocks','off',
          '--smmu-ids',str(ROOT/'reports/nio-mmu-ids-active-20260928/manifest.json'),
          '--smmu-firmware-counts','--smmu-control','--smmu-contexts','--qcom-timer',
          '--qfprom-sample',str(ROOT/'reports/nio-gcc-mmu-checkpoint-20260928/manifest.json'),
          '--cmd-db-sample',str(ROOT/'reports/nio-cmd-db-pointer-20261005/manifest.json'),
          '--nonsecure-query-unsupported','--out','PLACEHOLDER']
    common=['--smem-toc-assign','--smem-partition-assign','--tz-channel-assign','--tz-channel-21-42-assign']
    pointer=['--tz-log-sample',str(ROOT/'reports/nio-tz-log-pointer-20261005/manifest.json')]
    cases=[('cmd-db',common+['--cmd-db-assign']),
           ('log-without-pointer',common+['--cmd-db-assign','--hyp-log-share']),
           ('pointer-without-publication',common+['--cmd-db-assign','--hyp-log-share']+pointer),
           ('complete-off',common+['--cmd-db-assign','--hyp-log-share']+pointer+['--imem-publications']),
           ('complete-on',common+['--cmd-db-assign','--hyp-log-share']+pointer+['--imem-publications'])]
    for name,options in cases:
        dest=out/name;cmd=base[:];cmd[cmd.index('--out')+1]=str(dest)
        if name.endswith('-on'):cmd[cmd.index('--gcc-mmu-clocks')+1]='on'
        subprocess.run(cmd+options,stdout=subprocess.DEVNULL,check=True)
        m=json.loads((dest/'manifest.json').read_text());stop=m['stop'] or {};text=m['stdout']
        if name=='cmd-db':
            inspection=dest/'inspection'
            subprocess.run([sys.executable,str(Path(__file__).with_name('inspect_assign_mem.py')),
                '--manifest',str(dest/'manifest.json'),'--skip','14','--out',str(inspection)],stdout=subprocess.DEVNULL,check=True)
            state=json.loads((inspection/'buffers.json').read_text())
            passed=(m['cmd_db_assign_model']['accepted_transitions']==1 and state['region']==[0x80209000,0x2000]
                and state['source_vmids']==[4] and [d['vmid'] for d in state['destinations']]==[3,4]
                and [d['permission'] for d in state['destinations']]==[4,6]
                and state['ledgers']['cmd_db_assign_ledger']['words']==[0x4440006e,0]
                and [f['return_pc'] for f in state['candidate_frame_chain']][-3:]==['0x80042290','0x8004410c','0x80040170'])
        elif name=='log-without-pointer':
            passed=(m['hyp_log_share_model']['accepted_transitions']==1
                and 'Failed to map TZ DIAG region to HLOS PT' in text and m['outcome']=='qhee_fatal_watchdog_request')
        elif name=='pointer-without-publication':
            passed=(m['hyp_log_share_model']['accepted_transitions']==0
                and 'NIO_IMEM_DENIED write offset=0xb30 size=8 value=0x200080209000' in m['stderr'])
        else:
            checkpoints=dest/'checkpoints'
            subprocess.run([sys.executable,str(Path(__file__).with_name('trace_init_tail.py')),
                '--manifest',str(dest/'manifest.json'),'--out',str(checkpoints)],stdout=subprocess.DEVNULL,check=True)
            c=json.loads((checkpoints/'manifest.json').read_text())['checkpoints']
            passed=(m['cmd_db_assign_model']['accepted_transitions']==m['hyp_log_share_model']['accepted_transitions']==1
                and m['imem_publications_model']['log_publications']==1
                and m['stderr'].count('NIO_TZ_LOG_POINTER_READ')==1
                and stop.get('qhee_fault')=={'address':'0xc440900','pc':'0x80060d40'}
                and 'Failed to map TZ DIAG' not in text
                and len(c)==8 and all(int(r['registers']['x0'],16)==0 for r in c)
                and c[-1]['registers']['x26']=='0xc440900' and c[-1]['registers']['x21']=='0x0')
        results.append({'case':name,'passed':passed,'manifest':str(dest/'manifest.json')})
    for option,error in [('--cmd-db-assign','requires --tz-channel-21-42-assign'),
                         ('--hyp-log-share','requires --cmd-db-assign'),
                         ('--imem-publications','requires --tz-log-sample')]:
        run=subprocess.run([sys.executable,str(Path(__file__).with_name('run_qemu.py')),option],capture_output=True,text=True)
        results.append({'case':option+'-dependency','passed':run.returncode==2 and error in run.stderr})
    report={'results':results,'scope':'Original QHEE reaches PMIC table read under explicit offline assumptions; no EL2 payload handoff or physical KVM',
        'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__),Path(__file__).with_name('trace_init_tail.py'),Path(__file__).with_name('inspect_assign_mem.py')]}}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):raise SystemExit('Init-tail regression failed')


if __name__=='__main__':main()
