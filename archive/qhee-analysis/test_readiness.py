#!/usr/bin/env python3
"""Finite measured hold-flag replay, loop behavior and original counter boundary."""
import hashlib,json,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
from qhee import ROOT
from xbl_readiness import SAMPLE,sample,contract,poll,POINTS
from xbl_target import payload
from xbl_canary import reply_model
from run_qemu import compile_elf,environment
from test_entry import complete_args

class ReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'kernel-work/out/qhee-readiness-tests';cls.out.mkdir(exist_ok=True)
        cls.runner=Path(__file__).with_name('run_qemu.py');cls.tracer=Path(__file__).with_name('trace_bridge_handoff.py');cls.value,cls.meta=sample(SAMPLE);cls.contract=contract();cls.cases=[];cls.traces=[]
        cls.pins={n:hashlib.sha256((ROOT/'backups/nio-firmware-20260927T163534Z'/n).read_bytes()).hexdigest() for n in ('hyp_a.img','tz_a.img','xbl_a.img','devcfg_a.img','abl_a.img')}
        for profile in ('synthetic-masked','tz-frame-hcr-zero','tz-frame-hcr-rw'):
            for clock in (('off',) if profile=='synthetic-masked' else ('off','on')):
                for el2 in (False,True):
                    d=cls.out/(profile+'-'+clock+'-'+('el2' if el2 else 'stock'));a=complete_args(clock,d);a[a.index('--payload-address')+1]='0x9fc00000'
                    a+=['--prepare-only','--xbl-workspace-sentinel','--xbl-query-reply','--xbl-buffer-reply','--xbl-canary-reply','--xbl-readiness-sample',str(SAMPLE),'--entry-state-model',profile]
                    if el2:a+=['--handoff-experiment','el2-xbl-masked-mmu-off']
                    subprocess.run([sys.executable,str(cls.runner)]+a,check=True,stdout=subprocess.DEVNULL)
                    subprocess.run([sys.executable,str(cls.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace'),'--xbl-readiness'],check=True,stdout=subprocess.DEVNULL)
                    c={'profile':profile,'clock':clock,'el2':el2,'manifest':str(d/'manifest.json'),'trace':str(d/'trace/manifest.json')};cls.cases.append(c);cls.traces.append((c,json.loads(Path(c['trace']).read_text())))
        (cls.out/'results.json').write_text(json.dumps(cls.cases,indent=2)+'\n')

    def test_original_windows_counter_access_and_changed_code_rejected(self):
        b,m=payload();self.assertEqual(self.contract['fv_sha256'],m['segment_sha256'])
        for w in self.contract['windows'].values():
            a=int(w['address'],16)-0x9fc00000;self.assertEqual(w['sha256'],hashlib.sha256(b[a:a+w['size']]).hexdigest())
        changed=bytearray(b);changed[0x2bb48:0x2bb4c]=bytes.fromhex('1f2003d5')
        with patch('xbl_readiness.payload',return_value=(bytes(changed),m)):
            with self.assertRaisesRegex(ValueError,'Unexpected original'):contract()
        self.assertEqual(self.contract['counter'],'CNTVCT_EL0');self.assertIn('Unverified',self.contract['publisher_status'])
        build=json.loads((ROOT/'kernel-work/emulation/qemu-model-build.json').read_text())
        self.assertEqual(build['device_source_sha256']['nio-tz-log-pointer.c'],hashlib.sha256(Path(__file__).with_name('emulator').joinpath('nio-tz-log-pointer.c').read_bytes()).hexdigest())
        self.assertEqual(build['binary_sha256'],hashlib.sha256((ROOT/build['binary']).read_bytes()).hexdigest())

    def test_measured_sample_strict_parsing_and_context(self):
        self.assertEqual(self.value,0x3a6506a5);self.assertEqual(self.meta['read_limit'],1)
        p=self.out/'bad-sample.json';base=json.loads(SAMPLE.read_text())
        changes=[('failed',{'status':1}),('wrong-address',{'command':'devmem 0x146bf948 32'}),('wrong-width',{'command':'devmem 0x146bf944 64'}),('multiple',{'stdout':'0x00000000\n0x00000001\n'}),('overflow',{'stdout':'0x100000000\n'}),('negative',{'stdout':'-1\n'}),('junk',{'stdout':'junk\n'}),('different',{'stdout':'0x00000000\n'})]
        for name,values in changes:
            r=json.loads(json.dumps(base));r['checks']['sec_flag'].update(values);p.write_text(json.dumps(r))
            with self.assertRaises(ValueError,msg=name):sample(p)
        for name in ('uname','entry_level','sec_flag_repeat'):
            r=json.loads(json.dumps(base));del r['checks'][name];p.write_text(json.dumps(r))
            with self.assertRaises(ValueError,msg=name):sample(p)
        p.unlink()

    def test_original_poll_nonheld_held_and_explicit_release_fixture(self):
        for value in (self.value,0,0xffffffff):
            r=poll([value]);self.assertEqual(r['stop'],'0x90008000');self.assertEqual(r['sp'],'0x9000f000');self.assertFalse(r['exhausted']);self.assertEqual(len(r['reads']),1)
            self.assertIn('0x9fc0e390',r['pcs']);self.assertNotIn('0x9fc0e38c',r['pcs'])
        held=poll([0x55444247]);self.assertEqual(held['stop'],'0x9fc0e37c');self.assertTrue(held['exhausted']);self.assertIn('0x9fc0e38c',held['pcs'])
        release=poll([0x55444247,0x55444247,self.value]);self.assertEqual(len(release['reads']),3);self.assertEqual(release['stop'],'0x90008000')
        for values in ([],[-1],[1<<32],[0]*9):
            with self.assertRaises(ValueError):poll(values)
        (self.out/'poll-contracts.json').write_text(json.dumps({'nonheld':poll([self.value]),'held':held,'release_fixture':release},indent=2)+'\n')

    def test_device_exact_read_once_prior_publications_and_denials(self):
        qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64');sources=Path(__file__).with_name('emulator');results=[]
        names=['valid','nonzero','held','disabled','no-log','no-ready','read8','read16','read64','write8','write32','write64','repeat','adjacent-before','adjacent-after']
        for name in names:
            d=self.out/'device-contracts'/name;d.mkdir(parents=True,exist_ok=True)
            value=0xa5a5a5a5 if name=='nonzero' else 0x55444247 if name=='held' else self.value
            addr=0x146bf948 if name in ('wrong-address','adjacent-after') else 0x146bf940 if name=='adjacent-before' else 0x146bf944
            access={'read8':3,'read16':5,'read64':4,'write8':7,'write32':1,'write64':8}.get(name,0)
            text=(sources/'register_probe.S').read_text();init=[]
            if name!='no-log':init+=['ldr x8, =0x146bfb30','ldr x19, =0x200080209000','str x19, [x8]']
            if name not in ('no-log','no-ready'):init+=['ldr x8, =0x146bfb20','ldr x19, =0x800a5021','str x19, [x8]']
            text=text.replace('test:\n','test:\n'+'\n'.join(init)+'\n',1)
            if name=='repeat':text=text.replace('    ldr w19, [x8]\n','    ldr w19, [x8]\n    ldr w19, [x8]\n',1)
            (d/'probe.S').write_text(text);compile_elf(d/'probe.S',0x40200000,d/'probe.elf',[f'-DADDRESS={addr:#x}',f'-DACCESS={access}'])
            cmd=[str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3','-cpu','cortex-a76','-m','2G','-smp','1','-accel','tcg','-display','none','-serial','stdio','-monitor','none','-nic','none','-semihosting-config','enable=on,target=native','-no-reboot','-device',f'loader,file={d/"probe.elf"},cpu-num=0','-device',f'nio-tz-log-pointer,value=0x14695000,publications=on,ready-publication=on,sec-flag-replay={"off" if name=="disabled" else "on"},sec-flag-value={value:#x}']
            r=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=5);lines=r.stdout.splitlines()
            if name in ('valid','nonzero','held'):self.assertEqual(lines,['READ',f'{value:016x}'],name)
            else:self.assertEqual(lines[0],'ABORT',name);self.assertEqual(int(lines[1],16)&0x3f,0x10,name);self.assertEqual(int(lines[2],16),addr+4 if name=='read64' else addr,name)
            self.assertEqual(r.stderr.count('NIO_SEC_FLAG_READ'),int(name in ('valid','nonzero','held','repeat','read64')),name);self.assertEqual(r.returncode,0)
            (d/'stdout.txt').write_text(r.stdout);(d/'stderr.txt').write_text(r.stderr);results.append({'case':name,'passed':True,'command':cmd})
        (self.out/'device-contracts/results.json').write_text(json.dumps(results,indent=2)+'\n')

    def test_cli_dependencies_and_default_disabled(self):
        r=subprocess.run([sys.executable,str(self.runner),'--xbl-readiness-sample',str(SAMPLE)],capture_output=True,text=True);self.assertEqual(r.returncode,2);self.assertIn('requires --xbl-canary-reply',r.stderr)
        d=self.out/'no-flag';a=complete_args('off',d);a[a.index('--payload-address')+1]='0x9fc00000';a+=['--prepare-only','--xbl-query-reply','--xbl-buffer-reply','--xbl-canary-reply']
        subprocess.run([sys.executable,str(self.runner)]+a,check=True,stdout=subprocess.DEVNULL);m=json.loads((d/'manifest.json').read_text());self.assertIsNone(m['xbl_readiness_sample'])
        r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace'),'--xbl-readiness'],capture_output=True,text=True);self.assertEqual(r.returncode,2);self.assertIn('requires exact canary reply and measured',r.stderr)

    def test_metadata_and_device_command_fail_closed(self):
        p=Path(self.cases[-1]['manifest']);data=p.read_bytes();m=json.loads(data)
        try:
            variants=[({**m,'xbl_readiness_sample':{**m['xbl_readiness_sample'],'value':'0x0'}},'metadata mismatch')]
            n=json.loads(data);n['command']=[v.replace(',sec-flag-replay=on',',sec-flag-replay=off') for v in n['command']];variants.append((n,'device command mismatch'))
            n=json.loads(data);n['xbl_readiness_sample']=None;variants.append((n,'Unreported SEC flag'))
            for n,msg in variants:
                p.write_text(json.dumps(n));r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(p),'--out',str(p.parent/'bad-metadata'),'--xbl-readiness'],capture_output=True,text=True)
                self.assertEqual(r.returncode,2);self.assertIn(msg,r.stderr)
        finally:p.write_bytes(data)

    def test_ten_original_loop_exit_platform_prologue_and_counter_boundary(self):
        for c,t in self.traces:
            p={v['name']:v for v in t['xbl_prefix_checkpoints']};base=p['sec-dcache-enabled']['registers'];last=t['xbl_prefix_checkpoints'][-1]
            self.assertEqual(last['registers']['pc'],'0x9fc2bb48');self.assertEqual(last['registers']['sp'],'0x9ffcfbc0');self.assertEqual(last['pending_counter'],{'register':'CNTVCT_EL0','executed':False})
            for pc,name in POINTS.items():
                v=p[name];self.assertEqual(v['registers']['pc'],hex(pc));self.assertEqual(v['canary_word'],reply_model()['buffer_word'])
                for bank in ('SCTLR','SCTLR_EL2','HCR_EL2'):self.assertEqual(v['registers'][bank],base[bank])
                self.assertEqual(int(v['registers']['cpsr'],16)&0x3cf,int(base['cpsr'],16)&0x3cf)
                self.assertEqual((v['query_reply_count'],v['buffer_reply_count'],v['canary_reply_count']),(1,1,1))
                for rr in v['workspace_after']:self.assertEqual(rr['guard_before_hex'],rr['guard_after_hex']);self.assertEqual(rr['guard_after_hex'],'a5'*16)
            self.assertEqual(p['sec-flag-loaded']['observed_flag'],self.meta['value']);self.assertEqual(p['sec-flag-before-branch']['observed_flag'],self.meta['value']);self.assertFalse(int(p['sec-flag-before-branch']['registers']['cpsr'],16)&(1<<30))
            self.assertEqual(last['platform_frame_canary'],reply_model()['buffer_word']);self.assertEqual(p['sec-flag-helper-return']['registers']['sp'],'0x9ffcfce0')
            self.assertEqual(t['calls'],self.traces[0][1]['calls']);self.assertEqual(len(t['calls']),263);self.assertEqual(t['pmic_map_ledger'],[6]*241)
            stderr=(Path(c['trace']).parent/'stderr.txt').read_text();self.assertEqual(stderr.count('NIO_SEC_FLAG_READ'),1);self.assertNotIn('NIO_IMEM_DENIED',stderr)
            self.assertEqual(len(t['xbl_forward_calls']),0 if c['el2'] else 2)

    def test_earlier_stop_controls_do_not_read_flag(self):
        controls=[]
        for c in self.cases[-2:]:
            for flag,name,stop in (('--xbl-canary-return','before-flag','0x9fc0e37c'),('--xbl-cache-startup','before-second','0x9fc28468')):
                d=Path(c['manifest']).parent/name;subprocess.run([sys.executable,str(self.tracer),'--manifest',c['manifest'],'--out',str(d),flag],check=True,stdout=subprocess.DEVNULL)
                r=json.loads((d/'manifest.json').read_text());self.assertEqual(r['xbl_prefix_checkpoints'][-1]['registers']['pc'],stop);self.assertNotIn('xbl_readiness_contract',r);self.assertNotIn('NIO_SEC_FLAG_READ',(d/'stderr.txt').read_text());controls.append(str(d/'manifest.json'))
        (self.out/'earlier-controls.json').write_text(json.dumps(controls,indent=2)+'\n')

    def test_current_provenance_capture_and_unchanged_firmware(self):
        self.assertEqual(self.meta['sha256'],hashlib.sha256(SAMPLE.read_bytes()).hexdigest())
        for c,t in self.traces:
            p=Path(c['manifest']);m=json.loads(p.read_text());self.assertEqual(t['xbl_readiness_contract'],self.contract);self.assertEqual(t['xbl_readiness_sample'],self.meta)
            self.assertEqual(t['input_manifest_sha256'],hashlib.sha256(p.read_bytes()).hexdigest());self.assertEqual(t['tool_sha256'],hashlib.sha256(self.tracer.read_bytes()).hexdigest());self.assertEqual(t['el3_sha256'],hashlib.sha256((p.parent/'el3.elf').read_bytes()).hexdigest())
            for path,h in m['tool_sha256'].items():self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),h)
        for n,h in self.pins.items():self.assertEqual(hashlib.sha256((ROOT/'backups/nio-firmware-20260927T163534Z'/n).read_bytes()).hexdigest(),h)

if __name__=='__main__':unittest.main()
