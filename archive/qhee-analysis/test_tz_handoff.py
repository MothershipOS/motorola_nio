#!/usr/bin/env python3
"""Pinned original TZ selectors, frame outputs and bounded failure cases."""
import hashlib
import json
import struct
import unittest
from unittest.mock import patch
from qhee import ROOT
from tz_handoff import boot_records, inventory, run, RANGES, STOP


class TzHandoffTests(unittest.TestCase):
    def test_static_buffer_chain(self):
        m=inventory();c=m['buffer_chain'];self.assertEqual(c['entry_pointer_global'],'0x1468d008')
        self.assertEqual(c['early_table'],'0x1c02c008');self.assertEqual(c['secure_table'],'0x1c179c18')
        self.assertEqual(c['size'],'0xe00');self.assertEqual(c['record_stride'],'0x110')
        ins=m['windows']['entry-input-pointers']['instructions']
        self.assertEqual((ins[-1]['mnemonic'],ins[-1]['operands']),('stp','x0, x1, [x2]'))
        self.assertEqual(m['monitor_boot_subdispatch']['first_target'],'0x1c01d8f4')
        self.assertEqual(m['monitor_boot_subdispatch']['second_target'],'0x1c01d924')

    def test_qhee_present_contract_and_original_context_copy(self):
        m=run();s=m['selected']
        self.assertEqual(s,{'next_x0':'0x9fc00000','next_x1':'0x2','next_x2':'0x0','next_x3':'0x0','next_pc':'0x80040000',
            'hcr_rw_selector':'0x0','spsr':'0x89','scr':'0x504'})
        self.assertEqual(m['frame'][:8],['0x1','0x81','0x9fc00000','0x2','0x0','0x0','0x0','0x80040000'])
        self.assertEqual(m['monitor_argument_copy']['x0_x3'],['0x9fc00000','0x2','0x0','0x0'])
        self.assertIn('0x1c04f5c4',m['pcs']);self.assertIn('0x1c04f48c',m['pcs'])
        self.assertEqual(m['executed_instructions'],204)
        self.assertEqual(hashlib.sha256(bytes.fromhex(m['synthetic_inputs']['boot_records_hex'])).hexdigest(),m['synthetic_inputs']['boot_records_sha256'])
        self.assertTrue(all(any(a<=int(pc,16)<b for a,b in RANGES) for pc in m['pcs']))
        self.assertNotIn(hex(STOP),m['pcs'])

    def test_qhee_absent_control(self):
        m=run(False);s=m['selected'];self.assertEqual(s['next_pc'],'0x9fc00000')
        self.assertEqual(s['spsr'],'0x85');self.assertEqual(s['scr'],'0x404');self.assertEqual(s['hcr_rw_selector'],'0x1')
        self.assertEqual(m['monitor_argument_copy']['x0_x3'],['0x0']*4)
        self.assertNotIn('0x1c04f5c4',m['pcs']);self.assertEqual(m['executed_instructions'],133)

    def test_record_width_branches(self):
        results=[]
        for present in (False,True):
            for apps_width in (1,2):
                for hyp_width in ((1,2) if present else (2,)):
                    with self.subTest(present=present,apps=apps_width,hyp=hyp_width):
                        m=run(present,apps_width,hyp_width);s=m['selected']
                        self.assertEqual(s['spsr'],('0x89' if hyp_width==2 else '0x9a') if present else ('0x85' if apps_width==2 else '0x93'))
                        self.assertEqual(s['next_x1'],hex(apps_width) if present else '0x0')
                        self.assertEqual(m['monitor_argument_copy']['x0_x3'],[s['next_x'+str(i)] for i in range(4)])
                        results.append(m)
        out=ROOT/'kernel-work/out/tz-handoff-tests';out.mkdir(parents=True,exist_ok=True)
        (out/'width-controls.json').write_text(json.dumps(results,indent=2)+'\n')

    def test_version_selected_index_and_fallback(self):
        m=run(version=3,selected_index=1);self.assertEqual(m['selected']['next_x0'],'0x80040000')
        self.assertEqual(m['monitor_argument_copy']['x0_x3'],['0x80040000','0x2','0x0','0x0'])
        blob=bytearray(boot_records(False));struct.pack_into('<I',blob,0x18,14)
        m=run(False,records=bytes(blob));self.assertEqual(m['selected']['next_pc'],'0x9fc00000')

    def test_bounded_malformed_inputs(self):
        for kwargs in ({'apps_width':0},{'hyp_width':3},{'version':4},{'selected_index':2}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):boot_records(**kwargs)
        with self.assertRaisesRegex(ValueError,'exactly'):run(records=b'bad')
        blob=bytearray(boot_records());struct.pack_into('<I',blob,0xc,0)
        with self.assertRaisesRegex(RuntimeError,'bounded stop'):run(records=bytes(blob))
        blob=bytearray(boot_records());struct.pack_into('<I',blob,0x18,99);struct.pack_into('<I',blob,0x128,98)
        with self.assertRaisesRegex(RuntimeError,'bounded stop'):run(records=bytes(blob))

    def test_pin_rejection(self):
        with patch('tz_handoff.Path.read_bytes',return_value=b'changed'):
            with self.assertRaisesRegex(ValueError,'pinned'):inventory()
            with self.assertRaisesRegex(ValueError,'pinned'):run()


if __name__=='__main__':unittest.main()
