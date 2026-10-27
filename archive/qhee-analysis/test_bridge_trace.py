#!/usr/bin/env python3
"""Original QHEE full cold handoff: bridge lifecycle, ERET, stage-2 and payload."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
from qhee import ROOT, QheeImage
from pmic_regions import inventory
from run_qemu import environment


def main():
    out=ROOT/'kernel-work/out/qhee-bridge-trace-tests';out.mkdir(parents=True,exist_ok=True)
    qemu,_=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64');results=[]
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
    common=['--smem-toc-assign','--smem-partition-assign','--tz-channel-assign','--tz-channel-21-42-assign',
        '--cmd-db-assign','--hyp-log-share','--tz-log-sample',str(ROOT/'reports/nio-tz-log-pointer-20261005/manifest.json'),'--imem-publications']
    apid=['--pmic-arb-sample',str(ROOT/'reports/nio-pmic-arbiter-20261005/manifest.json')]
    owners=['--pmic-owner-sample',str(ROOT/'reports/nio-pmic-owners-20261005/manifest.json')]
    secondary=['--pmic-secondary-sample',str(ROOT/'reports/nio-pmic-secondary-map-20261005/manifest.json')]
    common+=apid+owners+secondary+['--pmic-region-map','--pil-empty-region-list','--imem-ready-publication','--handoff-prng']
    requests,_=inventory(QheeImage(),Path(apid[1]),Path(owners[1]),Path(secondary[1]))
    handle=0x53484d0000000001;word=0x736d656d736d656d
    both=['--shm-bridge-handle',hex(handle),'--bridge-prng-word',hex(word)]
    cases=[('disabled',[],handle,word),('bridge-only',['--shm-bridge-handle',hex(handle)],handle,word)]
    cases += [(f'{target}-target-{clock}',both+(['--payload-address','0x90000000'] if target=='ram' else []),handle,word)
              for target in ('old','ram') for clock in ('off','on')]
    cases += [('alternate-handle', ['--shm-bridge-handle','0xfedcba9876543210','--bridge-prng-word','0',
        '--payload-address','0x90000000'],0xfedcba9876543210,0)]
    for name,options,h,w in cases:
        d=out/name;cmd=base[:];cmd[cmd.index('--out')+1]=str(d)
        if name.endswith('-on'):cmd[cmd.index('--gcc-mmu-clocks')+1]='on'
        subprocess.run(cmd+common+options,stdout=subprocess.DEVNULL,check=True)
        m=json.loads((d/'manifest.json').read_text());stop=m['stop']
        if name=='disabled':passed=m['outcome']=='blocked_at_unmodeled_el3_exception' and stop['registers']['x0']=='0xc2000c1e'
        elif name=='bridge-only':passed=m['outcome']=='blocked_at_unmodeled_el3_exception' and [stop['registers'][f'x{i}'] for i in range(4)]==['0xc2000a02','0x22','0x800ab090','0x8'] and m['shm_bridge_model']['accepted_creates']==1
        else:
            ram=not name.startswith('old');target=0x90000000 if ram else 0x40400000
            passed=(m['outcome']=='synthetic_probe_reached' and m['exit']==0 and m['status']=='exited' and stop is None and m['stderr'].splitlines()[-1]=='EL1') if ram else (
                m['outcome']=='qhee_fatal_watchdog_request' and stop['qhee_fault']=={'address':'0x40400000','pc':'0x40400000'})
            trace=d/'checkpoints'
            subprocess.run([sys.executable,str(Path(__file__).with_name('trace_bridge_handoff.py')),'--manifest',str(d/'manifest.json'),
                '--out',str(trace)],stdout=subprocess.DEVNULL,check=True)
            t=json.loads((trace/'manifest.json').read_text());c=t['checkpoints'];pre=c[-1]['registers'];post=t['after_eret'];fetch=t['after_first_fetch']
            passed=passed and len(c)==8 and c[0]['service_and_handle']==['0x0',hex(h)] and c[1]['stored_handle']==hex(h) and c[2]['stored_handle']==hex(h)
            node=struct.unpack('<9Q',bytes.fromhex(c[3]['bridge_bookkeeping_node_hex']))
            passed=passed and node[1:3]==(0x10000,0x800ab000) and node[7]==h and t['bridge_record_handle_before_eret']==hex(h)
            passed=passed and c[5]['stack_canary']==hex(w) and t['shm_bridge_ledger']==[1,0x800ab000,0x800ab004,0x1001a,0,h]
            passed=passed and t['model_counts']=={'bridge_prng_count':1,'pmic_region_map_count':241,'handoff_prng_count':3,'pil_empty_regions_count':1} and t['pmic_map_ledger']==[6]*241
            maps=[call for call in t['calls'] if call['args'][0]=='0xc2000c19']
            passed=passed and [[int(v,16) for v in call['args'][2:5]]+call['extended'] for call in maps]==[list(r) for r in requests]
            bridges=[call['args'] for call in t['calls'] if call['args'][0]=='0xc2000c1e']
            passed=passed and bridges==[['0xc2000c1e','0x4','0x800ab000','0x800ab004','0x1001a','0x0','0x0','0x0']]
            prng=[call['args'][2:4] for call in t['calls'] if call['args'][0]=='0xc2000a02']
            passed=passed and prng==[[hex(a),hex(n)] for a,n in ((0x80095a60,4),(0x801ccaa8,2),(0x801ccaaa,2),(0x800ab090,8))]
            passed=passed and not any(call['args'][0]=='0xc2000c1d' for call in t['calls'])
            passed=passed and all(pre[f'x{i}']=='0x0' for i in range(31)) and pre['SPSR_EL2']=='0x85' and pre['ELR_EL2']==hex(target)
            passed=passed and pre['HCR_EL2']=='0x80080005' and pre['SCTLR_EL2']=='0x8100f' and pre['VTCR_EL2']=='0x8001355c'
            passed=passed and post['pc']==hex(target) and post['cpsr']=='0x85'
            passed=passed and (fetch['pc']=='0x90000004' and fetch['cpsr']=='0x85' and fetch['ESR_EL2']=='0x0' if ram else
                fetch['pc']=='0x80093400' and fetch['ESR_EL2']=='0x8200000e' and fetch['FAR_EL2']=='0x40400000')
            passed=passed and [walk['entries'][-1]['pte'] for walk in t['stage2_walks']]==['0x500000404004c5','0x100000900004fd']
            passed=passed and m['shm_bridge_model']['accepted_creates']==1 and m['bridge_prng_model']['accepted_requests']==1 and ([line for line in m['stderr'].splitlines() if 'NIO_IMEM_DENIED' in line]==([] if ram else ['NIO_IMEM_DENIED read offset=0x10 size=8']))
        results.append({'case':name,'passed':bool(passed),'manifest':str(d/'manifest.json')})
    invalid=[(['--shm-bridge-handle','0'],'nonzero uint64'),(['--shm-bridge-handle','-1'],'nonzero uint64'),
        (['--shm-bridge-handle','0x10000000000000000'],'nonzero uint64'),(['--shm-bridge-handle','1'],'requires --handoff-prng'),
        (['--bridge-prng-word','-1'],'must be a uint64'),(['--bridge-prng-word','0x10000000000000000'],'must be a uint64'),
        (['--bridge-prng-word','0'],'requires --shm-bridge-handle'),(['--payload-address','0x90000004'],'invalid choice')]
    for i,(options,error) in enumerate(invalid):
        run=subprocess.run([sys.executable,str(Path(__file__).with_name('run_qemu.py'))]+options,capture_output=True,text=True)
        results.append({'case':'CLI-invalid-'+str(i),'passed':run.returncode==2 and error in run.stderr})
    report={'results':results,'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__),Path(__file__).with_name('trace_bridge_handoff.py'),Path(__file__).with_name('run_qemu.py')]},
        'scope':'Original full cold initialization and stock EL1 payload handoff under explicit synthetic models. No real boot-chain target, firmware acceptance, Linux EL2 handoff or physical KVM execution established.'}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):raise SystemExit('Bridge/full-handoff trace regression failed')


if __name__=='__main__':main()
