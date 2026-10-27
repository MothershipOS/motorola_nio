#!/usr/bin/env python3
"""XBL configuration candidate and bounded original-image reads."""
from pathlib import Path
import unittest
from unittest.mock import patch
from xbl_target import inventory, read


class XblTargetTests(unittest.TestCase):
    def test_configured_candidate(self):
        m=inventory();self.assertEqual(len(m['rows']),10);self.assertEqual(m['terminator_address'],'0x14884be0')
        self.assertEqual(m['appsbl']['index'],9);self.assertEqual(m['appsbl']['image_id'],9)
        self.assertEqual(m['appsbl']['configured_address'],'0x9fc00000')
        self.assertEqual(m['appsbl']['callback'],'0x14817b14')
        self.assertEqual(m['configured_entry_branch'],{'address':'0x9fc00000','word':'0x14003314','target':'0x9fc0cc50'})
        self.assertIn('not a capture',m['scope'])

    def test_runtime_interface_boundary(self):
        m=inventory();instructions=m['windows']['interface-config-branch']['instructions']
        self.assertEqual((instructions[-1]['mnemonic'],instructions[-1]['operands']),('br','x1'))
        self.assertEqual((instructions[-3]['mnemonic'],instructions[-3]['operands']),('ldr','x1, [x8, #0x48]'))

    def test_configuration_not_secure_transfer(self):
        m=inventory();c=m['interface_configuration']
        self.assertEqual(c['slot_address'],'0x1488ba38');self.assertEqual(c['slot_target'],'0x14827850')
        self.assertEqual(c['descriptor_destination'],'0x1488bb48');self.assertEqual(c['descriptor_size'],20)
        copy=m['windows']['interface-descriptor-copy']['instructions'][:8]
        self.assertEqual((copy[-1]['mnemonic'],copy[-1]['operands']),('b','#0x148248c4'))
        self.assertFalse(any(i['mnemonic'] in ('smc','eret') for w in ('interface-initializer','interface-slot-target','interface-descriptor-copy') for i in m['windows'][w]['instructions']))

    def test_later_fixed_buffer_secure_call(self):
        m=inventory();c=m['later_secure_call'];self.assertEqual(c['x2'],'0x80716100');self.assertEqual(c['x3'],'0xe00')
        ins={i['address']:(i['mnemonic'],i['operands']) for i in m['windows']['secure-handoff']['instructions']}
        self.assertEqual(ins['0x14817a38'],('add','x19, x19, #0x100'))
        self.assertEqual(ins[c['call_site']],('bl','#0x1482c4e8'))
        wrapper={i['address']:i['mnemonic'] for i in m['windows']['smc-wrapper']['instructions']}
        self.assertEqual(wrapper[c['smc_instruction']],'smc')

    def test_read_bounds(self):
        segments=[{'address':0x1000,'size':8,'offset':0}]
        self.assertEqual(read(b'12345678',segments,0x1002,3),b'345')
        for address,size in ((0x1007,2),(0xfff,1),(0x1000,-1)):
            with self.subTest(address=address,size=size),self.assertRaises(ValueError):read(b'12345678',segments,address,size)
        with self.assertRaisesRegex(ValueError,'outside file'):read(b'123',segments,0x1000,8)

    def test_ambiguous_read(self):
        segment={'address':0x1000,'size':8,'offset':0}
        with self.assertRaisesRegex(ValueError,'one file-backed'):read(b'12345678',[segment,segment],0x1000,4)

    def test_pin_rejection(self):
        with patch('xbl_target.Path.read_bytes',return_value=b'changed'):
            with self.assertRaisesRegex(ValueError,'pinned'):inventory()


if __name__=='__main__':unittest.main()
