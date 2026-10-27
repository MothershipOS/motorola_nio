#!/usr/bin/env python3
"""Original SEC cache startup and second canary request, without a second reply."""
import hashlib,json,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
from qhee import ROOT
from xbl_cache import contract,geometry,POINTS
from xbl_target import payload
from tz_buffer import run,reply_model
from test_entry import complete_args

class CacheStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'kernel-work/out/qhee-cache-startup-tests';cls.out.mkdir(exist_ok=True)
        cls.runner=Path(__file__).with_name('run_qemu.py');cls.tracer=Path(__file__).with_name('trace_bridge_handoff.py')
        cls.cache=contract();cls.reply=reply_model();cls.cases=[];cls.traces=[]
        cls.pins={n:hashlib.sha256((ROOT/'backups/nio-firmware-20260927T163534Z'/n).read_bytes()).hexdigest() for n in ('hyp_a.img','tz_a.img','xbl_a.img','devcfg_a.img','abl_a.img')}
        for profile in ('synthetic-masked','tz-frame-hcr-zero','tz-frame-hcr-rw'):
            for clock in (('off',) if profile=='synthetic-masked' else ('off','on')):
                for el2 in (False,True):
                    d=cls.out/(profile+'-'+clock+'-'+('el2' if el2 else 'stock'))
                    a=complete_args(clock,d);a[a.index('--payload-address')+1]='0x9fc00000'
                    a+=['--prepare-only','--xbl-workspace-sentinel','--xbl-query-reply','--xbl-buffer-reply','--entry-state-model',profile]
                    if el2:a+=['--handoff-experiment','el2-xbl-masked-mmu-off']
                    subprocess.run([sys.executable,str(cls.runner)]+a,check=True,stdout=subprocess.DEVNULL)
                    a=[sys.executable,str(cls.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace'),'--xbl-cache-startup','--inspect-xbl-smc-route']
                    if not el2:a+=['--inspect-xbl-qhee-forward']
                    subprocess.run(a,check=True,stdout=subprocess.DEVNULL)
                    c={'profile':profile,'clock':clock,'el2':el2,'manifest':str(d/'manifest.json'),'trace':str(d/'trace/manifest.json')}
                    t=json.loads(Path(c['trace']).read_text());cls.cases.append(c);cls.traces.append((c,t))
                    regs=t['xbl_prefix_checkpoints'][-1]['registers'] if el2 else t['xbl_qhee_handler']['registers']
                    (d/'tz-buffer-slices.json').write_text(json.dumps(run([int(regs['x'+str(i)],16) for i in range(14)]),indent=2)+'\n')
        (cls.out/'results.json').write_text(json.dumps(cls.cases,indent=2)+'\n')

    def test_original_windows_and_changed_code_rejected(self):
        blob,meta=payload();self.assertEqual(self.cache['fv_sha256'],meta['segment_sha256'])
        for w in self.cache['windows'].values():
            a=int(w['address'],16)-0x9fc00000
            self.assertEqual(w['sha256'],hashlib.sha256(blob[a:a+w['size']]).hexdigest())
        b=bytearray(blob);b[0x17db0:0x17db4]=bytes.fromhex('1f2003d5')
        with patch('xbl_cache.payload',return_value=(bytes(b),meta)):
            with self.assertRaisesRegex(ValueError,'Unexpected original'):contract()
        self.assertEqual(self.cache['initial_canary_word'],'0xc0c0c0c0')
        for raw in (-1,1<<64):
            with self.assertRaises(ValueError):geometry(raw)

    def test_ten_original_cache_transitions_preserve_level_and_masks(self):
        for c,t in self.traces:
            p={v['name']:v for v in t['xbl_prefix_checkpoints']};base=p['sec-adjusted-stack-before-next-call']['registers']
            bank='SCTLR_EL2' if c['el2'] else 'SCTLR';other='SCTLR' if c['el2'] else 'SCTLR_EL2'
            for name,bits in (('sec-cache-invalidate-return',0),('sec-icache-enabled',0x1000),('sec-dcache-enabled',0x1004)):
                r=p[name]['registers'];self.assertEqual(int(r[bank],16),int(base[bank],16)|bits)
                self.assertEqual(int(r[bank],16)&1,0);self.assertEqual(r[other],base[other]);self.assertEqual(r['sp'],'0x9ffcfd00')
                self.assertEqual(int(r['cpsr'],16)&0x3cf,int(base['cpsr'],16)&0x3cf)
                self.assertEqual(r['HCR_EL2'],base['HCR_EL2'])
            self.assertEqual(t['calls'],self.traces[0][1]['calls']);self.assertEqual(len(t['calls']),263)
            self.assertEqual(t['pmic_map_ledger'],[6]*241)

    def test_executed_geometry_and_original_loop_bounds(self):
        for c,t in self.traces:
            g=t['xbl_cache_geometry'];self.assertEqual(len(g),2)
            for v,selector,raw,ways,sets in zip(g,(0,2),(0x701fe01a,0x707fe03a),(4,8),(256,1024)):
                self.assertEqual(v['selector'],hex(selector));self.assertEqual(v['clidr'],'0x82000023')
                expected=geometry(raw)
                for n in ('raw_ccsidr','line_bytes','ways','sets','setway_operations'):self.assertEqual(v[n],expected[n])
                self.assertEqual((v['ways'],v['sets']),(ways,sets));self.assertEqual(v['registers']['x1'],'0x9fc17db0')
            self.assertEqual(sum(v['setway_operations'] for v in g),9216)

    def test_second_request_unwritten_canary_and_single_reply_ledgers(self):
        for c,t in self.traces:
            p=t['xbl_prefix_checkpoints'];last=p[-1]
            self.assertEqual(sum(v['registers']['pc']=='0x9fc28468' for v in p),2)
            self.assertEqual(last['name'],'sec-canary-before-buffer-smc');self.assertEqual(last['registers']['sp'],'0x9ffcfce0')
            self.assertEqual(last['request'],['0x2000a01','0x22','0x9fc356c0','0x8','0x7','0x1d','0x82000023','0xffffffffffffffff'])
            self.assertEqual(last['buffer_hex'],'00'*8);self.assertEqual(last['canary_word'],self.cache['initial_canary_word'])
            self.assertEqual(last['query_reply_count'],1);self.assertEqual(last['buffer_reply_count'],1)
            self.assertEqual(last['stack_globals'],{'0x9fc3d710':'0x444444dd444444c','0x9fc356c8':'0x10'})
            for v in p:
                if v['registers']['pc'] in [hex(pc) for pc in POINTS] or v is last:
                    self.assertEqual(v['canary_word'],self.cache['initial_canary_word'])
                    for rr in v['workspace_after']:self.assertEqual(rr['guard_before_hex'],rr['guard_after_hex']);self.assertEqual(rr['guard_after_hex'],'a5'*16)
            stdout=(Path(c['trace']).parent/'stdout.txt').read_text()
            self.assertEqual(stdout.count('MODEL_XBL_BUFFER_ORIGINAL_SLICES_SYNTHETIC_FIFO_NOT_ENTROPY'),1)
            self.assertEqual(stdout.count('MODEL_XBL_QUERY_ORIGINAL_TZ_SLICE_REPLY'),1)

    def test_second_smc_routing_and_stock_forwarding(self):
        for c,t in self.traces:
            before=t['xbl_prefix_checkpoints'][-1]['registers'];route=t['xbl_smc_route'];r=route['after_instruction']
            self.assertEqual(int(before['cpsr'],16)>>32,0)  # signed GDB CPSR must normalize to uint32
            self.assertEqual([r['x'+str(i)] for i in range(8)],t['xbl_prefix_checkpoints'][-1]['request'])
            self.assertEqual(len(t['xbl_forward_calls']),0 if c['el2'] else 2)
            if c['el2']:
                self.assertEqual(route['destination'],'synthetic-el3-vector');self.assertEqual(r['ELR_EL3'],'0x9fc2846c')
                self.assertEqual(r['SPSR_EL3'],before['cpsr']);self.assertNotIn('xbl_qhee_handler',t)
            else:
                self.assertEqual(route['destination'],'original-qhee-el2-vector');self.assertEqual(r['ELR_EL2'],'0x9fc28468');self.assertEqual(r['SPSR_EL2'],before['cpsr'])
                h=t['xbl_qhee_handler'];self.assertEqual(h['registers']['pc'],'0x80041aa0');self.assertEqual(h['registers']['sp'],'0x80208db0')
                self.assertEqual(h['request'],['0x2000a01','0x22','0x9fc356c0','0x8','0x7','0x1d','0x0','0x3'])
                self.assertEqual(h['calls'],[{'args':h['request']}])

    def test_actual_registers_original_tz_slices_leave_validation_pending(self):
        for c,t in self.traces:
            r=json.loads((Path(c['manifest']).parent/'tz-buffer-slices.json').read_text())
            regs=t['xbl_prefix_checkpoints'][-1]['registers'] if c['el2'] else t['xbl_qhee_handler']['registers']
            self.assertEqual(r['decode']['input'],[regs['x'+str(i)] for i in range(14)])
            self.assertEqual(r['decode']['stop'],'0x1c065b0c');self.assertIsNone(r['decode']['validation_status'])
            self.assertEqual(r['reply_x0_x7'],['0x0','0x8']+['0x0']*6)
            self.assertFalse(any(v['address']=='0x82000023' for v in r['decode']['reads']))

    def test_cli_reply_metadata_and_forward_gates(self):
        c=self.cases[-1];p=Path(c['manifest']);data=p.read_bytes();m=json.loads(data)
        try:
            for value,message in ((None,'requires exact XBL buffer reply'),({**m['xbl_buffer_reply_model'],'buffer_hex':'00'*8},'buffer reply metadata mismatch')):
                n=json.loads(data);n['xbl_buffer_reply_model']=value;p.write_text(json.dumps(n))
                r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(p),'--out',str(p.parent/'bad-metadata'),'--xbl-cache-startup'],capture_output=True,text=True)
                self.assertEqual(r.returncode,2);self.assertIn(message,r.stderr)
        finally:p.write_bytes(data)
        r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(p),'--out',str(p.parent/'bad-metadata'),'--xbl-cache-startup','--inspect-xbl-smc-route','--inspect-xbl-qhee-forward'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2);self.assertIn('requires stock EL1',r.stderr)

    def test_earlier_stack_return_and_first_buffer_bounds(self):
        for c in self.cases[-2:]:
            for flag,name,stop in (('--xbl-stack-return','before-cache','0x9fc0cf38'),('--xbl-stack-buffer','before-buffer','0x9fc28468')):
                d=Path(c['manifest']).parent/name
                subprocess.run([sys.executable,str(self.tracer),'--manifest',c['manifest'],'--out',str(d),flag],check=True,stdout=subprocess.DEVNULL)
                r=json.loads((d/'manifest.json').read_text());self.assertEqual(r['xbl_prefix_checkpoints'][-1]['registers']['pc'],stop)
                self.assertNotIn('xbl_cache_contract',r);self.assertNotIn('xbl_cache_geometry',r)
                stdout=(d/'stdout.txt').read_text();self.assertEqual(stdout.count('MODEL_XBL_BUFFER_ORIGINAL_SLICES'),int(name=='before-cache'))

    def test_current_provenance_and_unchanged_firmware(self):
        for c,t in self.traces:
            p=Path(c['manifest']);m=json.loads(p.read_text())
            self.assertEqual(t['xbl_cache_contract'],self.cache);self.assertEqual(t['xbl_buffer_reply_model'],self.reply)
            self.assertEqual(t['input_manifest_sha256'],hashlib.sha256(p.read_bytes()).hexdigest());self.assertEqual(t['tool_sha256'],hashlib.sha256(self.tracer.read_bytes()).hexdigest())
            self.assertEqual(t['el3_sha256'],hashlib.sha256((p.parent/'el3.elf').read_bytes()).hexdigest())
            for path,h in m['tool_sha256'].items():self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),h)
        for n,h in self.pins.items():self.assertEqual(hashlib.sha256((ROOT/'backups/nio-firmware-20260927T163534Z'/n).read_bytes()).hexdigest(),h)

if __name__=='__main__':unittest.main()
