#!/usr/bin/env python3
"""Second exact fixture reply, original canary store and first SEC readiness load."""
import hashlib,json,struct,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
from qhee import ROOT
from xbl_canary import contract,reply_model,WORDS,POINTS
from xbl_target import payload
from tz_buffer import run,reply_model as first_reply
from test_entry import complete_args
from test_replay import caller_source
from test_bridge import caller
from test_late_init import symbols,machine
from run_qemu import compile_elf,environment,decode_stop

MARKER='MODEL_XBL_CANARY_SECOND_BUFFER_SYNTHETIC_FIFO_NOT_ENTROPY'
class CanaryReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'kernel-work/out/qhee-canary-return-tests';cls.out.mkdir(exist_ok=True)
        cls.runner=Path(__file__).with_name('run_qemu.py');cls.tracer=Path(__file__).with_name('trace_bridge_handoff.py')
        cls.reply=reply_model();cls.contract=contract();cls.word=int(cls.reply['buffer_word'],16);cls.cases=[];cls.traces=[]
        cls.pins={n:hashlib.sha256((ROOT/'backups/nio-firmware-20260927T163534Z'/n).read_bytes()).hexdigest() for n in ('hyp_a.img','tz_a.img','xbl_a.img','devcfg_a.img','abl_a.img')}
        for profile in ('synthetic-masked','tz-frame-hcr-zero','tz-frame-hcr-rw'):
            for clock in (('off',) if profile=='synthetic-masked' else ('off','on')):
                for el2 in (False,True):
                    d=cls.out/(profile+'-'+clock+'-'+('el2' if el2 else 'stock'))
                    a=complete_args(clock,d);a[a.index('--payload-address')+1]='0x9fc00000'
                    a+=['--prepare-only','--xbl-workspace-sentinel','--xbl-query-reply','--xbl-buffer-reply','--xbl-canary-reply','--entry-state-model',profile]
                    if el2:a+=['--handoff-experiment','el2-xbl-masked-mmu-off']
                    subprocess.run([sys.executable,str(cls.runner)]+a,check=True,stdout=subprocess.DEVNULL)
                    subprocess.run([sys.executable,str(cls.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace'),'--xbl-canary-return'],check=True,stdout=subprocess.DEVNULL)
                    a=[sys.executable,str(cls.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'before-canary'),'--xbl-cache-startup','--inspect-xbl-smc-route']
                    if not el2:a+=['--inspect-xbl-qhee-forward']
                    subprocess.run(a,check=True,stdout=subprocess.DEVNULL)
                    c={'profile':profile,'clock':clock,'el2':el2,'manifest':str(d/'manifest.json'),'trace':str(d/'trace/manifest.json'),'before_canary':str(d/'before-canary/manifest.json')}
                    t=json.loads(Path(c['trace']).read_text());cls.cases.append(c);cls.traces.append((c,t))
                    control=json.loads(Path(c['before_canary']).read_text());regs=control['xbl_prefix_checkpoints'][-1]['registers'] if el2 else control['xbl_qhee_handler']['registers']
                    (d/'tz-buffer-slices.json').write_text(json.dumps(run([int(regs['x'+str(i)],16) for i in range(14)]),indent=2)+'\n')
        (cls.out/'results.json').write_text(json.dumps(cls.cases,indent=2)+'\n')

    def test_original_windows_readiness_and_slice_derivations(self):
        b,m=payload();self.assertEqual(self.contract['fv_sha256'],m['segment_sha256'])
        for w in self.contract['windows'].values():
            a=int(w['address'],16)-0x9fc00000;self.assertEqual(w['sha256'],hashlib.sha256(b[a:a+w['size']]).hexdigest())
        changed=bytearray(b);changed[0x0cd54:0x0cd58]=bytes.fromhex('1f2003d5')
        with patch('xbl_canary.payload',return_value=(bytes(changed),m)):
            with self.assertRaisesRegex(ValueError,'Unexpected original'):contract()
        self.assertEqual(self.contract['readiness_address'],'0x146bf944');self.assertEqual(self.contract['wait_while_value'],'0x55444247')
        self.assertEqual(self.reply['buffer_word'],first_reply()['buffer_word'])  # repeat deterministic fixture explicitly
        for name,words in WORDS.items():
            r=run(words);self.assertEqual(self.reply['derivations'][name]['derivation_sha256'],hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest())
            self.assertEqual(r['decode']['stop'],'0x1c065b0c');self.assertIsNone(r['decode']['validation_status'])

    def test_runner_requires_first_reply_and_default_stays_disabled(self):
        for args,msg in ((['--xbl-canary-reply'],'requires --xbl-buffer-reply'),(['--xbl-canary-reply','--xbl-buffer-reply'],'requires --xbl-query-reply'),(['--xbl-canary-reply','--xbl-buffer-reply','--xbl-query-reply'],'requires prepared original XBL')):
            r=subprocess.run([sys.executable,str(self.runner)]+args,capture_output=True,text=True);self.assertEqual(r.returncode,2);self.assertIn(msg,r.stderr)
        d=self.out/'no-second';a=complete_args('off',d);a[a.index('--payload-address')+1]='0x9fc00000';a+=['--prepare-only','--xbl-query-reply','--xbl-buffer-reply']
        subprocess.run([sys.executable,str(self.runner)]+a,check=True,stdout=subprocess.DEVNULL)
        self.assertIsNone(json.loads((d/'manifest.json').read_text())['xbl_canary_reply_model'])
        r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace'),'--xbl-canary-return'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2);self.assertIn('requires exact second',r.stderr)

    def test_metadata_and_non_smc_routing_fail_closed(self):
        p=Path(self.cases[-1]['manifest']);data=p.read_bytes();m=json.loads(data)
        try:
            for v,msg in ((None,'requires exact second'),({**m['xbl_canary_reply_model'],'buffer_word':'0x0'},'canary reply metadata mismatch')):
                n=json.loads(data);n['xbl_canary_reply_model']=v;p.write_text(json.dumps(n))
                r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(p),'--out',str(p.parent/'bad-metadata'),'--xbl-canary-return'],capture_output=True,text=True)
                self.assertEqual(r.returncode,2);self.assertIn(msg,r.stderr)
        finally:p.write_bytes(data)
        r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(p),'--out',str(p.parent/'bad-metadata'),'--xbl-canary-return','--inspect-xbl-smc-route'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2);self.assertIn('requires --xbl-stack-smc',r.stderr)

    def test_exact_second_reply_preservation_denials_and_repeat(self):
        qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64');results=[]
        names=['valid-stock','valid-el2','disabled','wrong-site','wrong-el','wrong-immediate','wrong-fid','wrong-count','wrong-buffer','short-size','long-size','wrong-x4','wrong-x5','wrong-x6','wrong-x7','wrong-sp','cache-off','mmu-on','no-bridge','no-query','no-first-buffer','bad-first-count','consumed','preexisting-buffer','wrong-selector','wrong-nibble-cache','prewritten-canary','repeat']
        for name in names:
            d=self.out/'reply-contracts'/name;d.mkdir(parents=True,exist_ok=True);el2=name=='valid-el2'
            defs=['-DSHM_BRIDGE_MODEL_HANDLE=1','-DPRNG_MODEL_WORD=1','-DBRIDGE_PRNG_MODEL_WORD=1','-DXBL_QUERY_REPLY_MODEL','-DXBL_BUFFER_REPLY_MODEL',f'-DXBL_BUFFER_FIXTURE_WORD={self.word:#x}']
            if name!='disabled':defs+=['-DXBL_CANARY_REPLY_MODEL',f'-DXBL_CANARY_FIXTURE_WORD={self.word:#x}',f'-DXBL_CANARY_FIRST_SHIFTED_CACHE={self.word>>4:#x}']
            compile_elf(Path(__file__).with_name('emulator')/'start.S',0x40200000,d/'el3.elf',defs);sym=symbols(d/'el3.elf')
            asm,initial=caller_source(0x2000a01,0x22,1 if name=='wrong-el' else 2,int(name=='wrong-immediate'))
            values={i:v for i,v in enumerate(WORDS['el2' if el2 else 'stock'][:8])}
            changes={'wrong-fid':(0,0x2000a02),'wrong-count':(1,2),'wrong-buffer':(2,0x9fc356c8),'short-size':(3,4),'long-size':(3,16),'wrong-x4':(4,0),'wrong-x5':(5,0),'wrong-x6':(6,1),'wrong-x7':(7,0)}
            if name in changes:i,v=changes[name];values[i]=v
            for i,v in values.items():asm=asm.replace(f'ldr x{i}, ={initial[i]:#x}',f'ldr x{i}, ={v:#x}');initial[i]=v
            sp=0x9ffcfce0 if el2 else 0x80208db0
            if name=='wrong-sp':sp+=16
            sctlr=0x1000 if name=='cache-off' else 0x1005 if name=='mmu-on' else 0x1004
            init=f'ldr x11, ={sp:#x}\nmov sp, x11\nldr x11, ={sctlr:#x}\nmsr '+('sctlr_el2' if el2 else 'sctlr_el1')+', x11\nisb\n'
            asm=asm.replace('_start:\n','_start:\n'+init,1)
            blocks={0x9fc356b8:struct.pack('<4Q',0xa5a5a5a5a5a5a5a5,int(name=='preexisting-buffer'),8 if name=='wrong-selector' else 16,0xa5a5a5a5a5a5a5a5),
                    0x9fc3d710:struct.pack('<Q',0 if name=='wrong-nibble-cache' else self.word>>4),
                    0x9fc350a0:struct.pack('<3Q',0xa5a5a5a5a5a5a5a5,1 if name=='prewritten-canary' else 0xc0c0c0c0,0xa5a5a5a5a5a5a5a5),
                    sym['bridge_prng_count']:struct.pack('<Q',int(name!='no-bridge')),
                    sym['xbl_query_count']:struct.pack('<Q',int(name!='no-query')),
                    sym['xbl_buffer_count']:struct.pack('<Q',0 if name=='no-first-buffer' else 2 if name=='bad-first-count' else 1)}
            reads=[0x9fc356b8,0x9fc356c0,0x9fc356c8,0x9fc356d0,0x9fc3d710,0x9fc350a0,0x9fc350a8,0x9fc350b0,sym['xbl_buffer_count']]
            if 'xbl_canary_count' in sym:blocks[sym['xbl_canary_count']]=struct.pack('<Q',int(name=='consumed'));reads+=[sym['xbl_canary_count']]
            caller(d,asm,blocks,reads,int(name=='wrong-immediate'),False,name=='repeat')
            a=(d/'caller.S').read_text().replace('.org 0x1aa0','.org '+hex(0x1468 if el2 else 0x1cbc if name=='wrong-site' else 0x1aa0))
            (d/'caller.S').write_text(a);compile_elf(d/'caller.S',0x9fc27000 if el2 else 0x80040000,d/'caller.elf')
            cmd=machine(qemu,d/'el3.elf',d/'caller.elf')
            if el2:
                (d/'bootstrap.S').write_text('.text\n.global _start\n_start:\nldr x0, =0x9fc27000\nbr x0\n');compile_elf(d/'bootstrap.S',0x80040000,d/'bootstrap.elf');cmd+=['-device',f'loader,file={d/"bootstrap.elf"}']
            r=subprocess.run(cmd,capture_output=True,env=env,timeout=5);stdout=r.stdout.decode()
            if name.startswith('valid-'):
                expected=[0,8,0,0]+initial[4:]+[sp,0xa0000000,0xa5a5a5a5a5a5a5a5,self.word,16,0xa5a5a5a5a5a5a5a5,self.word>>4,0xa5a5a5a5a5a5a5a5,0xc0c0c0c0,0xa5a5a5a5a5a5a5a5,1,1]
                self.assertEqual(stdout.splitlines(),[MARKER]+[f'{v:016x}' for v in expected],name)
            else:self.assertEqual(stdout.count(MARKER),int(name=='repeat'),name);self.assertIsNotNone(decode_stop(r.stdout),name)
            self.assertEqual(r.returncode,0,name);(d/'stdout.txt').write_bytes(r.stdout);(d/'stderr.txt').write_bytes(r.stderr);results.append({'case':name,'passed':True,'command':cmd})
        (self.out/'reply-contracts/results.json').write_text(json.dumps(results,indent=2)+'\n')

    def test_ten_original_canary_stores_and_sec_main_arguments(self):
        for c,t in self.traces:
            p={v['name']:v for v in t['xbl_prefix_checkpoints']};source=p['sec-canary-source-return'];stored=p['sec-canary-stored']
            self.assertEqual(source['registers']['x0'],self.reply['buffer_word']);self.assertEqual(source['canary_word'],'0xc0c0c0c0')
            self.assertEqual(stored['canary_word'],self.reply['buffer_word']);self.assertEqual(stored['registers']['pc'],'0x9fc0cd58')
            self.assertEqual([p['canary-buffer-return']['registers']['x'+str(i)] for i in range(4)],['0x0','0x8','0x0','0x0'])
            for name in ('sec-canary-init-return','sec-main-before-call','sec-main-entry'):self.assertEqual(p[name]['registers']['sp'],'0x9ffcfd00')
            for name in ('sec-main-before-call','sec-main-entry'):self.assertEqual([p[name]['registers']['x0'],p[name]['registers']['x1']],['0x9ff90000','0x3fd00'])
            self.assertEqual(t['calls'],self.traces[0][1]['calls']);self.assertEqual(len(t['calls']),263);self.assertEqual(t['pmic_map_ledger'],[6]*241)
            self.assertEqual(len(t['xbl_forward_calls']),0 if c['el2'] else 2)
            stdout=(Path(c['trace']).parent/'stdout.txt').read_text();self.assertEqual(stdout.count(MARKER),1);self.assertEqual(stdout.count('MODEL_XBL_BUFFER_ORIGINAL_SLICES'),1)

    def test_level_cache_guards_and_pending_read_without_mmio_reply(self):
        for c,t in self.traces:
            p={v['name']:v for v in t['xbl_prefix_checkpoints']};base=p['sec-dcache-enabled']['registers']
            for pc in POINTS:
                v=next(z for z in t['xbl_prefix_checkpoints'] if z['name']==POINTS[pc]);r=v['registers']
                self.assertEqual((v['query_reply_count'],v['buffer_reply_count'],v['canary_reply_count']),(1,1,1))
                for n in ('SCTLR','SCTLR_EL2','HCR_EL2'):self.assertEqual(r[n],base[n])
                self.assertEqual(int(r['cpsr'],16)&0x3cf,int(base['cpsr'],16)&0x3cf)
                self.assertEqual(v['canary_guard_before_hex'],self.contract['canary_guard_before_hex']);self.assertEqual(v['canary_guard_after_hex'],self.contract['canary_guard_after_hex'])
                for rr in v['workspace_after']:self.assertEqual(rr['guard_before_hex'],rr['guard_after_hex']);self.assertEqual(rr['guard_after_hex'],'a5'*16)
            last=t['xbl_prefix_checkpoints'][-1];self.assertEqual(last['registers']['pc'],'0x9fc0e37c');self.assertEqual(last['registers']['sp'],'0x9ffcfcc0')
            self.assertEqual(last['pending_read'],{'address':'0x146bf944','size':4,'wait_while_value':'0x55444247','executed':False})

    def test_pre_second_controls_and_actual_tz_request_derivations(self):
        for c,t in self.traces:
            d=Path(c['manifest']).parent;control=json.loads(Path(c['before_canary']).read_text());last=control['xbl_prefix_checkpoints'][-1]
            self.assertEqual(last['canary_reply_count'],0);self.assertEqual(last['buffer_hex'],'00'*8);self.assertEqual(last['canary_word'],'0xc0c0c0c0')
            self.assertNotIn(MARKER,(d/'before-canary/stdout.txt').read_text())
            regs=last['registers'] if c['el2'] else control['xbl_qhee_handler']['registers'];s=json.loads((d/'tz-buffer-slices.json').read_text())
            words=[int(regs['x'+str(i)],16) for i in range(14)];self.assertEqual(words,WORDS['el2' if c['el2'] else 'stock'])
            self.assertEqual(s,run(words));self.assertIsNone(s['decode']['validation_status']);self.assertEqual(s['reply_x0_x7'],['0x0','0x8']+['0x0']*6)
            self.assertEqual(t['xbl_canary_reply_model']['derivations']['el2' if c['el2'] else 'stock']['derivation_sha256'],hashlib.sha256(json.dumps(s,sort_keys=True).encode()).hexdigest())

    def test_earlier_stack_and_first_buffer_boundaries(self):
        for c in self.cases[-2:]:
            for flag,name,stop in (('--xbl-stack-return','before-cache','0x9fc0cf38'),('--xbl-stack-buffer','before-buffer','0x9fc28468')):
                d=Path(c['manifest']).parent/name
                subprocess.run([sys.executable,str(self.tracer),'--manifest',c['manifest'],'--out',str(d),flag],check=True,stdout=subprocess.DEVNULL)
                r=json.loads((d/'manifest.json').read_text());self.assertEqual(r['xbl_prefix_checkpoints'][-1]['registers']['pc'],stop);self.assertNotIn('xbl_canary_contract',r)
                self.assertNotIn(MARKER,(d/'stdout.txt').read_text())

    def test_current_provenance_and_unchanged_backups(self):
        for c,t in self.traces:
            p=Path(c['manifest']);m=json.loads(p.read_text());self.assertEqual(t['xbl_canary_contract'],self.contract);self.assertEqual(t['xbl_canary_reply_model'],self.reply)
            self.assertEqual(t['input_manifest_sha256'],hashlib.sha256(p.read_bytes()).hexdigest());self.assertEqual(t['tool_sha256'],hashlib.sha256(self.tracer.read_bytes()).hexdigest())
            self.assertEqual(t['el3_sha256'],hashlib.sha256((p.parent/'el3.elf').read_bytes()).hexdigest())
            for path,h in m['tool_sha256'].items():self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),h)
        for n,h in self.pins.items():self.assertEqual(hashlib.sha256((ROOT/'backups/nio-firmware-20260927T163534Z'/n).read_bytes()).hexdigest(),h)

if __name__=='__main__':unittest.main()
