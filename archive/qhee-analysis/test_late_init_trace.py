#!/usr/bin/env python3
"""Original QHEE: differential boundaries and read-only late-init ledgers."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from qhee import ROOT, QheeImage
from pmic_regions import inventory
from run_qemu import environment


def main():
    out=ROOT/'kernel-work/out/qhee-late-init-trace-tests';out.mkdir(parents=True,exist_ok=True)
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
    captures=[Path(apid[1]),Path(owners[1]),Path(secondary[1])]
    requests,_=inventory(QheeImage(),*captures)
    common+=apid+owners+secondary
    stages=[('maps-disabled',[],0xc2000c19,None),
        ('maps',['--pmic-region-map'],0x4200020e,None),
        ('pil',['--pmic-region-map','--pil-empty-region-list'],None,{'address':'0x146bfb20','pc':'0x800441cc'}),
        ('ready',['--pmic-region-map','--pil-empty-region-list','--imem-ready-publication'],0xc2000a02,None)]
    full=['--pmic-region-map','--pil-empty-region-list','--imem-ready-publication','--handoff-prng']
    stages += [('complete-off',full,0xc2000c1e,None),('complete-on',full,0xc2000c1e,None)]
    for name,options,fid,fault in stages:
        d=out/name;cmd=base[:];cmd[cmd.index('--out')+1]=str(d)
        if name.endswith('-on'):cmd[cmd.index('--gcc-mmu-clocks')+1]='on'
        subprocess.run(cmd+common+options,stdout=subprocess.DEVNULL,check=True)
        m=json.loads((d/'manifest.json').read_text());stop=m['stop'] or {}
        passed=stop.get('qhee_fault')==fault if fault else not stop.get('qhee_fault') and stop['registers']['x0']==hex(fid)
        passed=passed and m['outcome']==('qhee_fatal_watchdog_request' if fault else 'blocked_at_unmodeled_el3_exception') and 'NIO_PMIC_DENIED' not in m['stderr']
        if name!='maps-disabled':passed=passed and m['pmic_region_map_model']['accepted_requests']==241
        if name in ('pil','ready','complete-off','complete-on'):passed=passed and m['pil_empty_region_list_model']['accepted_queries']==1
        if name in ('ready','complete-off','complete-on'):passed=passed and m['imem_publications_model']['ready_publications']==1
        if name.startswith('complete'):
            checkpoint=d/'checkpoints'
            subprocess.run([sys.executable,str(Path(__file__).with_name('trace_init_tail.py')),'--manifest',str(d/'manifest.json'),
                '--through-late-scm','--out',str(checkpoint)],stdout=subprocess.DEVNULL,check=True)
            t=json.loads((checkpoint/'manifest.json').read_text());c=t['checkpoints'];last=c[-1]
            passed=passed and len(c)==16 and t['pmic_map_calls']==[list(r) for r in requests]
            passed=passed and [c[i]['name'] for i in (11,12,13,14,15)]==['pmic-init-return','before-ready-publication',
                'after-ready-publication','main-init-return','late-secure-monitor-call']
            passed=passed and c[11]['registers']['x0']=='0x0' and c[14]['registers']['x0']=='0xffffffff'
            passed=passed and last['late_prng_calls']==[[0x80095a60,4],[0x801ccaa8,2],[0x801ccaaa,2]]
            passed=passed and last['late_prng_words']==['0x736d656d']*2 and m['handoff_prng_model']['accepted_requests']==3
            passed=passed and last['model_counts']=={'pmic_region_map_count':241,'pil_empty_regions_count':1,'handoff_prng_count':3}
            passed=passed and last['pmic_map_ledger']==[6]*241 and 'NIO_IMEM_DENIED' not in m['stderr']
            passed=passed and [last['registers'][f'x{i}'] for i in range(8)]==['0xc2000c1e','0x4','0x800ab000','0x800ab004','0x1001a','0x0','0x0','0x0']
            passed=passed and last['bridge_region_first32_hex']=='00'*32
            passed=passed and [f['return_pc'] for f in last['candidate_frame_chain']]==['0x80048690','0x80054eec','0x80055034','0x800495a8','0x80040174']
        results.append({'case':name,'passed':bool(passed),'manifest':str(d/'manifest.json')})
    for option,error in [('--pmic-region-map','requires --pmic-secondary-sample and --hyp-log-share'),
        ('--pil-empty-region-list','requires --pmic-region-map'),
        ('--imem-ready-publication','requires --imem-publications and --pil-empty-region-list'),
        ('--handoff-prng','requires --prng-word')]:
        run=subprocess.run([sys.executable,str(Path(__file__).with_name('run_qemu.py')),option],capture_output=True,text=True)
        results.append({'case':option+'-dependency','passed':run.returncode==2 and error in run.stderr})
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        p=Path(tmp)/'altered.json'
        for index in range(3):
            report=json.loads(captures[index].read_text());report['scope']+=' altered provenance';p.write_text(json.dumps(report))
            altered=captures[:];altered[index]=p
            try:inventory(QheeImage(),*altered)
            except ValueError as e:passed='requires pinned' in str(e)
            else:passed=False
            results.append({'case':'reject-unpinned-'+str(index),'passed':passed})
        p.write_bytes(QheeImage().data[:-1]+b'\x01')
        try:inventory(QheeImage(p),*captures)
        except ValueError as e:passed='requires pinned' in str(e)
        else:passed=False
        results.append({'case':'reject-unpinned-hyp','passed':passed})
    report={'results':results,'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__),Path(__file__).with_name('trace_init_tail.py'),Path(__file__).with_name('pmic_regions.py')]},
        'scope':'Original firmware executes through main-init return but stops in the next helper before payload ERET. Finite map success and empty PIL list assumed; no physical EL2 handoff.'}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):raise SystemExit('Late-init trace regression failed')


if __name__=='__main__':main()
