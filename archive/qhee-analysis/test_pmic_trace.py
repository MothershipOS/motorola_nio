#!/usr/bin/env python3
"""Original-QHEE differential tests for the three bounded PMIC table replays."""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
from qhee import ROOT
from pmic import sample, owner_sample, secondary_sample
from run_qemu import environment


def main():
    out=ROOT/'kernel-work/out/qhee-pmic-trace-tests';out.mkdir(parents=True,exist_ok=True)
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
    expected_apid=[];expected_owners=[]
    a=struct.unpack('<512I',sample(Path(apid[1]))[0]);o=struct.unpack('<512I',owner_sample(Path(owners[1]))[0])
    for i,v in enumerate(a):
        expected_apid.append((0xc440900+4*i,v))
        if v&0xff00:
            expected_owners.append((0xc40a700+4*i,o[i]));expected_apid.append((0xc440900+4*i,v))
    expected_secondary=[(0xc442300+4*i,v) for i,v in enumerate(struct.unpack('<256I',secondary_sample(Path(secondary[1]))[0]))]
    for name,options,fault in [
        ('disabled',[],{'address':'0xc440900','pc':'0x80060d40'}),
        ('apid-only',apid,{'address':'0xc40a700','pc':'0x80061020'}),
        ('owners',apid+owners,{'address':'0xc442300','pc':'0x80060d98'}),
        ('complete-off',apid+owners+secondary,None),('complete-on',apid+owners+secondary,None)]:
        dest=out/name;cmd=base[:];cmd[cmd.index('--out')+1]=str(dest)
        if name.endswith('-on'):cmd[cmd.index('--gcc-mmu-clocks')+1]='on'
        subprocess.run(cmd+common+options,stdout=subprocess.DEVNULL,check=True)
        m=json.loads((dest/'manifest.json').read_text());stop=m['stop'] or {}
        def reads(kind):return [(int(a,16),int(v,16)) for a,v in re.findall('NIO_PMIC_'+kind+'_READ address=(0x[0-9a-f]+) value=(0x[0-9a-f]+) size=4',m['stderr'])]
        if fault:
            passed=stop.get('qhee_fault')==fault
            if name=='disabled':passed=passed and not reads('APID')
            if name=='apid-only':passed=passed and reads('APID')==expected_apid[:1] and not reads('OWNER')
            if name=='owners':passed=passed and reads('APID')==expected_apid and reads('OWNER')==expected_owners and not reads('SECONDARY')
        else:
            checkpoint=dest/'checkpoints'
            subprocess.run([sys.executable,str(Path(__file__).with_name('trace_init_tail.py')),'--manifest',str(dest/'manifest.json'),
                '--through-pmic-scm','--out',str(checkpoint)],stdout=subprocess.DEVNULL,check=True)
            c=json.loads((checkpoint/'manifest.json').read_text())['checkpoints'];call=c[-1]
            passed=(not stop.get('qhee_fault') and stop['registers']['x0']=='0xc2000c19'
                and reads('APID')==expected_apid and reads('OWNER')==expected_owners and reads('SECONDARY')==expected_secondary
                and 'NIO_PMIC_DENIED' not in m['stderr'] and 'NIO_IMEM_DENIED' not in m['stderr']
                and len(c)==12 and c[-2]['pmic_descriptor_u16'][0]==512 and c[-2]['pmic_descriptor_u16'][7]==256
                and [call['registers'][f'x{i}'] for i in range(8)]==['0xc2000c19','0x5','0xccf0000','0xcd00000','0x2','0x801cc390','0x0','0x0']
                and call['extended_words'][:2]==['0x6','0x1']
                and [f['return_pc'] for f in call['candidate_frame_chain']]==['0x80048690','0x80067acc','0x8005ff68','0x80044160','0x80040170'])
        results.append({'case':name,'passed':passed,'manifest':str(dest/'manifest.json')})
    for option,error in [('--pmic-owner-sample','requires --pmic-arb-sample'),('--pmic-secondary-sample','requires --pmic-owner-sample')]:
        run=subprocess.run([sys.executable,str(Path(__file__).with_name('run_qemu.py')),option,'unused'],capture_output=True,text=True)
        results.append({'case':option+'-dependency','passed':run.returncode==2 and error in run.stderr})
    report={'results':results,'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__),Path(__file__).with_name('trace_init_tail.py')]},
        'scope':'Exact measured PMIC metadata advances original QHEE to unmodeled SCM 0xc2000c19; not successful physical TZ acceptance or EL2 handoff.'}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in results:print(r['case'],'PASS' if r['passed'] else 'FAIL')
    if not all(r['passed'] for r in results):raise SystemExit('PMIC trace regression failed')


if __name__=='__main__':main()
