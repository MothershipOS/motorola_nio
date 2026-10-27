#!/usr/bin/env python3
"""Original SEC prefix after full cold QHEE: bounded EL1/EL2 controls."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from handoff import loaded_code
from qhee import QheeImage, ROOT
from test_entry import complete_args
from transition import build, START, END, ORIGINAL
from xbl_target import payload


class XblPrefixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'kernel-work/out/qhee-xbl-prefix-tests';cls.out.mkdir(parents=True,exist_ok=True)
        cls.script=Path(__file__).with_name('run_qemu.py');cls.tracer=Path(__file__).with_name('trace_bridge_handoff.py')

    def prepare(self,clock,d,experiment=None):
        args=complete_args(clock,d);args[args.index('--payload-address')+1]='0x9fc00000'
        subprocess.run([sys.executable,str(self.script)]+args+['--prepare-only']+(['--handoff-experiment',experiment] if experiment else []),check=True,stdout=subprocess.DEVNULL)

    def test_original_fv_and_pin(self):
        blob,m=payload();self.assertEqual(len(blob),0x300000)
        self.assertEqual(struct.unpack_from('<I',blob)[0],0x14003314)
        self.assertEqual(hashlib.sha256(blob).hexdigest(),m['segment_sha256'])
        self.assertEqual((m['segment']['size'],m['segment']['memsz'],m['segment']['address']),(0x300000,0x300000,0x9fc00000))
        with patch('xbl_target.Path.read_bytes',return_value=b'changed'):
            with self.assertRaisesRegex(ValueError,'pinned'):payload()

    def test_exact_finite_transition(self):
        diag,dm=build();xbl,xm=build('xbl-prefix')
        self.assertEqual(dm['code_sha256'],'f85cbc9de78eeb5c23a73af4fe7d19def3c0d061132008f67dfd1c15c3a9d30f')
        self.assertEqual(xm['clean_ranges'],[['0x80040000','0x8028b000'],['0x9fc00000','0x9ff00000']])
        self.assertEqual(diag[:44],xbl[:44]);self.assertEqual(diag[52:],xbl[52:]);self.assertEqual(len(xbl),124)
        ins=list(Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(xbl,START))
        self.assertEqual(ins[11].op_str,'x1, #0x9fc0, lsl #16');self.assertEqual(ins[12].op_str,'x2, x1, #0x300, lsl #12')
        self.assertEqual(ins[-1].mnemonic,'eret');self.assertEqual(ins[-1].address,0x80040328)
        for i in ins:
            self.assertNotIn('sp',i.op_str);self.assertNotIn(i.mnemonic,('ldr','str','stp','ldp','bl','blr','br'))
        with self.assertRaisesRegex(ValueError,'Unknown'):build('arbitrary')
        image=QheeImage();base,original=image.code_bytes();code,m=loaded_code(image,'el2-xbl-mmu-off')
        expected=bytearray(original);struct.pack_into('<I',expected,0x1d8,0xd2807925);expected[START-base:END-base]=xbl
        self.assertEqual(code,expected);self.assertEqual(original[START-base:END-base],ORIGINAL);self.assertEqual(m['terminal_transition'],xm)

    def test_cli_bounds_and_prepare_gate(self):
        cases=(['--handoff-experiment','el2-xbl-mmu-off'],
            ['--handoff-experiment','el2-xbl-mmu-off','--bridge-prng-word','1','--payload-address','0x90000000'],
            ['--payload-address','0x9fc00000'],['--prepare-only'],
            ['--payload-address','0x9fc00000','--prepare-only','--handoff-experiment','el2-diag-mmu-off','--bridge-prng-word','1'])
        for args in cases:
            with self.subTest(args=args):
                r=subprocess.run([sys.executable,str(self.script)]+args,capture_output=True,text=True)
                self.assertEqual(r.returncode,2);self.assertTrue('requires' in r.stderr or 'only for XBL' in r.stderr)

    def test_full_cold_path_original_sec_and_controls(self):
        cases=[]
        for clock in ('off','on'):
            traces=[]
            for experiment in (None,'el2-xbl-mmu-off'):
                d=self.out/(clock+'-'+('el2' if experiment else 'stock'));self.prepare(clock,d,experiment)
                m=json.loads((d/'manifest.json').read_text());self.assertEqual(m['status'],'prepared');self.assertEqual(m['outcome'],'prepared_not_executed')
                subprocess.run([sys.executable,str(self.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace'),'--xbl-prefix'],check=True,stdout=subprocess.DEVNULL)
                t=json.loads((d/'trace/manifest.json').read_text());traces.append(t)
                with self.subTest(clock=clock,experiment=experiment):
                    self.assertEqual(t['after_eret']['pc'],'0x9fc00000');self.assertEqual(t['after_first_fetch']['pc'],'0x9fc0cc50')
                    self.assertEqual(t['after_first_fetch']['ESR_EL2'],'0x0')
                    self.assertTrue(all(t['after_first_fetch']['x'+str(i)]=='0x0' for i in range(4)))
                    prefix=t['xbl_prefix_checkpoints'];self.assertEqual(prefix[0]['registers']['pc'],'0x9fc0cd80');self.assertEqual(prefix[-1]['registers']['pc'],'0x9fc0ceb4')
                    self.assertEqual(t['pmic_map_ledger'],[6]*241)
                    self.assertEqual(t['model_counts'],{'bridge_prng_count':1,'pmic_region_map_count':241,'handoff_prng_count':3,'pil_empty_regions_count':1})
                    self.assertEqual(t['bridge_record_handle_before_eret'],'0x53484d0000000001')
                    self.assertTrue(all(c['registers']['ESR_EL2']=='0x0' for c in prefix))
                    level=9 if experiment else 5
                    self.assertTrue(all(int(c['registers']['cpsr'],16)&15==level for c in prefix))
                    self.assertEqual(prefix[2]['registers']['x0'],'0x8' if experiment else '0x4')
                    self.assertEqual(prefix[-1]['registers']['SCTLR'],'0x800000')
                    if experiment:
                        self.assertEqual(len(prefix),7);self.assertEqual(len(t['checkpoints']),11)
                        self.assertTrue(all(int(c['registers']['cpsr'],16)&0x3c0==0x3c0 for c in prefix))
                        self.assertTrue(all(c['registers']['SCTLR_EL2']=='0x8000a' for c in prefix))
                        self.assertEqual(prefix[4]['registers']['HCR_EL2'],'0x80080005')
                        self.assertEqual(prefix[5]['registers']['HCR_EL2'],'0x10');self.assertEqual(prefix[-1]['registers']['HCR_EL2'],'0x10')
                        self.assertEqual(prefix[-1]['registers']['VBAR_EL2'],'0x9ff8c000')
                        mappings=t['transition_mapping_checks'];self.assertEqual([len(r['pages']) for r in mappings],[587,768])
                        self.assertTrue(all(p['pa']==p['va'] and p['mair_attribute'] in ('0x44','0xff') for r in mappings for p in r['pages']))
                        self.assertTrue(all(not p['executable'] for p in mappings[1]['pages']))
                        before=t['checkpoints'][-3]['registers'];self.assertEqual(before['x1'],'0x9ff00000');self.assertEqual(before['x2'],'0x9ff00000')
                    else:
                        self.assertEqual(len(prefix),6);self.assertEqual(len(t['checkpoints']),8);self.assertEqual(t['transition_mapping_checks'],[])
                        self.assertTrue(all(c['registers']['HCR_EL2']=='0x80080005' for c in prefix))
                cases.append({'clock':clock,'experiment':experiment,'manifest':str(d/'manifest.json'),'trace':str(d/'trace/manifest.json')})
            self.assertEqual(traces[0]['calls'],traces[1]['calls']);self.assertEqual(traces[0]['checkpoints'][:7],traces[1]['checkpoints'][:7])
        (self.out/'results.json').write_text(json.dumps(cases,indent=2)+'\n')

    def test_tracer_rejects_payload_tampering(self):
        source=self.out/'payload-tampering';self.prepare('off',source,'el2-xbl-mmu-off')
        path=source/'manifest.json';m=json.loads(path.read_text());original=path.read_bytes()
        def reject(message):
            r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(path),'--out',str(source/'trace'),'--xbl-prefix'],capture_output=True,text=True)
            self.assertEqual(r.returncode,2);self.assertIn(message,r.stderr)
        m['xbl_payload']['segment_sha256']='0'*64;path.write_text(json.dumps(m));reject('XBL payload metadata mismatch')
        m=json.loads(original);i=m['command'].index(f'loader,file={source / "xbl-fv.bin"},addr=0x9fc00000,force-raw=on');m['command'][i]=m['command'][i].replace('0x9fc00000','0x90000000')
        path.write_text(json.dumps(m));reject('Unexpected XBL prefix loader command')
        path.write_bytes(original);blob=bytearray((source/'xbl-fv.bin').read_bytes());blob[0]^=1;(source/'xbl-fv.bin').write_bytes(blob);reject('Unexpected loaded XBL bytes')


if __name__=='__main__':unittest.main()
