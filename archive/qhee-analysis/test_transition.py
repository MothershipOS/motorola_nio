#!/usr/bin/env python3
"""Bounded terminal transition: actual EL2 execution after the MMU switch."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from handoff import loaded_code
from qhee import QheeImage, ROOT
from test_entry import complete_args
from transition import build, START, END, ORIGINAL


class TransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image=QheeImage();cls.out=ROOT/'kernel-work/out/qhee-transition-tests'
        cls.out.mkdir(parents=True,exist_ok=True)
        cls.script=Path(__file__).with_name('run_qemu.py')
        cls.tracer=Path(__file__).with_name('trace_bridge_handoff.py')

    def test_exact_two_patch_ranges(self):
        base,original=self.image.code_bytes();code,m=loaded_code(self.image,'el2-diag-mmu-off');stub,sm=build()
        expected=bytearray(original);struct.pack_into('<I',expected,0x1d8,0xd2807925)
        expected[START-base:END-base]=stub
        self.assertEqual(code,expected);self.assertEqual(len(code),len(original))
        self.assertEqual(original[START-base:END-base],ORIGINAL)
        self.assertEqual(len(stub),124);self.assertEqual(stub[-4:],struct.pack('<I',0xd69f03e0))
        self.assertEqual(m['terminal_transition'],sm);self.assertEqual(len(m['changes']),2)
        self.assertEqual(m['loaded_code_sha256'],hashlib.sha256(code).hexdigest())

    def test_terminal_instruction_guard(self):
        base,code=self.image.code_bytes();changed=bytearray(code);changed[START-base]^=1
        class Fake:
            data=self.image.data
            code=self.image.code
            def code_bytes(self):return base,bytes(changed)
        with self.assertRaisesRegex(ValueError,'terminal register-clearing'):loaded_code(Fake(),'el2-diag-mmu-off')

    def test_memsz_guard(self):
        class Fake:
            data=self.image.data
            code=replace(self.image.code,memsz=self.image.code.memsz-4096)
            code_bytes=self.image.code_bytes
        with self.assertRaisesRegex(ValueError,'clean range'):loaded_code(Fake(),'el2-diag-mmu-off')

    def test_non_pinned_rejected(self):
        class Fake:
            data=b'not original firmware'
            code_bytes=self.image.code_bytes
        with self.assertRaisesRegex(ValueError,'pinned'):loaded_code(Fake(),'el2-diag-mmu-off')

    def test_no_stack_or_out_of_block_control_flow(self):
        code,_=build();instructions=list(Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(code,START))
        self.assertEqual(len(instructions),31)
        for ins in instructions:
            self.assertNotIn('sp',ins.op_str)
            self.assertNotIn(ins.mnemonic,('ldr','str','stp','ldp','bl','blr','br'))
            if ins.mnemonic.startswith('b.'):
                self.assertTrue(START<=int(ins.op_str.lstrip('#'),16)<END)
        maintenance=[(i.mnemonic,i.op_str) for i in instructions if i.mnemonic in ('dc','ic','dsb','isb')]
        self.assertEqual(maintenance,[('dc','cvac, x1'),('dc','cvac, x1'),('dsb','sy'),('ic','iallu'),('dsb','sy'),('isb',''),('isb','')])
        self.assertEqual([(hex(i.address),i.op_str) for i in instructions if i.mnemonic=='msr'],[('0x80040310','sctlr_el2, x4')])

    def test_cli_dependencies(self):
        for args in ([],['--bridge-prng-word','1'],['--payload-address','0x90000000']):
            with self.subTest(args=args):
                r=subprocess.run([sys.executable,str(self.script),'--handoff-experiment','el2-diag-mmu-off']+args,capture_output=True,text=True)
                self.assertEqual(r.returncode,2);self.assertIn('requires --bridge-prng-word and --payload-address',r.stderr)

    def test_complete_cold_path_and_switch(self):
        reports=[]
        for clock in ('off','on'):
            traces=[]
            for experiment in ('spsr-el2h','el2-diag-mmu-off'):
                d=self.out/(clock+'-'+experiment)
                subprocess.run([sys.executable,str(self.script)]+complete_args(clock,d)+['--handoff-experiment',experiment],check=True,stdout=subprocess.DEVNULL)
                m=json.loads((d/'manifest.json').read_text())
                subprocess.run([sys.executable,str(self.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace')],check=True,stdout=subprocess.DEVNULL)
                t=json.loads((d/'trace/manifest.json').read_text());traces.append(t)
                if experiment=='spsr-el2h':
                    self.assertEqual(m['outcome'],'qhee_fatal_watchdog_request');continue
                with self.subTest(clock=clock):
                    self.assertEqual(m['outcome'],'synthetic_probe_reached');self.assertEqual(m['status'],'exited')
                    self.assertEqual(m['exit'],0);self.assertIsNone(m['stop']);self.assertEqual(m['stderr'].splitlines()[-1],'EL2')
                    self.assertEqual(len(t['checkpoints']),11)
                    entry,before,after,eret=[c['registers'] for c in t['checkpoints'][-4:]]
                    self.assertEqual(entry['SCTLR_EL2'],'0x8100f');self.assertEqual(before['SCTLR_EL2'],'0x8100f')
                    self.assertEqual(before['x0'],'0x40');self.assertEqual(before['x1'],'0x90001000');self.assertEqual(before['x2'],'0x90001000')
                    self.assertEqual(before['x3'],'0x1005');self.assertEqual(before['x4'],'0x8000a')
                    self.assertEqual(after['SCTLR_EL2'],'0x8000a');self.assertEqual(eret['SCTLR_EL2'],'0x8000a')
                    self.assertEqual(int(eret['SCTLR_EL2'],16),int(entry['SCTLR_EL2'],16)&~0x1005)
                    self.assertEqual(eret['HCR_EL2'],entry['HCR_EL2']);self.assertEqual(eret['sp'],entry['sp'])
                    self.assertTrue(all(eret['x'+str(i)]=='0x0' for i in range(4)))
                    self.assertTrue(all(int(c['registers']['cpsr'],16)&0x3cf==0x3c9 for c in t['checkpoints'][-4:]))
                    self.assertEqual(t['after_eret']['pc'],'0x90000000');self.assertEqual(t['after_eret']['cpsr'],'0x3c9')
                    self.assertEqual(t['after_first_fetch']['pc'],'0x90000004');self.assertEqual(t['after_first_fetch']['ESR_EL2'],'0x0')
                    mappings=t['transition_mapping_checks'];self.assertEqual([len(r['pages']) for r in mappings],[587,1])
                    self.assertTrue(all(p['pa']==p['va'] and p['mair_attribute'] in ('0x44','0xff') for r in mappings for p in r['pages']))
                    self.assertTrue(mappings[0]['pages'][0]['executable']);self.assertFalse(mappings[1]['pages'][0]['executable'])
                    self.assertEqual(t['pmic_map_ledger'],[6]*241)
                    self.assertEqual(t['model_counts'],{'bridge_prng_count':1,'pmic_region_map_count':241,'handoff_prng_count':3,'pil_empty_regions_count':1})
                    self.assertEqual(t['bridge_record_handle_before_eret'],'0x53484d0000000001')
                    self.assertFalse(any('NIO_IMEM_DENIED' in line for line in m['stderr'].splitlines()))
                reports.append({'clock':clock,'manifest':str(d/'manifest.json'),'trace':str(d/'trace/manifest.json')})
            self.assertEqual(traces[0]['calls'],traces[1]['calls'])
            self.assertEqual(traces[0]['checkpoints'][:7],traces[1]['checkpoints'][:7])
            self.assertEqual(traces[0]['stage2_walks'],traces[1]['stage2_walks'])
            self.assertEqual(traces[0]['el2_stage1_walks'],traces[1]['el2_stage1_walks'])
        (self.out/'results.json').write_text(json.dumps(reports,indent=2)+'\n')

    def test_tracer_rejects_changed_stub(self):
        d=self.out/'tampering-source'
        subprocess.run([sys.executable,str(self.script)]+complete_args('off',d)+['--handoff-experiment','el2-diag-mmu-off'],check=True,stdout=subprocess.DEVNULL)
        code=bytearray((d/'hyp-code.bin').read_bytes());code[START-0x80040000]^=1;(d/'hyp-code.bin').write_bytes(code)
        r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace')],capture_output=True,text=True)
        self.assertEqual(r.returncode,2);self.assertIn('Unexpected loaded QHEE code bytes',r.stderr)


if __name__=='__main__':unittest.main()
