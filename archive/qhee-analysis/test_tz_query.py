#!/usr/bin/env python3
"""Original TZ query slices and exact reply advancing XBL to its buffer call."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
from qhee import ROOT
from tz_query import run,decode,marshal,lookup,reply_model,inventory
from xbl_target import payload
from xbl_stack import buffer_contract
from test_entry import complete_args
from test_replay import caller_source
from test_bridge import caller
from test_late_init import symbols,machine
from run_qemu import compile_elf,environment,decode_stop


class TzQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'kernel-work/out/qhee-tz-query-tests';cls.out.mkdir(parents=True,exist_ok=True)
        cls.runner=Path(__file__).with_name('run_qemu.py');cls.tracer=Path(__file__).with_name('trace_bridge_handoff.py')
        cls.cases=[];cls.traces=[]
        cls.backup=ROOT/'backups/nio-firmware-20260927T163534Z'
        cls.before={n:hashlib.sha256((cls.backup/n).read_bytes()).hexdigest() for n in ('hyp_a.img','tz_a.img','xbl_a.img','devcfg_a.img')}
        for profile in ('synthetic-masked','tz-frame-hcr-zero','tz-frame-hcr-rw'):
            for clock in (('off',) if profile=='synthetic-masked' else ('off','on')):
                for el2 in (False,True):
                    d=cls.out/(profile+'-'+clock+'-'+('el2' if el2 else 'stock'))
                    a=complete_args(clock,d);a[a.index('--payload-address')+1]='0x9fc00000'
                    a+=['--prepare-only','--xbl-workspace-sentinel','--xbl-query-reply','--entry-state-model',profile]
                    if el2:a+=['--handoff-experiment','el2-xbl-masked-mmu-off']
                    subprocess.run([sys.executable,str(cls.runner)]+a,check=True,stdout=subprocess.DEVNULL)
                    subprocess.run([sys.executable,str(cls.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace'),'--xbl-stack-buffer'],check=True,stdout=subprocess.DEVNULL)
                    c={'profile':profile,'clock':clock,'el2':el2,'manifest':str(d/'manifest.json'),'trace':str(d/'trace/manifest.json')}
                    cls.cases.append(c);cls.traces.append((c,json.loads(Path(c['trace']).read_text())))
        (cls.out/'results.json').write_text(json.dumps(cls.cases,indent=2)+'\n')

    def test_original_registry_and_handler(self):
        r=run();self.assertEqual(r['query_registry']['x0'],'0x0')
        self.assertEqual(r['query_registry']['descriptor']['handler'],'0x1c06705c')
        self.assertEqual(r['query_registry']['descriptor']['arginfo'],'0x1')
        self.assertEqual(r['target_registry']['x0'],'0x1');self.assertEqual(r['reply_x0_x3'],['0x0']*4)
        self.assertEqual(r['query_registry']['guard_after_hex'],'a5'*40)
        m=reply_model();self.assertFalse(m['queried_function_registered']);self.assertEqual(m['query_handler'],'0x1c06705c')
        self.assertEqual(m['derivation_sha256'],hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest())
        with patch('tz_handoff.Path.read_bytes',return_value=b'changed'):
            with self.assertRaisesRegex(ValueError,'pinned TZ'):inventory()

    def test_actual_registers_decode_without_pointer_dereference(self):
        for case,t in self.traces:
            p=next(p for p in t['xbl_prefix_checkpoints'] if p['name']=='stack-before-availability-smc')
            words=[int(p['registers']['x'+str(i)],16) for i in range(14)];r=run(words)
            (Path(case['manifest']).parent/'tz-query-slices.json').write_text(json.dumps(r,indent=2)+'\n')
            self.assertEqual(r['decode']['stop'],'0x1c067664');self.assertEqual(r['decode']['validation_status'],'0x0')
            self.assertEqual(r['reply_x0_x3'],['0x0']*4)
            self.assertTrue(all(int(a['address'],16)!=0x801cba78 for stage in (r['decode'],r['marshal']) for a in stage['reads']))
            self.assertIn('0x1c0679e0',r['marshal']['pcs']);self.assertIn('0x1c06705c',r['marshal']['pcs'])
        words=[0x02000601,1,0xffff000002000602,0xffffabcd9ffd0000,0,1,0x801cba78]+[0]*7
        r=run(words);norm=bytes.fromhex(r['decode']['normalized_hex'])
        self.assertEqual(struct.unpack_from('<Q',norm,16)[0],0x02000602)
        self.assertEqual(struct.unpack_from('<Q',norm,24)[0],0x9ffd0000)
        self.assertEqual(r['reply_x0_x3'],['0x0']*4)

    def test_original_argument_count_type_rejections(self):
        for info,status in ((0,'0xfffffffb'),(2,'0xfffffffb'),(0x11,'0xfffffff6')):
            r=decode([0x02000601,info,0x02000602]+[0]*11)
            self.assertEqual(r['stop'],'0x1c06748c');self.assertEqual(r['validation_status'],status)
        with self.assertRaisesRegex(ValueError,'fourteen'):decode([1,2])
        d=run()['decode'];desc=bytearray(bytes.fromhex(d['descriptor_hex']));struct.pack_into('<Q',desc,16,0x1c054b30)
        with self.assertRaisesRegex(ValueError,'restricted'):marshal(d['normalized_hex'],desc.hex())

    def test_availability_value_separate_from_transport_status(self):
        for target,available in ((0x02000602,0),(0x02000601,1),(0x02000a01,1),(0x02ffffff,0)):
            r=run([0x02000601,1,target]+[0]*11)
            self.assertEqual(r['marshal']['reply_x0_x7'][:4],['0x0',hex(available),'0x0','0x0'])
        l=lookup(0x02000a01);self.assertEqual(l['descriptor']['handler'],'0x1c054b30')
        self.assertEqual(l['descriptor']['arginfo'],'0x22');self.assertEqual(l['descriptor']['flags'],'0x1')

    def test_finite_reply_assembly_preservation_and_denials(self):
        qemu,env=environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64');results=[]
        names=['valid','disabled','wrong-site','wrong-el','wrong-immediate','wrong-fid','wrong-count','wrong-target','wrong-x3','wrong-x4','wrong-x5','wrong-x6','wrong-x7','not-ready','consumed','repeat']
        for name in names:
            d=self.out/'reply-contracts'/name;d.mkdir(parents=True,exist_ok=True)
            defs=['-DSHM_BRIDGE_MODEL_HANDLE=1','-DPRNG_MODEL_WORD=0x736d656d','-DBRIDGE_PRNG_MODEL_WORD=1']
            if name!='disabled':defs+=['-DXBL_QUERY_REPLY_MODEL']
            compile_elf(Path(__file__).with_name('emulator')/'start.S',0x40200000,d/'el3.elf',defs);sym=symbols(d/'el3.elf')
            asm,initial=caller_source(0x02000601,1,1 if name=='wrong-el' else 2,int(name=='wrong-immediate'))
            values={2:0x02000602,3:0x9ffd0000,4:0,5:0,6:0,7:0}
            changes={'wrong-fid':(0,0x02000602),'wrong-count':(1,2),'wrong-target':(2,0x02000603),
                     'wrong-x3':(3,0x9ffd0008),'wrong-x4':(4,1),'wrong-x5':(5,2),'wrong-x6':(6,1),'wrong-x7':(7,1)}
            if name in changes:i,v=changes[name];values[i]=v
            for i,v in values.items():asm=asm.replace(f'ldr x{i}, ={initial[i]:#x}',f'ldr x{i}, ={v:#x}');initial[i]=v
            blocks={sym['bridge_prng_count']:struct.pack('<Q',int(name!='not-ready'))}
            if 'xbl_query_count' in sym:blocks[sym['xbl_query_count']]=struct.pack('<Q',int(name=='consumed'))
            caller(d,asm,blocks,[],int(name=='wrong-immediate'),False,name=='repeat')
            a=(d/'caller.S').read_text().replace('.org 0x1aa0','.org '+hex(0x1cc0 if name=='wrong-site' else 0x1cbc))
            (d/'caller.S').write_text(a);compile_elf(d/'caller.S',0x80040000,d/'caller.elf')
            r=subprocess.run(machine(qemu,d/'el3.elf',d/'caller.elf'),capture_output=True,env=env,timeout=5)
            stdout=r.stdout.decode();marker='MODEL_XBL_QUERY_ORIGINAL_TZ_SLICE_REPLY'
            if name=='valid':
                expected=[0]*4+initial[4:]+[0x803f0000,0xa0000000]
                self.assertEqual(stdout.splitlines(),[marker]+[f'{v:016x}' for v in expected])
            else:
                self.assertEqual(stdout.count(marker),int(name=='repeat'))
                self.assertIsNotNone(decode_stop(r.stdout))
            self.assertEqual(r.returncode,0)
            (d/'stdout.txt').write_bytes(r.stdout);(d/'stderr.txt').write_bytes(r.stderr)
            results.append({'case':name,'passed':True,'command':machine(qemu,d/'el3.elf',d/'caller.elf')})
        (self.out/'reply-contracts/results.json').write_text(json.dumps(results,indent=2)+'\n')

    def test_full_qhee_xbl_reply_and_next_buffer_matrix(self):
        baseline=self.traces[0][1]
        for case,t in self.traces:
            points={p['name']:p for p in t['xbl_prefix_checkpoints']};ret=points['stack-query-return'];last=t['xbl_prefix_checkpoints'][-1]
            self.assertEqual([ret['registers']['x'+str(i)] for i in range(4)],['0x0']*4)
            self.assertEqual(last['registers']['pc'],'0x9fc28468');self.assertEqual(last['registers']['sp'],'0x9ffcffb0')
            self.assertEqual(last['request'][:4],['0x2000a01','0x22','0x9fc356c0','0x8'])
            self.assertEqual(last['buffer_hex'],'00'*8);self.assertEqual(last['query_reply_count'],1)
            self.assertEqual(last['stack_globals']['0x9fc356c8'],'0x10');self.assertEqual(last['stack_globals']['0x9fc3d710'],'0x0')
            self.assertEqual(int(last['registers']['cpsr'],16)&15,9 if case['el2'] else 5)
            self.assertEqual(t['xbl_query_reply_model'],reply_model());self.assertEqual(t['xbl_buffer_contract'],buffer_contract())
            self.assertEqual(t['calls'],baseline['calls']);self.assertEqual(t['pmic_map_ledger'],[6]*241)
            self.assertEqual(t['model_counts']['xbl_query_count'],0) # sampled before initial payload ERET
            self.assertEqual((Path(case['trace']).parent/'stdout.txt').read_text().count('MODEL_XBL_QUERY_ORIGINAL_TZ_SLICE_REPLY'),1)
            for region in last['workspace_after']:
                self.assertEqual(region['guard_before_hex'],'a5'*16);self.assertEqual(region['guard_after_hex'],'a5'*16)

    def test_previous_smc_boundary_does_not_consume_reply(self):
        c=self.cases[-1];d=Path(c['manifest']).parent/'before-query'
        subprocess.run([sys.executable,str(self.tracer),'--manifest',c['manifest'],'--out',str(d),'--xbl-stack-smc','--inspect-xbl-smc-route'],check=True,stdout=subprocess.DEVNULL)
        t=json.loads((d/'manifest.json').read_text());self.assertEqual(t['xbl_prefix_checkpoints'][-1]['registers']['pc'],'0x9fc284dc')
        self.assertNotIn('xbl_buffer_contract',t);self.assertEqual((d/'stdout.txt').read_text().count('MODEL_XBL_QUERY_ORIGINAL_TZ_SLICE_REPLY'),0)

    def test_cli_and_reply_metadata_gates(self):
        r=subprocess.run([sys.executable,str(self.runner),'--xbl-query-reply'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2);self.assertIn('requires prepared original XBL',r.stderr)
        p=Path(self.cases[-1]['manifest']);data=p.read_bytes();m=json.loads(data)
        try:
            for value,message in ((None,'requires exact XBL query reply'),({**m['xbl_query_reply_model'],'reply_x0_x3':['0x1']*4},'reply metadata mismatch')):
                n=json.loads(data);n['xbl_query_reply_model']=value;p.write_text(json.dumps(n))
                r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(p),'--out',str(p.parent/'bad-metadata'),'--xbl-stack-buffer'],capture_output=True,text=True)
                self.assertEqual(r.returncode,2);self.assertIn(message,r.stderr)
        finally:p.write_bytes(data)

    def test_evidence_hashes_and_originals(self):
        for case,t in self.traces:
            p=Path(case['manifest']);m=json.loads(p.read_text())
            self.assertEqual(t['input_manifest_sha256'],hashlib.sha256(p.read_bytes()).hexdigest())
            self.assertEqual(t['tool_sha256'],hashlib.sha256(self.tracer.read_bytes()).hexdigest())
            self.assertEqual(m['tool_sha256']['tools/hyp_re/tz_query.py'],inventory()['source_sha256'])
            self.assertEqual(t['el3_sha256'],hashlib.sha256((p.parent/'el3.elf').read_bytes()).hexdigest())
        for name,h in self.before.items():self.assertEqual(hashlib.sha256((self.backup/name).read_bytes()).hexdigest(),h)


if __name__=='__main__':unittest.main()
