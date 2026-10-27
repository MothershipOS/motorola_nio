#!/usr/bin/env python3
"""Original TZ restore/ERET controls and terminal unsupported CPU behavior."""
import hashlib
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
from qhee import ROOT
from tz_monitor import run,prepare,inventory,RAM
from tz_handoff import image
from xbl_target import read


class TzMonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'kernel-work/out/tz-monitor-tests';cls.out.mkdir(parents=True,exist_ok=True)
        cls.results={}
        for cpu in ('cortex-a55','cortex-a55,midr=0x51df805e'):
            for present in (True,False):
                for hcr in (0,0x80000000):
                    name=f'{cpu.split(",")[0]}-{"measured-midr" if "," in cpu else "default"}-{present}-{hcr:x}'
                    cls.results[(cpu,present,hcr)]=run(cls.out/name,hcr,present,cpu)
        (cls.out/'results.json').write_text(json.dumps({'cases':[{'cpu':c,'qhee_present':p,'hcr':hex(h),'passed':m['passed']} for (c,p,h),m in cls.results.items()]},indent=2)+'\n')

    def test_original_layout_and_reset_instructions(self):
        m=inventory();self.assertEqual(m['per_cpu_scr_table'],'0x1c0280e8')
        self.assertEqual(m['cpu0_secure_sp_candidate'],'0x1c155290')
        ins=m['windows']['layout-initializer']['instructions']
        self.assertIn(('strb','w10, [x8, #0x158]'),[(i['mnemonic'],i['operands']) for i in ins])
        reset=m['windows']['early-gic-and-el2-reset']['instructions']
        self.assertIn(('msr','sctlr_el2, xzr'),[(i['mnemonic'],i['operands']) for i in reset])
        tail=m['windows']['smc-handler-return']['instructions']
        self.assertEqual(tail[-1]['mnemonic'],'eret');self.assertEqual(tail[-1]['address'],'0x1c0192a8')

    def test_qhee_present_hcr_preserved_and_el2(self):
        for hcr in (0,0x80000000):
            m=self.results[('cortex-a55',True,hcr)];r=m['trace']['terminal'];c=m['trace']['checkpoints']
            self.assertEqual(r['HCR_EL2'],hex(hcr));self.assertEqual(r['pc'],'0x80040000')
            self.assertEqual(r['cpsr'],'0x89');self.assertEqual(r['SCR_EL3'],'0x535')
            self.assertEqual([r['x'+str(i)] for i in range(4)],['0x9fc00000','0x2','0x0','0x0'])
            self.assertEqual(c[0]['registers']['SCTLR_EL2'],'0x30c50830')
            self.assertEqual(c[2]['registers']['SCTLR_EL2'],'0x0')
            self.assertEqual(struct.unpack_from('<I',bytes.fromhex(c[-1]['scr_table']))[0],0x505)
            self.assertEqual(m['trace']['after_diagnostic_reads']['x20'],'0x8')
            self.assertEqual(m['trace']['after_diagnostic_reads']['x21'],'0x80')
            self.assertEqual(m['trace']['after_diagnostic_reads']['x22'],'0x0')

    def test_absent_control_forces_rw_and_el1(self):
        for hcr in (0,0x80000000):
            m=self.results[('cortex-a55',False,hcr)];r=m['trace']['terminal']
            self.assertEqual(r['HCR_EL2'],'0x80000000');self.assertEqual(r['pc'],'0x9fc00000')
            self.assertEqual(r['cpsr'],'0x85');self.assertEqual(r['SCR_EL3'],'0x435')
            self.assertEqual([r['x'+str(i)] for i in range(4)],['0x0']*4)
            self.assertEqual(m['trace']['after_diagnostic_reads']['x20'],'0x4')

    def test_captured_cpu_identity_control(self):
        sample=ROOT/'reports/nio-diag-boot-20261004-kvm/linux/cpuinfo.txt'
        text=sample.read_text();self.assertIn('CPU implementer\t: 0x51',text)
        self.assertIn('CPU variant\t: 0xd',text);self.assertIn('CPU part\t: 0x805',text);self.assertIn('CPU revision\t: 14',text)
        for present in (True,False):
            for hcr in (0,0x80000000):
                a=self.results[('cortex-a55',present,hcr)]['trace']['terminal']
                b=self.results[('cortex-a55,midr=0x51df805e',present,hcr)]['trace']['terminal']
                self.assertEqual(a,b)

    def test_original_backing_and_translated_bytes(self):
        data,segments=image()
        for m in self.results.values():
            self.assertTrue(m['original_translated_blocks'])
            addresses={int(b['address'],16) for b in m['original_translated_blocks']}
            self.assertIn(0x14680614,addresses)
            for block in m['original_translated_blocks']:
                blob=read(data,segments,int(block['address'],16),block['size'])
                self.assertEqual(hashlib.sha256(blob).hexdigest(),block['sha256'])
            for region in m['ram_regions']:
                blob=Path(region['path']).read_bytes();self.assertEqual(hashlib.sha256(blob).hexdigest(),region['sha256'])
                for segment in segments:
                    a=max(int(region['base'],16),segment['address']);b=min(int(region['base'],16)+region['size'],segment['address']+segment['size'])
                    if a<b:self.assertEqual(blob[a-int(region['base'],16):b-int(region['base'],16)],read(data,segments,a,b-a))
            probe=Path(m['ram_regions'][0]['path']).parent/'arrival.bin'
            ins=list(Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(probe.read_bytes(),int(m['target'],16)))
            self.assertEqual([i.mnemonic for i in ins],['mrs','mrs','mrs','nop'])

    def test_unsupported_cpu_is_terminal(self):
        out=self.out/'unsupported-a76'
        with self.assertRaisesRegex(ValueError,'Unexpected original monitor'):run(out,cpu='cortex-a76')
        m=json.loads((out/'manifest.json').read_text());self.assertFalse(m['passed'])
        self.assertEqual(m['trace']['terminal']['pc'],'0x146838e4')
        self.assertEqual(m['trace']['checkpoints'][-1]['name'],'terminal-failure')
        self.assertNotIn('after_diagnostic_reads',m['trace'])

    def test_guards_and_pin(self):
        with self.assertRaisesRegex(ValueError,'HCR'):prepare(self.out/'invalid',1)
        with self.assertRaisesRegex(ValueError,'CPU'):prepare(self.out/'invalid',cpu='max')
        with patch('tz_handoff.Path.read_bytes',return_value=b'changed'):
            with self.assertRaisesRegex(ValueError,'pinned'):inventory()


if __name__=='__main__':unittest.main()
