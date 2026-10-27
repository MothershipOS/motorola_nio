#!/usr/bin/env python3
"""Exact buffer reply and original XBL stack-sizing return, offline only."""
import hashlib,json,struct,subprocess,sys,unittest
from pathlib import Path
from qhee import ROOT
from tz_buffer import run,reply_model
from xbl_stack import return_contract
from test_entry import complete_args
from test_replay import caller_source
from test_bridge import caller
from test_late_init import symbols,machine
from run_qemu import compile_elf,environment,decode_stop

class StackReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'kernel-work/out/qhee-stack-return-tests';cls.out.mkdir(exist_ok=True)
        cls.runner=Path(__file__).with_name('run_qemu.py');cls.tracer=Path(__file__).with_name('trace_bridge_handoff.py')
        cls.cases=[];cls.traces=[];cls.reply=reply_model();cls.word=int(cls.reply['buffer_word'],16)
        cls.pins={n:hashlib.sha256((ROOT/'backups/nio-firmware-20260927T163534Z'/n).read_bytes()).hexdigest() for n in ('hyp_a.img','tz_a.img','xbl_a.img','devcfg_a.img','abl_a.img')}
        for profile in ('synthetic-masked','tz-frame-hcr-zero','tz-frame-hcr-rw'):
            for clock in (('off',) if profile=='synthetic-masked' else ('off','on')):
                for el2 in (False,True):
                    d=cls.out/(profile+'-'+clock+'-'+('el2' if el2 else 'stock'))
                    a=complete_args(clock,d);a[a.index('--payload-address')+1]='0x9fc00000'
                    a+=['--prepare-only','--xbl-workspace-sentinel','--xbl-query-reply','--xbl-buffer-reply','--entry-state-model',profile]
                    if el2:a+=['--handoff-experiment','el2-xbl-masked-mmu-off']
                    subprocess.run([sys.executable,str(cls.runner)]+a,check=True,stdout=subprocess.DEVNULL)
                    subprocess.run([sys.executable,str(cls.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace'),'--xbl-stack-return'],check=True,stdout=subprocess.DEVNULL)
                    c={'profile':profile,'clock':clock,'el2':el2,'manifest':str(d/'manifest.json'),'trace':str(d/'trace/manifest.json')}
                    if not el2:
                        subprocess.run([sys.executable,str(cls.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'forward'),'--xbl-stack-buffer','--inspect-xbl-smc-route','--inspect-xbl-qhee-forward'],check=True,stdout=subprocess.DEVNULL)
                        c['forward']=str(d/'forward/manifest.json')
                    cls.cases.append(c);cls.traces.append((c,json.loads(Path(c['trace']).read_text())))
        (cls.out/'results.json').write_text(json.dumps(cls.cases,indent=2)+'\n')

    def test_original_slice_reply_and_contract_pin(self):
        r=run();self.assertEqual(self.reply['derivation_sha256'],hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest())
        self.assertEqual(self.reply['reply_x0_x3'],['0x0','0x8','0x0','0x0']);self.assertEqual(self.word,0x444444dd444444cc)
        c=return_contract(self.word);self.assertEqual(c['consumed_nibble'],'0xc');self.assertEqual(c['stack_size'],'0x3fd00');self.assertEqual(c['adjusted_sp'],'0x9ffcfd00')
        self.assertEqual(return_contract(0)['stack_size'],'0x40000');self.assertEqual(return_contract(15)['stack_size'],'0x3fc40')

    def test_cli_requires_query_and_prepared_payload(self):
        for args,message in ((['--xbl-buffer-reply'],'requires --xbl-query-reply'),(['--xbl-buffer-reply','--xbl-query-reply'],'requires prepared original XBL')):
            r=subprocess.run([sys.executable,str(self.runner)]+args,capture_output=True,text=True)
            self.assertEqual(r.returncode,2);self.assertIn(message,r.stderr)

    def test_reply_metadata_fail_closed(self):
        p=Path(self.cases[-1]['manifest']);data=p.read_bytes();m=json.loads(data)
        try:
            for value,message in ((None,'requires exact XBL buffer reply'),({**m['xbl_buffer_reply_model'],'buffer_hex':'00'*8},'buffer reply metadata mismatch')):
                n=json.loads(data);n['xbl_buffer_reply_model']=value;p.write_text(json.dumps(n))
                r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(p),'--out',str(p.parent/'bad-metadata'),'--xbl-stack-return'],capture_output=True,text=True)
                self.assertEqual(r.returncode,2);self.assertIn(message,r.stderr)
        finally:p.write_bytes(data)

    def test_exact_reply_preservation_and_denials(self):
        qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64');results=[]
        names=['valid-stock','valid-el2','disabled','wrong-site','wrong-el','wrong-immediate','wrong-fid','wrong-count','wrong-buffer','short-size','long-size','wrong-x4','wrong-x5','wrong-x6','wrong-x7','no-bridge','no-query','consumed','preexisting-buffer','wrong-selector','nonempty-cache','repeat']
        for name in names:
            d=self.out/'reply-contracts'/name;d.mkdir(parents=True,exist_ok=True);el2=name=='valid-el2'
            defs=['-DSHM_BRIDGE_MODEL_HANDLE=1','-DPRNG_MODEL_WORD=1','-DBRIDGE_PRNG_MODEL_WORD=1','-DXBL_QUERY_REPLY_MODEL']
            if name!='disabled':defs+=['-DXBL_BUFFER_REPLY_MODEL',f'-DXBL_BUFFER_FIXTURE_WORD={self.word:#x}']
            compile_elf(Path(__file__).with_name('emulator')/'start.S',0x40200000,d/'el3.elf',defs);sym=symbols(d/'el3.elf')
            asm,initial=caller_source(0x2000a01,0x22,1 if name=='wrong-el' else 2,int(name=='wrong-immediate'))
            values={2:0x9fc356c0,3:8,4:0,5:1 if el2 else 0,6:0x801cba78 if el2 else 0,7:0 if el2 else 3}
            changes={'wrong-fid':(0,0x2000a02),'wrong-count':(1,2),'wrong-buffer':(2,0x9fc356c8),'short-size':(3,4),'long-size':(3,16),'wrong-x4':(4,1),'wrong-x5':(5,2),'wrong-x6':(6,1),'wrong-x7':(7,0)}
            if name in changes:i,v=changes[name];values[i]=v
            for i,v in values.items():asm=asm.replace(f'ldr x{i}, ={initial[i]:#x}',f'ldr x{i}, ={v:#x}');initial[i]=v
            blocks={0x9fc356b8:struct.pack('<4Q',0xa5a5a5a5a5a5a5a5,int(name=='preexisting-buffer'),8 if name=='wrong-selector' else 16,0xa5a5a5a5a5a5a5a5),
                    0x9fc3d710:struct.pack('<Q',int(name=='nonempty-cache')),
                    sym['bridge_prng_count']:struct.pack('<Q',int(name!='no-bridge')),
                    sym['xbl_query_count']:struct.pack('<Q',int(name!='no-query'))}
            reads=[0x9fc356b8,0x9fc356c0,0x9fc356c8,0x9fc356d0,0x9fc3d710]
            if 'xbl_buffer_count' in sym:blocks[sym['xbl_buffer_count']]=struct.pack('<Q',int(name=='consumed'));reads+=[sym['xbl_buffer_count']]
            caller(d,asm,blocks,reads,int(name=='wrong-immediate'),False,name=='repeat')
            a=(d/'caller.S').read_text().replace('.org 0x1aa0','.org '+hex(0x1468 if el2 else (0x1cbc if name=='wrong-site' else 0x1aa0)))
            (d/'caller.S').write_text(a);compile_elf(d/'caller.S',0x9fc27000 if el2 else 0x80040000,d/'caller.elf')
            cmd=machine(qemu,d/'el3.elf',d/'caller.elf')
            if el2:
                (d/'bootstrap.S').write_text('.text\n.global _start\n_start:\nldr x0, =0x9fc27000\nbr x0\n')
                compile_elf(d/'bootstrap.S',0x80040000,d/'bootstrap.elf');cmd+=['-device',f'loader,file={d/"bootstrap.elf"}']
            r=subprocess.run(cmd,capture_output=True,env=env,timeout=5);marker='MODEL_XBL_BUFFER_ORIGINAL_SLICES_SYNTHETIC_FIFO_NOT_ENTROPY'
            stdout=r.stdout.decode()
            if name.startswith('valid-'):
                expected=[0,8,0,0]+initial[4:]+[0x803f0000,0xa0000000,0xa5a5a5a5a5a5a5a5,self.word,16,0xa5a5a5a5a5a5a5a5,0,1]
                self.assertEqual(stdout.splitlines(),[marker]+[f'{v:016x}' for v in expected])
            else:self.assertEqual(stdout.count(marker),int(name=='repeat'));self.assertIsNotNone(decode_stop(r.stdout))
            self.assertEqual(r.returncode,0);(d/'stdout.txt').write_bytes(r.stdout);(d/'stderr.txt').write_bytes(r.stderr)
            results.append({'case':name,'passed':True,'command':cmd})
        (self.out/'reply-contracts/results.json').write_text(json.dumps(results,indent=2)+'\n')

    def test_full_original_xbl_stack_return_matrix(self):
        for c,t in self.traces:
            p={v['name']:v for v in t['xbl_prefix_checkpoints']};last=t['xbl_prefix_checkpoints'][-1]
            self.assertEqual(last['registers']['pc'],'0x9fc0cf38');self.assertEqual(last['registers']['sp'],'0x9ffcfd00')
            self.assertEqual(last['registers']['x19'],'0x3fd00');self.assertEqual(int(last['registers']['cpsr'],16)&15,9 if c['el2'] else 5)
            self.assertEqual(p['stack-sizing-return']['registers']['sp'],'0x9ffd0000')
            self.assertEqual([p['stack-buffer-return']['registers']['x'+str(i)] for i in range(4)],['0x0','0x8','0x0','0x0'])
            self.assertEqual(last['buffer_reply_count'],1);self.assertEqual(last['query_reply_count'],1)
            self.assertEqual(t['model_counts']['xbl_buffer_count'],0)
            self.assertEqual(t['xbl_buffer_reply_model'],self.reply);self.assertEqual(t['xbl_stack_return_contract'],return_contract(self.word))
            self.assertEqual(t['calls'],self.traces[0][1]['calls']);self.assertEqual(t['pmic_map_ledger'],[6]*241)
            self.assertEqual(len(t['xbl_forward_calls']),0 if c['el2'] else 1)

    def test_original_cache_update_nibble_and_workspace_guards(self):
        for c,t in self.traces:
            p={v['name']:v for v in t['xbl_prefix_checkpoints']}
            self.assertEqual(p['stack-nibble-cache-published']['stack_globals']['0x9fc3d710'],hex(self.word))
            self.assertEqual(p['stack-nibble-consumed']['stack_globals']['0x9fc3d710'],hex(self.word>>4))
            self.assertEqual(p['stack-sizing-nibble-return']['registers']['x0'],'0xc')
            self.assertEqual(p['stack-size-computed']['registers']['x0'],'0x3fd00')
            for name in ('stack-buffer-return','stack-buffer-invalidate-return','stack-buffer-source-ready','stack-sizing-return','sec-adjusted-stack-before-next-call'):
                self.assertEqual(p[name]['buffer_hex'],self.reply['buffer_hex']);self.assertEqual(p[name]['stack_globals']['0x9fc356c8'],'0x10')
                for rr in p[name]['workspace_after']:self.assertEqual(rr['guard_before_hex'],rr['guard_after_hex']);self.assertEqual(rr['guard_after_hex'],'a5'*16)

    def test_original_stock_forward_changes_x7_and_tz_check_variant(self):
        for c,t in self.traces:
            if c['el2']:continue
            f=json.loads(Path(c['forward']).read_text());h=f['xbl_qhee_handler']
            self.assertEqual(h['registers']['pc'],'0x80041aa0');self.assertEqual(h['registers']['sp'],'0x80208db0')
            self.assertEqual(h['request'],['0x2000a01','0x22','0x9fc356c0','0x8','0x0','0x0','0x0','0x3'])
            words=[int(h['registers']['x'+str(i)],16) for i in range(14)];r=run(words)
            self.assertEqual(r['decode']['stop'],'0x1c065b0c');self.assertIsNone(r['decode']['validation_status']);self.assertEqual(r['reply_x0_x7'],['0x0','0x8']+['0x0']*6)
            (Path(c['forward']).parent/'tz-buffer-slices.json').write_text(json.dumps(r,indent=2)+'\n')
            self.assertEqual((Path(c['forward']).parent/'stdout.txt').read_text().count('MODEL_XBL_BUFFER_ORIGINAL_SLICES'),0)

    def test_earlier_boundaries_and_candidate_route(self):
        for c in self.cases[-2:]:
            d=Path(c['manifest']).parent/'before-buffer';a=[sys.executable,str(self.tracer),'--manifest',c['manifest'],'--out',str(d),'--xbl-stack-buffer','--inspect-xbl-smc-route']
            subprocess.run(a,check=True,stdout=subprocess.DEVNULL);r=json.loads((d/'manifest.json').read_text())
            self.assertEqual(r['xbl_prefix_checkpoints'][-1]['registers']['pc'],'0x9fc28468')
            self.assertNotIn('xbl_stack_return_contract',r);self.assertEqual((d/'stdout.txt').read_text().count('MODEL_XBL_BUFFER_ORIGINAL_SLICES'),0)
            if c['el2']:self.assertEqual(r['xbl_smc_route']['after_instruction']['ELR_EL3'],'0x9fc2846c')

    def test_provenance_and_unchanged_backups(self):
        for c,t in self.traces:
            p=Path(c['manifest']);m=json.loads(p.read_text())
            self.assertEqual(t['input_manifest_sha256'],hashlib.sha256(p.read_bytes()).hexdigest());self.assertEqual(t['tool_sha256'],hashlib.sha256(self.tracer.read_bytes()).hexdigest())
            self.assertEqual(t['el3_sha256'],hashlib.sha256((p.parent/'el3.elf').read_bytes()).hexdigest())
            for path,h in m['tool_sha256'].items():self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),h)
        for n,h in self.pins.items():self.assertEqual(hashlib.sha256((ROOT/'backups/nio-firmware-20260927T163534Z'/n).read_bytes()).hexdigest(),h)

if __name__=='__main__':unittest.main()
