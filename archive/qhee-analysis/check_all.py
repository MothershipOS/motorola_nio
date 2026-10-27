#!/usr/bin/env python3
"""Run independent offline suites and record their results and evidence hashes."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from qhee import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'reports/qhee-offline/entry-regressions')
    out=p.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=True)
    def run(path):
        log=out/(path.stem+'.txt')
        r=subprocess.run([sys.executable,str(path)],cwd=ROOT,capture_output=True,text=True,timeout=240)
        log.write_text(r.stdout+r.stderr);match=re.search(r'Ran (\d+) tests',r.stderr)
        if match:count=int(match[1])
        elif path.stem in ('test_handoff','test_secure_call'):
            report=ROOT/('kernel-work/out/qhee-slices/results.json' if path.stem=='test_handoff' else 'kernel-work/out/qhee-secure-call-tests/results.json')
            count=len(json.loads(report.read_text())['results'])
        else:count=sum(bool(re.search(r'\bPASS\b',line)) for line in r.stdout.splitlines())
        return {'suite':path.stem.removeprefix('test_'),'checks':count,'passed':r.returncode==0 and count>0,
            'evidence':str(log.relative_to(ROOT)) if log.is_relative_to(ROOT) else str(log),
            'sha256':hashlib.sha256(log.read_bytes()).hexdigest(),
            'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    results=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run,path) for path in sorted(Path(__file__).parent.glob('test_*.py'))]
        for future in as_completed(futures):
            result=future.result();results.append(result)
            print(result['suite'],result['checks'],'PASS' if result['passed'] else 'FAIL',flush=True)
    path=Path(__file__).with_name('inspect_qhee_mmu.py');log=out/'inspect_qhee_mmu.txt'
    r=subprocess.run([sys.executable,str(path),'--out',str(out/'mmu-inspection')],cwd=ROOT,capture_output=True,text=True,timeout=45)
    log.write_text(r.stdout+r.stderr)
    checks=json.loads((out/'mmu-inspection/inspection.json').read_text())['checks'] if r.returncode==0 else {}
    result={'suite':'mmu_inspection','checks':len(checks),'passed':r.returncode==0 and bool(checks) and all(checks.values()),
        'evidence':str(log.relative_to(ROOT)) if log.is_relative_to(ROOT) else str(log),'sha256':hashlib.sha256(log.read_bytes()).hexdigest(),
        'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    results.append(result);print('mmu_inspection',len(checks),'PASS' if result['passed'] else 'FAIL',flush=True)
    report={'suites':sorted(results,key=lambda r:r['suite']),'total_checks':sum(r['checks'] for r in results),
        'passed':all(r['passed'] for r in results),'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    if not report['passed']:raise SystemExit('Offline regression failed')


if __name__=='__main__':main()
