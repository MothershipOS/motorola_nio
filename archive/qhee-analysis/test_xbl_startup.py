#!/usr/bin/env python3
"""Original SEC writes and temporary stack after full modeled QHEE, EL1/EL2."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
from qhee import ROOT
from test_entry import complete_args
from xbl_startup import contract, sentinel, sentinel_metadata, STOP
from xbl_target import payload


class XblStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'kernel-work/out/qhee-xbl-startup-tests';cls.out.mkdir(parents=True,exist_ok=True)
        cls.runner=Path(__file__).with_name('run_qemu.py');cls.tracer=Path(__file__).with_name('trace_bridge_handoff.py')
        cls.firmware=ROOT/'backups/nio-firmware-20260927T163534Z'
        cls.before={name:hashlib.sha256((cls.firmware/name).read_bytes()).hexdigest() for name in ('hyp_a.img','xbl_a.img','tz_a.img','devcfg_a.img')}
        cls.cases=[]
        for profile in ('synthetic-masked','tz-frame-hcr-zero','tz-frame-hcr-rw'):
            for clock in (('off',) if profile=='synthetic-masked' else ('off','on')):
                for el2 in (False,True):
                    poison=profile!='synthetic-masked'
                    d=cls.out/(profile+'-'+clock+'-'+('el2' if el2 else 'stock'))
                    args=complete_args(clock,d);args[args.index('--payload-address')+1]='0x9fc00000'
                    args+=['--prepare-only','--entry-state-model',profile]
                    if el2:args+=['--handoff-experiment','el2-xbl-masked-mmu-off']
                    if poison:args+=['--xbl-workspace-sentinel']
                    subprocess.run([sys.executable,str(cls.runner)]+args,check=True,stdout=subprocess.DEVNULL)
                    subprocess.run([sys.executable,str(cls.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace'),'--xbl-startup'],check=True,stdout=subprocess.DEVNULL)
                    cls.cases.append({'profile':profile,'clock':clock,'el2':el2,'sentinel':poison,
                                      'manifest':str(d/'manifest.json'),'trace':str(d/'trace/manifest.json')})
        (cls.out/'results.json').write_text(json.dumps(cls.cases,indent=2)+'\n')
        cls.traces=[(c,json.loads(Path(c['trace']).read_text())) for c in cls.cases]

    def test_pinned_workspace_contract(self):
        c=contract();b,m=payload()
        self.assertEqual(c['firmware_sha256'],m['firmware_sha256']);self.assertEqual(c['stop_before'],hex(STOP))
        for w in c['windows'].values():
            off=int(w['address'],16)-0x9fc00000
            self.assertEqual(w['sha256'],hashlib.sha256(b[off:off+w['size']]).hexdigest())
        self.assertEqual(c['windows']['workspace']['instructions'][-1],{'address':'0x9fc0cf28','mnemonic':'bl','operands':'#0x9fc21ce8'})
        changed=bytearray(b);changed[0xcd68]^=1
        with patch('xbl_startup.payload',return_value=(bytes(changed),m)):
            with self.assertRaisesRegex(ValueError,'workspace literals'):contract()

    def test_original_stores_replace_sentinels(self):
        for case,t in self.traces:
            with self.subTest(case=case):
                self.assertEqual(t['xbl_startup_contract'],contract())
                pre=t['xbl_workspace_before'];post=t['xbl_prefix_checkpoints'][-1]['workspace_after']
                for before,after in zip(pre,post):
                    if case['sentinel']:
                        self.assertEqual(before['sha256'],hashlib.sha256(bytes([0xa5])*before['size']).hexdigest())
                        self.assertNotEqual(before['sha256'],after['sha256'])
                    expected=struct.pack('<Q',0xaa0403f314000000)*256 if after['name']=='vectors' else bytes(0x40000)
                    self.assertEqual(after['sha256'],hashlib.sha256(expected).hexdigest())
                points={p['name']:p for p in t['xbl_prefix_checkpoints']}
                self.assertEqual(points['sec-vectors-filled']['timestamp'],points['sec-vectors-filled']['registers']['x19'])
                self.assertEqual(points['sec-vectors-filled']['vectors_sha256'],post[0]['sha256'])
                self.assertEqual(points['sec-bss-cleared']['bss_sha256'],post[1]['sha256'])

    def test_write_guards_and_temporary_stack(self):
        for case,t in self.traces:
            final=t['xbl_prefix_checkpoints'][-1]
            self.assertEqual(final['registers']['pc'],'0x9fc0cf28');self.assertEqual(final['registers']['sp'],'0x9ffd0000')
            self.assertEqual(final['registers']['x0'],'0x40000');self.assertEqual(final['registers']['x2'],'0x9ffd0000')
            for region in final['workspace_after']:
                expected=('a5' if case['sentinel'] else '00')*16
                self.assertEqual(region['guard_before_hex'],expected);self.assertEqual(region['guard_after_hex'],expected)
        regions=sentinel();self.assertEqual(len(regions),2)
        self.assertTrue(all(a>=0x9ff00000 for a,_,_ in regions))
        self.assertLess(regions[0][0]+len(regions[0][1]),regions[1][0])

    def test_el1_el2_and_simd_controls(self):
        for case,t in self.traces:
            for p in t['xbl_prefix_checkpoints']:
                r=p['registers'];self.assertEqual(int(r['cpsr'],16)&15,9 if case['el2'] else 5)
                self.assertEqual(r['ESR_EL2'],'0x0');self.assertEqual(r['CPTR_EL2'],'0x33ff')
                if case['el2']:
                    self.assertEqual(int(r['cpsr'],16)&0x3c0,0x3c0);self.assertEqual(r['SCTLR_EL2'],'0x8000a')
            p={p['name']:p['registers'] for p in t['xbl_prefix_checkpoints']}
            self.assertEqual(p['sec-before-simd-zero']['CPACR'],'0x300000')
            self.assertEqual(int(p['sec-mpidr-read']['x4'],16)&0xff00,0)
            self.assertEqual(p['sec-temporary-stack-ready']['HCR_EL2'],'0x10' if case['el2'] else '0x80080005')
            if case['el2']:self.assertEqual(p['sec-temporary-stack-ready']['VBAR_EL2'],'0x9ff8c000')

    def test_entry_and_cold_ledgers_unchanged(self):
        baseline=self.traces[0][1]
        for case,t in self.traces:
            self.assertEqual(t['calls'],baseline['calls']);self.assertEqual(t['pmic_map_ledger'],[6]*241)
            self.assertEqual(t['bridge_record_handle_before_eret'],'0x53484d0000000001')
            self.assertEqual(t['model_counts'],{'bridge_prng_count':1,'pmic_region_map_count':241,'handoff_prng_count':3,'pil_empty_regions_count':1})
            if case['profile']!='synthetic-masked':
                r=t['entry_state_inspection']['initial_qhee_entry']
                self.assertEqual(r['SCR_EL3'],'0x535');self.assertEqual(r['SCTLR_EL2'],'0x0')
                self.assertEqual(int(r['cpsr'],16)&0x3cf,0x89)
                self.assertEqual(r['HCR_EL2'],'0x0' if case['profile']=='tz-frame-hcr-zero' else '0x80000000')

    def test_legacy_prefix_still_stops_before_writes(self):
        case=self.cases[-1];out=Path(case['manifest']).parent/'legacy-prefix'
        subprocess.run([sys.executable,str(self.tracer),'--manifest',case['manifest'],'--out',str(out),'--xbl-prefix'],check=True,stdout=subprocess.DEVNULL)
        t=json.loads((out/'manifest.json').read_text());self.assertEqual(t['xbl_prefix_checkpoints'][-1]['registers']['pc'],'0x9fc0ceb4')
        self.assertEqual(len(t['xbl_prefix_checkpoints']),7);self.assertNotIn('xbl_startup_contract',t)
        self.assertIn('monitor quit',(out/'trace.gdb').read_text());self.assertNotIn('\ndetach\n',(out/'trace.gdb').read_text())

    def test_cli_gates(self):
        r=subprocess.run([sys.executable,str(self.runner),'--xbl-workspace-sentinel'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2);self.assertIn('requires original XBL',r.stderr)
        r=subprocess.run([sys.executable,str(self.tracer),'--manifest',self.cases[0]['manifest'],'--out',str(self.out/'bad-cli'),'--xbl-prefix','--xbl-startup'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2);self.assertIn('not allowed with',r.stderr)

    def test_sentinel_tampering_rejected_before_execution(self):
        source=Path(self.cases[-1]['manifest']);original=source.read_bytes();m=json.loads(original)
        def reject(message):
            r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(source),'--out',str(source.parent/'tampered-trace'),'--xbl-startup'],capture_output=True,text=True)
            self.assertEqual(r.returncode,2);self.assertIn(message,r.stderr)
        try:
            m['xbl_workspace_sentinel']['regions'][0]['sha256']='0'*64;source.write_text(json.dumps(m));reject('sentinel metadata mismatch')
            m=json.loads(original);m['command']=[p for p in m['command'] if 'xbl-workspace-vectors.bin' not in p]
            source.write_text(json.dumps(m));reject('sentinel loader')
            m=json.loads(original);m['xbl_workspace_sentinel']=None;source.write_text(json.dumps(m));reject('Unreported XBL workspace')
            source.write_bytes(original);p=source.parent/'xbl-workspace-bss.bin';data=p.read_bytes()
            try:p.write_bytes(b'changed');reject('sentinel bytes')
            finally:p.write_bytes(data)
        finally:source.write_bytes(original)
        self.assertEqual(sentinel_metadata()['regions'][1]['size'],0x40020)

    def test_evidence_and_firmware_immutability(self):
        for case,t in self.traces:
            path=Path(case['manifest']);m=json.loads(path.read_text())
            self.assertEqual(t['input_manifest_sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(t['tool_sha256'],hashlib.sha256(self.tracer.read_bytes()).hexdigest())
            self.assertEqual(t['el3_sha256'],hashlib.sha256((path.parent/'el3.elf').read_bytes()).hexdigest())
            self.assertEqual(m['tool_sha256']['tools/hyp_re/xbl_startup.py'],contract()['source_sha256'])
            self.assertEqual(m['status'],'prepared');self.assertEqual(m['outcome'],'prepared_not_executed')
            self.assertEqual(t['xbl_workspace_sentinel'],sentinel_metadata() if case['sentinel'] else None)
        for name,before in self.before.items():self.assertEqual(hashlib.sha256((self.firmware/name).read_bytes()).hexdigest(),before)


if __name__=='__main__':unittest.main()
