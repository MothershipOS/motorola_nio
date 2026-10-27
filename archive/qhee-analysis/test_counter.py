#!/usr/bin/env python3
"""Original virtual counter/conversion and bounded platform-selection fault tracing."""
import hashlib,json,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
from qhee import ROOT
from xbl_counter import contract,convert,slice_convert,POINTS,STOP,FREQUENCY
from xbl_readiness import SAMPLE
from xbl_target import payload
from xbl_canary import reply_model
from test_entry import complete_args

class CounterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'kernel-work/out/qhee-counter-tests';cls.out.mkdir(exist_ok=True)
        cls.runner=Path(__file__).with_name('run_qemu.py');cls.tracer=Path(__file__).with_name('trace_bridge_handoff.py');cls.contract=contract();cls.cases=[];cls.traces=[]
        cls.pins={n:hashlib.sha256((ROOT/'backups/nio-firmware-20260927T163534Z'/n).read_bytes()).hexdigest() for n in ('hyp_a.img','tz_a.img','xbl_a.img','devcfg_a.img','abl_a.img')}
        for profile in ('synthetic-masked','tz-frame-hcr-zero','tz-frame-hcr-rw'):
            for clock in (('off',) if profile=='synthetic-masked' else ('off','on')):
                for el2 in (False,True):
                    d=cls.out/(profile+'-'+clock+'-'+('el2' if el2 else 'stock'));a=complete_args(clock,d);a[a.index('--payload-address')+1]='0x9fc00000'
                    a+=['--prepare-only','--xbl-workspace-sentinel','--xbl-query-reply','--xbl-buffer-reply','--xbl-canary-reply','--xbl-readiness-sample',str(SAMPLE),'--entry-state-model',profile]
                    if el2:a+=['--handoff-experiment','el2-xbl-masked-mmu-off']
                    subprocess.run([sys.executable,str(cls.runner)]+a,check=True,stdout=subprocess.DEVNULL)
                    subprocess.run([sys.executable,str(cls.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace'),'--xbl-counter','--inspect-xbl-next-step'],check=True,stdout=subprocess.DEVNULL)
                    c={'profile':profile,'clock':clock,'el2':el2,'manifest':str(d/'manifest.json'),'trace':str(d/'trace/manifest.json')};cls.cases.append(c);cls.traces.append((c,json.loads(Path(c['trace']).read_text())))
        (cls.out/'results.json').write_text(json.dumps(cls.cases,indent=2)+'\n')

    def test_original_windows_and_fixed_frequency_reject_changed_code(self):
        b,m=payload();self.assertEqual(self.contract['fv_sha256'],m['segment_sha256']);self.assertEqual(self.contract['frequency'],FREQUENCY)
        for w in self.contract['windows'].values():
            a=int(w['address'],16)-0x9fc00000;self.assertEqual(w['sha256'],hashlib.sha256(b[a:a+w['size']]).hexdigest())
        for offset in (0x2bb48,0x19be8,0x22850,0x2a150,0x2f2e4):
            changed=bytearray(b);changed[offset:offset+4]=bytes.fromhex('1f2003d5')
            with patch('xbl_counter.payload',return_value=(bytes(changed),m)):
                with self.assertRaises(ValueError):contract()

    def test_original_conversion_boundary_and_wraparound_slices(self):
        values=(0,1,FREQUENCY-1,FREQUENCY,FREQUENCY+1,0xffffffff,1<<32,(1<<64)-1)
        results=[slice_convert(v) for v in values]
        for v,r in zip(values,results):
            self.assertEqual(int(r['result'],16),convert(v));self.assertEqual(r['sp'],'0x9000f000')
            self.assertEqual(convert(v),(v*1000000000//FREQUENCY)&((1<<64)-1))
        self.assertEqual(convert(FREQUENCY),1000000000)
        (self.out/'conversion-slices.json').write_text(json.dumps(results,indent=2)+'\n')

    def test_conversion_rejects_invalid_inputs(self):
        for value in (-1,1<<64,True,1.5,'1'):
            with self.assertRaises(ValueError):convert(value)
        for freq in (0,-1,1<<32,True):
            with self.assertRaises(ValueError):convert(1,freq)

    def test_ten_original_counter_frequency_conversion_and_storage_paths(self):
        for c,t in self.traces:
            p={v['name']:v for v in t['xbl_prefix_checkpoints']};ticks=int(p['sec-counter-read-complete']['counter_ticks'],16);expected=hex(convert(ticks))
            self.assertGreater(ticks,0);self.assertEqual(p['sec-fixed-frequency-return']['frequency'],FREQUENCY);self.assertEqual(p['sec-frequency-observed']['frequency'],FREQUENCY)
            self.assertEqual(p['sec-counter-converted']['converted_value'],expected);self.assertEqual(p['sec-counter-converted']['expected_value'],expected)
            for pc,name in POINTS.items():
                v=p[name];self.assertEqual(v['registers']['pc'],hex(pc))
                self.assertEqual(v['timer_controls'],p['sec-counter-read-complete']['timer_controls']);self.assertTrue(v['frequency_mismatch'])
                self.assertEqual(v['timer_controls']['CNTFRQ_EL0'],hex(62500000));self.assertEqual(v['timer_controls']['CNTVOFF_EL2'],'0x0');self.assertEqual(v['timer_controls']['CNTHCTL_EL2'],'0x3')
                if 'stored_value' in v:self.assertEqual(v['stored_value'],expected)
            self.assertEqual(p['sec-counter-converted']['registers']['sp'],'0x9ffcfbc0')

    def test_simd_descriptor_copy_and_next_exact_mmio_dependency(self):
        for c,t in self.traces:
            p={v['name']:v for v in t['xbl_prefix_checkpoints']}
            self.assertEqual(p['sec-simd-load-complete']['registers']['pc'],'0x9fc22854')
            self.assertEqual(p['sec-init-descriptor-copied']['descriptor_copy_hex'],self.contract['descriptor_copy']['expected_hex'])
            last=t['xbl_prefix_checkpoints'][-1];self.assertEqual(last['registers']['pc'],hex(STOP));self.assertEqual(last['registers']['x8'],'0x1fc8004');self.assertEqual(last['registers']['sp'],'0x9ffcfaa0')
            self.assertEqual(last['pending_access'],{**self.contract['next_access'],'executed':False})
            step=t['xbl_next_access_step'];bank='EL2' if c['el2'] else 'EL1'
            self.assertEqual(step['destination'],'mmio-data-abort-'+bank.lower());self.assertEqual(step['syndrome'],'0x96000010');self.assertFalse(step['handler_executed']);self.assertFalse(step['instruction_executed'])
            self.assertEqual(step['after']['FAR_'+bank],'0x1fc8004');self.assertEqual(step['after']['ELR_'+bank],hex(STOP));self.assertEqual(step['after']['pc'],'0x9ff8c200');self.assertEqual(step['after']['sp'],last['registers']['sp'])

    def test_el_cache_masks_canary_ledgers_and_original_cold_calls_preserved(self):
        for c,t in self.traces:
            p={v['name']:v for v in t['xbl_prefix_checkpoints']};base=p['sec-dcache-enabled']['registers']
            for name in POINTS.values():
                v=p[name]
                for bank in ('SCTLR','SCTLR_EL2','HCR_EL2'):self.assertEqual(v['registers'][bank],base[bank])
                self.assertEqual(int(v['registers']['cpsr'],16)&0x3cf,int(base['cpsr'],16)&0x3cf)
                self.assertEqual(v['canary_word'],reply_model()['buffer_word']);self.assertEqual((v['query_reply_count'],v['buffer_reply_count'],v['canary_reply_count']),(1,1,1))
                for rr in v['workspace_after']:self.assertEqual(rr['guard_before_hex'],rr['guard_after_hex']);self.assertEqual(rr['guard_after_hex'],'a5'*16)
            self.assertEqual(t['calls'],self.traces[0][1]['calls']);self.assertEqual(len(t['calls']),263);self.assertEqual(t['pmic_map_ledger'],[6]*241);self.assertEqual(len(t['xbl_forward_calls']),0 if c['el2'] else 2)
            self.assertEqual((Path(c['trace']).parent/'stderr.txt').read_text().count('NIO_SEC_FLAG_READ'),1)

    def test_cli_bound_dependencies_and_missing_or_altered_sample_rejected(self):
        r=subprocess.run([sys.executable,str(self.tracer),'--manifest',self.cases[-1]['manifest'],'--out',str(self.out/'bad-options'),'--inspect-xbl-next-step'],capture_output=True,text=True);self.assertEqual(r.returncode,2);self.assertIn('requires --xbl-counter',r.stderr)
        p=Path(self.cases[-1]['manifest']);data=p.read_bytes();m=json.loads(data)
        try:
            for key in ('xbl_readiness_sample','xbl_canary_reply_model'):
                n=json.loads(data);n[key]=None;p.write_text(json.dumps(n));r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(p),'--out',str(self.out/'bad-options'),'--xbl-counter'],capture_output=True,text=True);self.assertEqual(r.returncode,2)
            n=json.loads(data);n['xbl_readiness_sample']['value']='0x0';p.write_text(json.dumps(n));r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(p),'--out',str(self.out/'bad-options'),'--xbl-counter'],capture_output=True,text=True);self.assertEqual(r.returncode,2);self.assertIn('metadata mismatch',r.stderr)
        finally:p.write_bytes(data)

    def test_earlier_counter_bound_and_default_unstepped_mmio_controls(self):
        controls=[]
        for c in self.cases[-2:]:
            for flag,name,stop in (('--xbl-readiness','before-counter','0x9fc2bb48'),('--xbl-counter','before-mmio',hex(STOP))):
                d=Path(c['manifest']).parent/name;subprocess.run([sys.executable,str(self.tracer),'--manifest',c['manifest'],'--out',str(d),flag],check=True,stdout=subprocess.DEVNULL)
                r=json.loads((d/'manifest.json').read_text());self.assertEqual(r['xbl_prefix_checkpoints'][-1]['registers']['pc'],stop);self.assertNotIn('xbl_next_access_step',r)
                if flag=='--xbl-readiness':self.assertNotIn('xbl_counter_contract',r);self.assertEqual(r['xbl_prefix_checkpoints'][-1]['pending_counter'],{'register':'CNTVCT_EL0','executed':False})
                controls.append(str(d/'manifest.json'))
        (self.out/'earlier-controls.json').write_text(json.dumps(controls,indent=2)+'\n')

    def test_current_provenance_and_unchanged_firmware(self):
        for c,t in self.traces:
            p=Path(c['manifest']);m=json.loads(p.read_text());self.assertEqual(t['xbl_counter_contract'],self.contract)
            self.assertEqual(t['input_manifest_sha256'],hashlib.sha256(p.read_bytes()).hexdigest());self.assertEqual(t['tool_sha256'],hashlib.sha256(self.tracer.read_bytes()).hexdigest());self.assertEqual(t['el3_sha256'],hashlib.sha256((p.parent/'el3.elf').read_bytes()).hexdigest())
            for path,h in m['tool_sha256'].items():self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),h)
        for n,h in self.pins.items():self.assertEqual(hashlib.sha256((ROOT/'backups/nio-firmware-20260927T163534Z'/n).read_bytes()).hexdigest(),h)

if __name__=='__main__':unittest.main()
