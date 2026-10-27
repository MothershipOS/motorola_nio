#!/usr/bin/env python3
"""Finite measured selector replay and original descriptor-to-MMIO tracing."""
import hashlib,json,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
from qhee import ROOT
from xbl_selector import SAMPLE,sample,contract,select,POINTS,STOP
from xbl_readiness import SAMPLE as FLAG
from xbl_target import payload
from xbl_canary import reply_model
from run_qemu import compile_elf,environment
from test_entry import complete_args

class SelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'kernel-work/out/qhee-selector-tests';cls.out.mkdir(exist_ok=True)
        cls.runner=Path(__file__).with_name('run_qemu.py');cls.tracer=Path(__file__).with_name('trace_bridge_handoff.py');cls.value,cls.meta=sample(SAMPLE);cls.contract=contract(cls.value);cls.cases=[];cls.traces=[]
        cls.pins={n:hashlib.sha256((ROOT/'backups/nio-firmware-20260927T163534Z'/n).read_bytes()).hexdigest() for n in ('hyp_a.img','tz_a.img','xbl_a.img','devcfg_a.img','abl_a.img')}
        for profile in ('synthetic-masked','tz-frame-hcr-zero','tz-frame-hcr-rw'):
            for clock in (('off',) if profile=='synthetic-masked' else ('off','on')):
                for el2 in (False,True):
                    d=cls.out/(profile+'-'+clock+'-'+('el2' if el2 else 'stock'));a=complete_args(clock,d);a[a.index('--payload-address')+1]='0x9fc00000'
                    a+=['--prepare-only','--xbl-workspace-sentinel','--xbl-query-reply','--xbl-buffer-reply','--xbl-canary-reply','--xbl-readiness-sample',str(FLAG),'--xbl-selector-sample',str(SAMPLE),'--entry-state-model',profile]
                    if el2:a+=['--handoff-experiment','el2-xbl-masked-mmu-off']
                    subprocess.run([sys.executable,str(cls.runner)]+a,check=True,stdout=subprocess.DEVNULL)
                    subprocess.run([sys.executable,str(cls.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace'),'--xbl-selector','--inspect-xbl-next-step'],check=True,stdout=subprocess.DEVNULL)
                    c={'profile':profile,'clock':clock,'el2':el2,'manifest':str(d/'manifest.json'),'trace':str(d/'trace/manifest.json')};cls.cases.append(c);cls.traces.append((c,json.loads(Path(c['trace']).read_text())))
        (cls.out/'results.json').write_text(json.dumps(cls.cases,indent=2)+'\n')

    def test_original_windows_and_changed_selector_read_choice_or_next_read_rejected(self):
        b,m=payload();self.assertEqual(self.contract['fv_sha256'],m['segment_sha256'])
        for w in self.contract['windows'].values():
            a=int(w['address'],16)-0x9fc00000;self.assertEqual(w['sha256'],hashlib.sha256(b[a:a+w['size']]).hexdigest())
        for offset in (0x2a150,0x2a164,0x220fc):
            changed=bytearray(b);changed[offset:offset+4]=bytes.fromhex('1f2003d5')
            with patch('xbl_selector.payload',return_value=(bytes(changed),m)):
                with self.assertRaises(ValueError):contract()
        self.assertEqual(self.contract['mmio_bases'],['0xa90000','0xac0000']);self.assertEqual(self.contract['next_access']['address'],'0xac0004')

    def test_original_selection_leaf_all_low_bits_no_writes_and_alternate_descriptor(self):
        results=[select(v) for v in (0,1,2,3,4,5,0xfffffffd,0xffffffff)]
        for r in results:
            value=int(r['input'],16);self.assertEqual(r['selected_descriptor'],'0x9fc35728' if value&3==1 else '0x9fc356e0');self.assertEqual(len(r['reads']),1);self.assertEqual(r['sp'],'0x9000f000')
        self.assertEqual(contract(1)['next_access']['address'],'0x9c0004')
        for value in (-1,1<<32,True,1.5):
            with self.assertRaises(ValueError):contract(value)
        (self.out/'selection-slices.json').write_text(json.dumps(results,indent=2)+'\n')

    def test_measured_sample_strict_parsing_repeats_and_entry_context(self):
        self.assertEqual(self.value,0);self.assertEqual(self.meta['read_limit'],1);p=self.out/'bad-sample.json';base=json.loads(SAMPLE.read_text())
        for change in ({'status':1},{'command':'devmem 0x01fc8000 32'},{'command':'devmem 0x01fc8004 64'},{'stdout':'0x00000000\n0x00000001\n'},{'stdout':'0x100000000\n'},{'stdout':'junk\n'},{'stdout':'0x00000001\n'}):
            r=json.loads(json.dumps(base));r['checks']['selector'].update(change);p.write_text(json.dumps(r))
            with self.assertRaises(ValueError):sample(p)
        for key in ('selector_repeat','uname','entry_level'):
            r=json.loads(json.dumps(base));del r['checks'][key];p.write_text(json.dumps(r))
            with self.assertRaises(ValueError):sample(p)
        p.unlink()

    def test_device_exact_once_prerequisite_default_disabled_and_access_denials(self):
        qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64');sources=Path(__file__).with_name('emulator');results=[]
        names=['valid','nonzero','disabled','no-version','repeat','repeat-after-version','read8','read16','read64','base-read64','write8','write32','write64','adjacent-after','base-repeat']
        for name in names:
            d=self.out/'device-contracts'/name;d.mkdir(parents=True,exist_ok=True);value=0xa5a5a5a5 if name=='nonzero' else self.value
            addr=0x1fc8008 if name=='adjacent-after' else 0x1fc8000 if name in ('base-read64','base-repeat') else 0x1fc8004
            access={'read8':3,'read16':5,'read64':4,'base-read64':4,'write8':7,'write32':1,'write64':8}.get(name,0)
            text=(sources/'register_probe.S').read_text()
            if name!='no-version':text=text.replace('test:\n','test:\n    ldr x8, =0x1fc8000\n    ldr w18, [x8]\n',1)
            if name in ('repeat','base-repeat'):text=text.replace('    ldr w19, [x8]\n','    ldr w19, [x8]\n    ldr w19, [x8]\n',1)
            if name=='repeat-after-version':text=text.replace('    ldr w19, [x8]\n','    ldr w19, [x8]\n    ldr x9, =0x1fc8000\n    ldr w18, [x9]\n    ldr w19, [x8]\n',1)
            (d/'probe.S').write_text(text);compile_elf(d/'probe.S',0x40200000,d/'probe.elf',[f'-DADDRESS={addr:#x}',f'-DACCESS={access}'])
            cmd=[str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3','-cpu','cortex-a76','-m','2G','-smp','1','-accel','tcg','-display','none','-serial','stdio','-monitor','none','-nic','none','-semihosting-config','enable=on,target=native','-no-reboot','-device',f'loader,file={d/"probe.elf"},cpu-num=0','-device',f'nio-soc-version,value=0x60080201,selector-replay={"off" if name=="disabled" else "on"},selector-value={value:#x}']
            r=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=5);lines=r.stdout.splitlines()
            if name in ('valid','nonzero','base-repeat'):self.assertEqual(lines,['READ',f'{0x60080201 if name=="base-repeat" else value:016x}'],name)
            else:self.assertEqual(lines[0],'ABORT',name);self.assertEqual(int(lines[1],16)&0x3f,0x10,name);self.assertEqual(int(lines[2],16),addr+4 if name=='read64' else addr,name)
            self.assertEqual(r.stderr.count('NIO_SEC_SELECTOR_READ'),int(name in ('valid','nonzero','repeat','repeat-after-version','read64')),name);self.assertEqual(r.returncode,0)
            (d/'stdout.txt').write_text(r.stdout);(d/'stderr.txt').write_text(r.stderr);results.append({'case':name,'passed':True,'command':cmd})
        (self.out/'device-contracts/results.json').write_text(json.dumps(results,indent=2)+'\n')

    def test_cli_dependencies_default_disabled_and_strict_metadata_command_validation(self):
        r=subprocess.run([sys.executable,str(self.runner),'--xbl-selector-sample',str(SAMPLE)],capture_output=True,text=True);self.assertEqual(r.returncode,2);self.assertIn('requires --xbl-readiness-sample',r.stderr)
        d=self.out/'no-selector';a=complete_args('off',d);a[a.index('--payload-address')+1]='0x9fc00000';a+=['--prepare-only','--xbl-query-reply','--xbl-buffer-reply','--xbl-canary-reply','--xbl-readiness-sample',str(FLAG)]
        subprocess.run([sys.executable,str(self.runner)]+a,check=True,stdout=subprocess.DEVNULL);m=json.loads((d/'manifest.json').read_text());self.assertIsNone(m['xbl_selector_sample'])
        r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace'),'--xbl-selector'],capture_output=True,text=True);self.assertEqual(r.returncode,2);self.assertIn('requires exact measured selector',r.stderr)
        p=Path(self.cases[-1]['manifest']);data=p.read_bytes()
        try:
            variants=[];n=json.loads(data);n['xbl_selector_sample']['value']='0x1';variants.append((n,'metadata mismatch'))
            n=json.loads(data);n['command']=[v.replace('selector-replay=on','selector-replay=off') for v in n['command']];variants.append((n,'device command mismatch'))
            n=json.loads(data);n['xbl_selector_sample']=None;variants.append((n,'Unreported SEC selector'))
            n=json.loads(data);n['command']+=[next(v for v in n['command'] if v.startswith('nio-soc-version,'))];variants.append((n,'device command mismatch'))
            for n,msg in variants:
                p.write_text(json.dumps(n));r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(p),'--out',str(self.out/'bad-metadata'),'--xbl-selector'],capture_output=True,text=True);self.assertEqual(r.returncode,2);self.assertIn(msg,r.stderr)
        finally:p.write_bytes(data)

    def test_ten_original_selector_choice_store_table_match_hook_and_next_fault(self):
        for c,t in self.traces:
            p={v['name']:v for v in t['xbl_prefix_checkpoints']};last=t['xbl_prefix_checkpoints'][-1]
            self.assertEqual(p['sec-selector-read-complete']['observed_selector'],'0x0');self.assertEqual(p['sec-selector-before-choice']['low_bits'],0);self.assertFalse(p['sec-selector-before-choice']['equal_one'])
            self.assertEqual(p['sec-selector-chosen']['selected_descriptor'],'0x9fc356e0');self.assertEqual(p['sec-selected-descriptor-stored']['stored_pointer'],'0x9fc356e0')
            self.assertEqual(p['sec-descriptor-table-match']['table_match'],{'key':'0x1c200','copied_id':'0x1c200','record':'0x9fc32600'});self.assertEqual(p['sec-descriptor-noop-hook']['hook_argument'],'0x708000')
            self.assertEqual(p['sec-descriptor-hook-return']['registers']['x0'],'0x0');self.assertEqual(last['registers']['pc'],hex(STOP));self.assertEqual(last['registers']['sp'],'0x9ffcfac0');self.assertEqual(last['pending_access'],{**self.contract['next_access'],'executed':False})
            step=t['xbl_next_access_step'];bank='EL2' if c['el2'] else 'EL1';self.assertEqual(step['destination'],'mmio-data-abort-'+bank.lower());self.assertEqual(step['syndrome'],'0x96000010');self.assertFalse(step['handler_executed']);self.assertEqual(step['after']['FAR_'+bank],'0xac0004');self.assertEqual(step['after']['ELR_'+bank],hex(STOP));self.assertEqual(step['after']['pc'],'0x9ff8c200')
            err=(Path(c['trace']).parent/'stderr.txt').read_text();self.assertEqual(err.count('NIO_SEC_SELECTOR_READ'),1);self.assertLess(err.index('NIO_MODEL_TCSR_READ'),err.index('NIO_SEC_SELECTOR_READ'))

    def test_el_controls_guards_ledgers_original_cold_calls_and_counter_store_preserved(self):
        for c,t in self.traces:
            p={v['name']:v for v in t['xbl_prefix_checkpoints']};base=p['sec-dcache-enabled']['registers']
            for pc,name in POINTS.items():
                v=p[name];self.assertEqual(v['registers']['pc'],hex(pc));self.assertEqual(v['canary_word'],reply_model()['buffer_word']);self.assertEqual((v['query_reply_count'],v['buffer_reply_count'],v['canary_reply_count']),(1,1,1))
                for bank in ('SCTLR','SCTLR_EL2','HCR_EL2'):self.assertEqual(v['registers'][bank],base[bank])
                self.assertEqual(int(v['registers']['cpsr'],16)&0x3cf,int(base['cpsr'],16)&0x3cf);self.assertEqual(v['stored_counter'],p['sec-counter-converted']['converted_value'])
                self.assertEqual(v['timer_controls'],p['sec-counter-read-complete']['timer_controls'])
                for rr in v['workspace_after']:self.assertEqual(rr['guard_before_hex'],rr['guard_after_hex']);self.assertEqual(rr['guard_after_hex'],'a5'*16)
            self.assertEqual(t['calls'],self.traces[0][1]['calls']);self.assertEqual(len(t['calls']),263);self.assertEqual(t['pmic_map_ledger'],[6]*241);self.assertEqual(len(t['xbl_forward_calls']),0 if c['el2'] else 2)

    def test_earlier_counter_and_default_unstepped_next_controls(self):
        controls=[]
        for c in self.cases[-2:]:
            for flag,name,stop in (('--xbl-counter','before-selector','0x9fc2a150'),('--xbl-selector','before-selected-mmio',hex(STOP))):
                d=Path(c['manifest']).parent/name;subprocess.run([sys.executable,str(self.tracer),'--manifest',c['manifest'],'--out',str(d),flag],check=True,stdout=subprocess.DEVNULL);r=json.loads((d/'manifest.json').read_text());self.assertEqual(r['xbl_prefix_checkpoints'][-1]['registers']['pc'],stop);self.assertNotIn('xbl_next_access_step',r)
                if flag=='--xbl-counter':self.assertNotIn('xbl_selector_contract',r);self.assertNotIn('NIO_SEC_SELECTOR_READ',(d/'stderr.txt').read_text())
                controls.append(str(d/'manifest.json'))
        (self.out/'earlier-controls.json').write_text(json.dumps(controls,indent=2)+'\n')

    def test_current_source_capture_build_provenance_and_unchanged_firmware(self):
        build=json.loads((ROOT/'kernel-work/emulation/qemu-model-build.json').read_text());self.assertEqual(build['device_source_sha256']['nio-soc-version.c'],hashlib.sha256(Path(__file__).with_name('emulator').joinpath('nio-soc-version.c').read_bytes()).hexdigest());self.assertEqual(build['binary_sha256'],hashlib.sha256((ROOT/build['binary']).read_bytes()).hexdigest())
        capture=json.loads(SAMPLE.read_text());self.assertEqual(capture['tool_sha256'],hashlib.sha256((ROOT/'tools/nio_console.py').read_bytes()).hexdigest());self.assertEqual(capture['capture_script_sha256'],hashlib.sha256(SAMPLE.with_name('capture.py').read_bytes()).hexdigest())
        for c,t in self.traces:
            p=Path(c['manifest']);m=json.loads(p.read_text());self.assertEqual(t['xbl_selector_contract'],self.contract);self.assertEqual(m['xbl_selector_sample'],t['xbl_selector_sample']);self.assertEqual(t['xbl_selector_sample'],self.meta)
            self.assertEqual(t['input_manifest_sha256'],hashlib.sha256(p.read_bytes()).hexdigest());self.assertEqual(t['tool_sha256'],hashlib.sha256(self.tracer.read_bytes()).hexdigest());self.assertEqual(t['el3_sha256'],hashlib.sha256((p.parent/'el3.elf').read_bytes()).hexdigest())
            for path,h in m['tool_sha256'].items():self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),h)
        for n,h in self.pins.items():self.assertEqual(hashlib.sha256((ROOT/'backups/nio-firmware-20260927T163534Z'/n).read_bytes()).hexdigest(),h)

if __name__=='__main__':unittest.main()
