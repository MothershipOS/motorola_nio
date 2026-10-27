#!/usr/bin/env python3
"""Pinned boot image inventory and malformed-container rejection."""
import hashlib
import lzma
from pathlib import Path
import struct
import unittest
import uuid
from bootchain import analyze, image_info, loads, sections, volume, LZMA_GUID
from qhee import ROOT


class BootchainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report=analyze(ROOT/'kernel-work/out/bootchain-tests')
        cls.xbl=cls.report['images']['xbl_a.img'][0];cls.abl=cls.report['images']['abl_a.img'][0]
        cls.te=Path(cls.xbl['extracted_path']).read_bytes();cls.pe=Path(cls.abl['extracted_path']).read_bytes()

    def test_xbl_sec_entry(self):
        self.assertEqual(self.xbl['machine'],'0xaa64');self.assertEqual(self.xbl['format'],'TE')
        self.assertEqual(self.xbl['physical_entry'],'0x9fc0cc50')
        self.assertEqual(self.report['files']['xbl_a.img']['fv_entry_branch'],self.xbl['physical_entry'])
        self.assertEqual(self.xbl['sha256'],hashlib.sha256(self.te).hexdigest())

    def test_abl_compressed_aarch64(self):
        self.assertEqual(self.abl['names'],['MotoBootModule']);self.assertEqual(self.abl['machine'],'0xaa64')
        self.assertEqual(self.abl['format'],'PE32+');self.assertIsNone(self.abl['physical_entry'])
        self.assertEqual(self.abl['sha256'],hashlib.sha256(self.pe).hexdigest())

    def test_candidates_bounded(self):
        for image in (self.xbl,self.abl):
            self.assertTrue(image['transition_instruction_candidates'])
            for c in image['transition_instruction_candidates']:
                off=int(c['file_offset'],16)
                self.assertTrue(any(a<=off and off+4<=a+n for a,n,va in image['executable_ranges']))
        self.assertIn('not a CFG proof',self.report['scope'])

    def test_sec_el2_startup_instructions(self):
        windows=self.xbl['sec_instruction_windows']
        instructions={i['address']:(i['mnemonic'],i['operands']) for w in windows.values() for i in w['instructions']}
        self.assertEqual(instructions['0x9fc0cc50'],('cmp','x0, #0'))
        self.assertEqual(instructions['0x9fc0cda0'],('mrs','x0, currentel'))
        self.assertEqual(instructions['0x9fc0cea4'],('movz','x0, #0x10'))
        self.assertEqual(instructions['0x9fc0cea8'],('bl','#0x9fc182f4'))
        self.assertEqual(instructions['0x9fc182f4'],('msr','hcr_el2, x0'))
        self.assertEqual(instructions['0x9fc17f20'],('msr','sctlr_el2, x0'))
        for w in windows.values():self.assertEqual(w['sha256'],hashlib.sha256(Path(w['path']).read_bytes()).hexdigest())

    def test_elf_truncated(self):
        with self.assertRaises(ValueError):loads(b'\x7fELF')

    def test_elf_program_bounds(self):
        data=bytearray(64);data[:6]=b'\x7fELF\x02\x01';struct.pack_into('<Q',data,32,64)
        struct.pack_into('<HH',data,54,56,1)
        with self.assertRaisesRegex(ValueError,'program-header'):loads(data)

    def test_fv_checksum(self):
        data=bytearray(64);data[40:44]=b'_FVH';struct.pack_into('<Q',data,32,64);struct.pack_into('<H',data,48,56)
        with self.assertRaisesRegex(ValueError,'checksum'):volume(data)

    def test_fv_bounds(self):
        data=bytearray(64);data[40:44]=b'_FVH';struct.pack_into('<Q',data,32,128);struct.pack_into('<H',data,48,56)
        with self.assertRaisesRegex(ValueError,'bounds'):volume(data)

    def test_section_bounds(self):
        for data in (b'\x03\0\0\x10',b'\x08\0\0\x10',b'\xff\xff\xff\x10'):
            with self.subTest(data=data),self.assertRaisesRegex(ValueError,'bounds'):sections(data,None)

    def test_section_recursion(self):
        with self.assertRaisesRegex(ValueError,'recursion'):sections(b'',None,9)

    def test_guided_offset(self):
        data=bytearray(28);data[:4]=b'\x1c\0\0\x02';data[4:20]=uuid.UUID(LZMA_GUID).bytes_le
        struct.pack_into('<HH',data,20,4,1)
        with self.assertRaisesRegex(ValueError,'offset'):sections(bytes(data),None)

    def test_truncated_lzma(self):
        payload=lzma.compress(b'\x08\0\0\x12test',format=lzma.FORMAT_ALONE)[:-2]
        data=(24+len(payload)).to_bytes(3,'little')+b'\x02'+uuid.UUID(LZMA_GUID).bytes_le+struct.pack('<HH',24,1)+payload
        with self.assertRaisesRegex(ValueError,'truncated'):sections(data,None)

    def test_te_entry_and_sections(self):
        for offset,value in ((8,0xffffffff),(4,255)):
            data=bytearray(self.te)
            if offset==8:struct.pack_into('<I',data,offset,value)
            else:data[offset]=value
            with self.subTest(offset=offset),self.assertRaises(ValueError):image_info({'kind':0x12,'address':None,'data':data})
        data=bytearray(self.te);struct.pack_into('<I',data,40+20,0xffffffff)
        with self.assertRaisesRegex(ValueError,'section bounds'):image_info({'kind':0x12,'address':None,'data':data})

    def test_pe_entry_bounds(self):
        data=bytearray(self.pe);pe=struct.unpack_from('<I',data,60)[0];struct.pack_into('<I',data,pe+24+16,0xffffffff)
        with self.assertRaisesRegex(ValueError,'entry outside'):image_info({'kind':0x10,'address':None,'data':data})

    def test_pe_signature(self):
        data=bytearray(self.pe);struct.pack_into('<I',data,60,len(data))
        with self.assertRaisesRegex(ValueError,'signature'):image_info({'kind':0x10,'address':None,'data':data})


if __name__=='__main__':unittest.main()
