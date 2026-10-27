#!/usr/bin/env python3
"""Derived TZ controls through full cold QHEE and finite EL2/SEC transitions."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from entry_state import model,defines
from handoff import loaded_code
from qhee import QheeImage,ROOT
from test_entry import complete_args
from transition import build,START,END


class TzEntryStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'kernel-work/out/qhee-tz-entry-tests';cls.out.mkdir(parents=True,exist_ok=True)
        cls.script=Path(__file__).with_name('run_qemu.py');cls.tracer=Path(__file__).with_name('trace_bridge_handoff.py')
        cls.cases={}
        for profile in ('tz-frame-hcr-zero','tz-frame-hcr-rw'):
            for clock in ('off','on'):
                for case,experiment,xbl in (('stock',None,False),('spsr-only','spsr-el2h',False),
                    ('el2-diag','el2-diag-masked-mmu-off',False),('xbl-stock',None,True),
                    ('xbl-el2','el2-xbl-masked-mmu-off',True)):
                    cls.cases[(profile,clock,case)]=cls.execute(profile,clock,case,experiment,xbl)
        cls.baseline=cls.execute('synthetic-masked','off','baseline',None,False)
        (cls.out/'results.json').write_text(json.dumps({'cases':[{'profile':p,'clock':c,'case':k,'manifest':str(v[0]),'trace':str(v[0].parent/'trace/manifest.json')} for (p,c,k),v in cls.cases.items()],
            'baseline':str(cls.baseline[0])},indent=2)+'\n')

    @classmethod
    def execute(cls,profile,clock,case,experiment,xbl):
        d=cls.out/(profile+'-'+clock+'-'+case);args=complete_args(clock,d)+['--entry-state-model',profile]
        if experiment:args+=['--handoff-experiment',experiment]
        if xbl:args[args.index('--payload-address')+1]='0x9fc00000';args+=['--prepare-only']
        subprocess.run([sys.executable,str(cls.script)]+args,check=True,stdout=subprocess.DEVNULL)
        subprocess.run([sys.executable,str(cls.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace'),'--inspect-entry']+(['--xbl-prefix'] if xbl else []),check=True,stdout=subprocess.DEVNULL)
        return d/'manifest.json',json.loads((d/'manifest.json').read_text()),json.loads((d/'trace/manifest.json').read_text())

    def test_default_entry_remains_masked(self):
        m=model();self.assertEqual(m['controls'],{'SCR_EL3':'0x501','SPSR_EL3':'0x3c9','SCTLR_EL2':'0x30c50830','HCR_EL2':'0x80000000'})
        self.assertEqual(defines(m),[]);self.assertIsNone(m['derived'])
        t=self.baseline[2];s=t['entry_state_inspection']['initial_qhee_entry']
        self.assertEqual(s['cpsr'],'0x3c9');self.assertEqual(s['SCTLR_EL2'],'0x30c50830')
        self.assertEqual(s['SCR_EL3'],'0x531');self.assertEqual(s['HCR_EL2'],'0x80000000')
        self.assertEqual(t['after_eret']['cpsr'],'0x85')

    def test_derived_entry_matches_original_monitor_controls(self):
        for name in ('tz-frame-hcr-zero','tz-frame-hcr-rw'):
            m=model(name,0x9fc00000);c=m['controls']
            self.assertEqual(c['SCR_EL3'],'0x505');self.assertEqual(c['SPSR_EL3'],'0x89');self.assertEqual(c['SCTLR_EL2'],'0x0')
            self.assertEqual(c['HCR_EL2'],'0x0' if name.endswith('zero') else '0x80000000')
            self.assertEqual(m['arguments'],{'x0':'0x9fc00000','x1':'0x2','x2':'0x0','x3':'0x0'})
            self.assertFalse(m['diagnostic_target_override']);self.assertTrue(model(name)['diagnostic_target_override'])
            self.assertEqual(len(m['derived']['original_instruction_guards']),3)
        for (name,clock,case),(_,m,t) in self.cases.items():
            s=t['entry_state_inspection']['initial_qhee_entry']
            self.assertEqual(s['cpsr'],'0x89');self.assertEqual(s['SCTLR_EL2'],'0x0');self.assertEqual(s['SCR_EL3'],'0x535')
            self.assertEqual(s['HCR_EL2'],m['entry_state_model']['controls']['HCR_EL2'])
            self.assertEqual([s['x'+str(i)] for i in range(4)],[m['synthetic_payload']['address'],'0x2','0x0','0x0'])
            self.assertEqual(m['entry_state_model'],t['entry_state_model'])

    def test_unknown_states_and_changed_firmware_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unknown'):model('unbounded')
        with self.assertRaisesRegex(ValueError,'payload'):model(target=0)
        with patch('tz_handoff.Path.read_bytes',return_value=b'changed'):
            with self.assertRaisesRegex(ValueError,'pinned'):model('tz-frame-hcr-zero')
        with patch('entry_state.read',return_value=b'\x00'*4):
            with self.assertRaisesRegex(ValueError,'instruction'):model('tz-frame-hcr-rw')

    def test_masked_terminal_fits_and_preserves_old_bytes(self):
        md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
        for old,new in (('diagnostic','diagnostic-masked'),('xbl-prefix','xbl-prefix-masked')):
            old_code,om=build(old);code,m=build(new);ins=list(md.disasm(code,START))
            self.assertEqual(len(code),124);self.assertEqual(len(ins),31)
            self.assertEqual((ins[0].mnemonic,ins[0].op_str),('msr','daifset, #0xf'))
            self.assertEqual((ins[6].mnemonic,ins[6].op_str),('add','x2, x1, #0x24b, lsl #12'))
            self.assertEqual(code[28:],old_code[28:]);self.assertEqual(m['clean_ranges'],om['clean_ranges'])
            self.assertEqual(ins[-1].address,0x80040328);self.assertEqual(ins[-1].mnemonic,'eret')
            self.assertTrue(m['mask_daif_before_clean']);self.assertFalse(om['mask_daif_before_clean'])
            self.assertTrue(all('sp' not in i.op_str and i.mnemonic not in ('bl','blr','br','ldr','str','stp','ldp') for i in ins))
        self.assertEqual(build()[1]['code_sha256'],'f85cbc9de78eeb5c23a73af4fe7d19def3c0d061132008f67dfd1c15c3a9d30f')
        q=QheeImage();base,original=q.code_bytes()
        for experiment,variant in (('el2-diag-masked-mmu-off','diagnostic-masked'),('el2-xbl-masked-mmu-off','xbl-prefix-masked')):
            code,m=loaded_code(q,experiment);expected=bytearray(original)
            struct.pack_into('<I',expected,0x1d8,0xd2807925);expected[START-base:END-base]=build(variant)[0]
            self.assertEqual(code,expected);self.assertEqual(len(m['changes']),2)

    def test_cli_requires_bounded_models_and_masked_terminal(self):
        cases=[(['--entry-state-model','unknown'],'invalid choice'),
            (['--entry-state-model','tz-frame-hcr-zero'],'require --bridge-prng-word'),
            (['--entry-state-model','tz-frame-hcr-rw','--bridge-prng-word','1'],'require --bridge-prng-word')]
        for experiment,target in (('el2-diag-mmu-off','0x90000000'),('el2-xbl-mmu-off','0x9fc00000')):
            cases.append((['--entry-state-model','tz-frame-hcr-zero','--bridge-prng-word','1','--payload-address',target,'--handoff-experiment',experiment]+(['--prepare-only'] if 'xbl' in experiment else []),'masks DAIF'))
        for args,message in cases:
            r=subprocess.run([sys.executable,str(self.script)]+args,capture_output=True,text=True)
            self.assertEqual(r.returncode,2);self.assertIn(message,r.stderr)

    def test_stock_cold_path_and_spsr_only_fault_control(self):
        for profile in ('tz-frame-hcr-zero','tz-frame-hcr-rw'):
            for clock in ('off','on'):
                for case in ('stock','spsr-only'):
                    _,m,t=self.cases[(profile,clock,case)];r=t['checkpoints'][-1]['registers']
                    self.assertEqual(int(r['cpsr'],16)&0x3cf,0x89)
                    self.assertEqual(r['SCTLR_EL2'],'0x8100f');self.assertEqual(r['HCR_EL2'],'0x80080005')
                    if case=='stock':
                        self.assertEqual(m['outcome'],'synthetic_probe_reached');self.assertEqual(m['exit'],0)
                        self.assertEqual(t['after_eret']['cpsr'],'0x85');self.assertEqual(t['after_first_fetch']['pc'],'0x90000004')
                        self.assertEqual(m['loaded_code']['changes'],[])
                    else:
                        self.assertEqual(m['outcome'],'qhee_fatal_watchdog_request')
                        self.assertEqual(t['after_eret']['cpsr'],'0x3c9');self.assertEqual(t['after_first_fetch']['ESR_EL2'],'0x8600000e')
                        self.assertEqual(t['after_first_fetch']['FAR_EL2'],'0x90000000')

    def test_el2_diagnostic_masks_before_cache_teardown(self):
        for profile in ('tz-frame-hcr-zero','tz-frame-hcr-rw'):
            for clock in ('off','on'):
                _,m,t=self.cases[(profile,clock,'el2-diag')];c=t['checkpoints'][-5:]
                self.assertEqual([p['name'] for p in c],['diagnostic-transition-entry','after-daif-mask','before-sctlr-disable','after-sctlr-disable','before-payload-eret'])
                self.assertEqual(int(c[0]['registers']['cpsr'],16)&0x3cf,0x89)
                self.assertTrue(all(int(p['registers']['cpsr'],16)&0x3cf==0x3c9 for p in c[1:]))
                self.assertEqual(c[1]['registers']['SCTLR_EL2'],'0x8100f');self.assertEqual(c[3]['registers']['SCTLR_EL2'],'0x8000a')
                self.assertEqual(m['outcome'],'synthetic_probe_reached');self.assertEqual(m['exit'],0)
                self.assertEqual(t['after_eret']['cpsr'],'0x3c9');self.assertEqual(t['after_first_fetch']['pc'],'0x90000004')
                self.assertEqual([len(r['pages']) for r in t['transition_mapping_checks']],[587,1])
                self.assertTrue(all(p['pa']==p['va'] for r in t['transition_mapping_checks'] for p in r['pages']))

    def test_original_sec_prefix_with_both_levels(self):
        for profile in ('tz-frame-hcr-zero','tz-frame-hcr-rw'):
            for clock in ('off','on'):
                for case in ('xbl-stock','xbl-el2'):
                    _,m,t=self.cases[(profile,clock,case)];prefix=t['xbl_prefix_checkpoints'];el2=case=='xbl-el2'
                    self.assertEqual(m['status'],'prepared');self.assertIsNone(m['exit'])
                    self.assertFalse(m['entry_state_model']['diagnostic_target_override'])
                    self.assertEqual(t['after_eret']['pc'],'0x9fc00000');self.assertEqual(t['after_first_fetch']['pc'],'0x9fc0cc50')
                    self.assertEqual(prefix[-1]['registers']['pc'],'0x9fc0ceb4')
                    self.assertTrue(all(int(p['registers']['cpsr'],16)&15==(9 if el2 else 5) for p in prefix))
                    self.assertTrue(all(p['registers']['ESR_EL2']=='0x0' for p in prefix))
                    if el2:
                        self.assertEqual(prefix[-1]['registers']['HCR_EL2'],'0x10')
                        self.assertEqual(prefix[-1]['registers']['VBAR_EL2'],'0x9ff8c000')
                        self.assertTrue(all(int(p['registers']['cpsr'],16)&0x3c0==0x3c0 for p in prefix))
                        self.assertEqual([len(r['pages']) for r in t['transition_mapping_checks']],[587,768])
                    else:self.assertEqual(prefix[-1]['registers']['HCR_EL2'],'0x80080005')

    def test_cold_call_sequence_and_ledgers_unchanged(self):
        expected=self.baseline[2]['calls']
        for _,m,t in self.cases.values():
            self.assertEqual(t['calls'],expected)
            self.assertEqual(t['model_counts'],{'bridge_prng_count':1,'pmic_region_map_count':241,'handoff_prng_count':3,'pil_empty_regions_count':1})
            self.assertEqual(t['pmic_map_ledger'],[6]*241)
            self.assertEqual(t['bridge_record_handle_before_eret'],'0x53484d0000000001')
            self.assertEqual(t['shm_bridge_ledger'],self.baseline[2]['shm_bridge_ledger'])

    def test_tracer_rejects_entry_metadata_changes(self):
        source,m,_=self.cases[('tz-frame-hcr-zero','off','stock')];out=self.out/'tampered';out.mkdir(exist_ok=True)
        (out/'hyp-code.bin').write_bytes((source.parent/'hyp-code.bin').read_bytes())
        for mutation in ('controls','name','arguments'):
            altered=json.loads(source.read_text())
            if mutation=='controls':altered['entry_state_model']['controls']['SPSR_EL3']='0x3c9'
            elif mutation=='name':altered['entry_state_model']['name']='unknown'
            else:altered['entry_state_model']['arguments']['x0']='0x40400000'
            path=out/'manifest.json';path.write_text(json.dumps(altered))
            r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(path),'--out',str(out/'trace')],capture_output=True,text=True)
            self.assertEqual(r.returncode,2);self.assertIn('entry-state',r.stderr.lower())


if __name__=='__main__':unittest.main()
