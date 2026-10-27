#!/usr/bin/env python3
"""Full cold initialization with an isolated loaded-code EL2 experiment."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from handoff import loaded_code
from qhee import QheeImage, ROOT


def complete_args(clock, out):
    backup=ROOT/'backups/nio-firmware-20260927T163534Z'
    captures=ROOT/'reports'
    options=['--qemu',str(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64'),
        '--soc-hw-version','0x60080201','--devcfg',str(backup/'devcfg_a.img'),
        '--psci-version','0x10001','--prng-word','0x736d656d','--gcc-mmu-clocks',clock,
        '--shm-bridge-handle','0x53484d0000000001','--bridge-prng-word','0x736d656d736d656d',
        '--payload-address','0x90000000','--out',str(out)]
    for flag,folder in (
        ('secure-state-sample','nio-scm-live-20260928-direct'),('smem-sample','nio-smem-layout-20260928-v7'),
        ('smmu-ids','nio-mmu-ids-active-20260928'),('qfprom-sample','nio-gcc-mmu-checkpoint-20260928'),
        ('cmd-db-sample','nio-cmd-db-pointer-20261005'),('tz-log-sample','nio-tz-log-pointer-20261005'),
        ('pmic-arb-sample','nio-pmic-arbiter-20261005'),('pmic-owner-sample','nio-pmic-owners-20261005'),
        ('pmic-secondary-sample','nio-pmic-secondary-map-20261005')):
        options+=['--'+flag,str(captures/folder/'manifest.json')]
    options+=['--'+flag for flag in (
        'smem-version-write','smem-rlock-zero','smem-mutex','smem-ram-table-write',
        'smmu-firmware-counts','smmu-control','smmu-contexts','qcom-timer','nonsecure-query-unsupported',
        'smem-toc-assign','smem-partition-assign','tz-channel-assign','tz-channel-21-42-assign',
        'cmd-db-assign','hyp-log-share','imem-publications','pmic-region-map','pil-empty-region-list',
        'imem-ready-publication','handoff-prng')]
    return options


class EntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image=QheeImage();cls.out=ROOT/'kernel-work/out/qhee-entry-tests'
        cls.out.mkdir(parents=True,exist_ok=True)
        cls.script=Path(__file__).with_name('run_qemu.py')
        cls.tracer=Path(__file__).with_name('trace_bridge_handoff.py')

    def test_stock_code_immutable(self):
        original=self.image.data
        code,m=loaded_code(self.image)
        self.assertEqual(code,self.image.code_bytes()[1]);self.assertEqual(original,self.image.data)
        self.assertEqual(m['original_code_sha256'],m['loaded_code_sha256']);self.assertEqual(m['changes'],[])

    def test_single_word_experiment(self):
        base,original=self.image.code_bytes();code,m=loaded_code(self.image,'spsr-el2h')
        off=0x800401d8-base
        self.assertEqual(original[:off]+struct.pack('<I',0xd2807925)+original[off+4:],code)
        self.assertEqual(struct.unpack_from('<I',original,off)[0],0xd28010a5)
        self.assertEqual(m['loaded_code_sha256'],hashlib.sha256(code).hexdigest())
        self.assertEqual(len(m['changes']),1)

    def test_unknown_experiment(self):
        with self.assertRaisesRegex(ValueError,'Unknown'):loaded_code(self.image,'arbitrary')

    def test_pin_rejection(self):
        class Fake:
            data=b'changed'
            code_bytes=self.image.code_bytes
        with self.assertRaisesRegex(ValueError,'pinned'):loaded_code(Fake(),'spsr-el2h')

    def test_instruction_guard(self):
        base,code=self.image.code_bytes();changed=bytearray(code);changed[0x1d8]^=1
        class Fake:
            data=self.image.data
            def code_bytes(self):return base,bytes(changed)
        with self.assertRaisesRegex(ValueError,'Unexpected original'):loaded_code(Fake(),'spsr-el2h')

    def test_cli_dependencies(self):
        for args in ([],['--bridge-prng-word','1'],['--payload-address','0x90000000']):
            with self.subTest(args=args):
                r=subprocess.run([sys.executable,str(self.script),'--handoff-experiment','spsr-el2h']+args,capture_output=True,text=True)
                self.assertEqual(r.returncode,2);self.assertIn('requires --bridge-prng-word and --payload-address',r.stderr)
        r=subprocess.run([sys.executable,str(self.script),'--handoff-experiment','unknown'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2);self.assertIn('invalid choice',r.stderr)

    def test_full_path_differential(self):
        reports=[]
        for clock in ('off','on'):
            traces=[]
            for experiment in (None,'spsr-el2h'):
                d=self.out/(clock+'-'+(experiment or 'stock'));args=complete_args(clock,d)
                if experiment:args+=['--handoff-experiment',experiment]
                subprocess.run([sys.executable,str(self.script)]+args,check=True,stdout=subprocess.DEVNULL)
                m=json.loads((d/'manifest.json').read_text())
                subprocess.run([sys.executable,str(self.tracer),'--manifest',str(d/'manifest.json'),'--out',str(d/'trace')],check=True,stdout=subprocess.DEVNULL)
                t=json.loads((d/'trace/manifest.json').read_text());traces.append(t)
                with self.subTest(clock=clock,experiment=experiment):
                    self.assertEqual(t['model_counts'],{'bridge_prng_count':1,'pmic_region_map_count':241,'handoff_prng_count':3,'pil_empty_regions_count':1})
                    self.assertEqual(t['pmic_map_ledger'],[6]*241)
                    self.assertEqual(t['bridge_record_handle_before_eret'],'0x53484d0000000001')
                    pre=t['checkpoints'][-1]['registers'];post=t['after_eret'];fetch=t['after_first_fetch']
                    self.assertEqual(pre['SCTLR_EL2'],'0x8100f');self.assertEqual(pre['HCR_EL2'],'0x80080005')
                    self.assertTrue(all(pre['x'+str(i)]=='0x0' for i in range(31)))
                    self.assertEqual(post['pc'],'0x90000000')
                    self.assertEqual(t['el2_stage1_walks'][1]['entries'][-1]['pte'],'0x50000090000705')
                    if experiment:
                        self.assertEqual(post['cpsr'],'0x3c9');self.assertEqual(pre['SPSR_EL2'],'0x3c9')
                        self.assertEqual(fetch['pc'],'0x80093200');self.assertEqual(fetch['ESR_EL2'],'0x8600000e')
                        self.assertEqual(fetch['FAR_EL2'],'0x90000000')
                        self.assertEqual(m['outcome'],'qhee_fatal_watchdog_request')
                        self.assertEqual(m['stop']['qhee_fault'],{'address':'0x90000000','pc':'0x90000000'})
                    else:
                        self.assertEqual(post['cpsr'],'0x85');self.assertEqual(fetch['pc'],'0x90000004')
                        self.assertEqual(m['outcome'],'synthetic_probe_reached');self.assertEqual(m['exit'],0)
                reports.append({'clock':clock,'experiment':experiment,'manifest':str(d/'manifest.json'),'trace':str(d/'trace/manifest.json')})
            self.assertEqual(traces[0]['calls'],traces[1]['calls'])
            self.assertEqual(traces[0]['checkpoints'][:-1],traces[1]['checkpoints'][:-1])
            self.assertEqual(traces[0]['stage2_walks'],traces[1]['stage2_walks'])
            self.assertEqual(traces[0]['el2_stage1_walks'],traces[1]['el2_stage1_walks'])
        (self.out/'results.json').write_text(json.dumps(reports,indent=2)+'\n')

    def test_trace_rejects_tampering(self):
        # Generate this fixture independently; reject before launching the debugger.
        source=self.out/'tampering-source'
        subprocess.run([sys.executable,str(self.script)]+complete_args('off',source)+['--handoff-experiment','spsr-el2h'],check=True,stdout=subprocess.DEVNULL)
        m=json.loads((source/'manifest.json').read_text());d=self.out/'tampered';d.mkdir(exist_ok=True)
        code=(source/'hyp-code.bin').read_bytes();(d/'hyp-code.bin').write_bytes(code)
        m['loaded_code']['loaded_code_sha256']='0'*64
        path=d/'manifest.json';path.write_text(json.dumps(m))
        def reject(message):
            r=subprocess.run([sys.executable,str(self.tracer),'--manifest',str(path),'--out',str(d/'trace')],capture_output=True,text=True)
            self.assertEqual(r.returncode,2);self.assertIn(message,r.stderr)
        reject('metadata mismatch')
        m=json.loads((source/'manifest.json').read_text());path.write_text(json.dumps(m))
        altered=bytearray(code);altered[0]^=1;(d/'hyp-code.bin').write_bytes(altered)
        reject('Unexpected loaded QHEE code bytes')


if __name__=='__main__':unittest.main()
