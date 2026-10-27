#!/usr/bin/env python3
"""Pinned ABL PE-loader guards and isolated EL1/EL2 launch-boundary execution."""
import hashlib
import json
from pathlib import Path
import struct
import unittest
from abl_contract import inventory, map_pe, BASE
from qhee import ROOT
from run_abl_boundary import run


class AblBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data,cls.mapped,cls.contract=inventory()
        cls.pe=struct.unpack_from('<I',cls.data,60)[0];cls.opt=cls.pe+24
        cls.out=ROOT/'kernel-work/out/abl-boundary-tests';cls.out.mkdir(exist_ok=True)

    def test_original_launch_instructions(self):
        instructions=self.contract['windows']['aarch64-launch']['instructions']
        self.assertEqual([(i['mnemonic'],i['operands']) for i in instructions],[
            ('ldur','x8, [x23, #-0x70]'),('mov','x1, xzr'),('ldur','x0, [x23, #-0x58]'),
            ('mov','x2, xzr'),('mov','x3, xzr'),('blr','x8')])
        for window in self.contract['windows'].values():
            at=int(window['rva'],16);n=window['size']
            self.assertEqual(self.mapped[at:at+n],self.data[at:at+n])

    def test_pe_relocation_values(self):
        mapping=self.contract['mapping'];self.assertEqual(mapping['relocations'],1242)
        self.assertEqual(len(self.mapped),958464);self.assertEqual(mapping['mapped_sha256'],hashlib.sha256(self.mapped).hexdigest())
        for target in (mapping['relocation_targets'][0],mapping['relocation_targets'][-1]):
            at=int(target,16)
            self.assertEqual(struct.unpack_from('<Q',self.mapped,at)[0],struct.unpack_from('<Q',self.data,at)[0]+BASE)

    def test_mapping_base_and_size(self):
        for base in (-4096,BASE+1,1<<64):
            with self.subTest(base=base),self.assertRaisesRegex(ValueError,'base/size'):map_pe(self.data,base)
        d=bytearray(self.data);struct.pack_into('<I',d,self.opt+56,32*1024*1024)
        with self.assertRaisesRegex(ValueError,'base/size'):map_pe(d)

    def test_overlap_rejected(self):
        d=bytearray(self.data);opt_size=struct.unpack_from('<H',d,self.pe+20)[0]
        section=self.opt+opt_size+40
        struct.pack_into('<I',d,section+12,0x1000)
        with self.assertRaisesRegex(ValueError,'overlapping'):map_pe(d)

    def test_unsupported_relocation(self):
        d=bytearray(self.data);rva=struct.unpack_from('<I',d,self.opt+112+5*8)[0]
        at=rva+8;word=struct.unpack_from('<H',d,at)[0]
        struct.pack_into('<H',d,at,(word&4095)|0x3000)
        with self.assertRaisesRegex(ValueError,'type'):map_pe(d)

    def test_relocation_bounds(self):
        rva=struct.unpack_from('<I',self.data,self.opt+112+5*8)[0]
        for offset,value,error in ((4,4,'block bounds'),(0,0xffffffff,'target')):
            d=bytearray(self.data);struct.pack_into('<I',d,rva+offset,value)
            with self.subTest(offset=offset),self.assertRaisesRegex(ValueError,error):map_pe(d)

    def test_invalid_entry_state(self):
        for el,mmu,daif in ((0,'on','masked'),(2,'unknown','masked'),(2,'on','unknown')):
            with self.subTest(el=el,mmu=mmu,daif=daif),self.assertRaisesRegex(ValueError,'entry state'):
                run(self.out/'invalid',el,mmu,initial_daif=daif)

    def test_original_boundary_all_states(self):
        results=[]
        for el in (1,2):
            for mmu in ('off','on'):
                for daif in ('masked','unmasked'):
                    with self.subTest(el=el,mmu=mmu,daif=daif):
                        d=self.out/f'el{el}-{mmu}-{daif}';m=run(d,el,mmu,initial_daif=daif)
                        c=m['trace']['checkpoints'];self.assertEqual(len(c),5)
                        before,after=c[1]['registers'],c[2]['registers'];key=f'SCTLR_EL{el}'
                        self.assertEqual(int(before[key],16)&0x1005,0x1005 if mmu=='on' else 0)
                        self.assertEqual(int(after[key],16),int(before[key],16)&~0x1005)
                        self.assertEqual(after['sp'],before['sp']);self.assertEqual(after['HCR_EL2'],before['HCR_EL2'])
                        self.assertEqual(after['x0'],'0x0')
                        for point in c:
                            self.assertEqual(int(point['registers']['cpsr'],16)&15,9 if el==2 else 5)
                        self.assertEqual(int(after['cpsr'],16)&0x3c0,0x3c0 if daif=='masked' else 0x1c0)
                        call=c[3]['registers'];probe=c[4]['registers']
                        self.assertEqual(call['pc'],'0x90061db4');self.assertEqual(call['x0'],'0x93000000')
                        self.assertEqual([call['x'+str(i)] for i in range(1,4)],['0x0']*3)
                        self.assertEqual(probe['pc'],call['x8']);self.assertEqual(probe['x0'],'0x93000000')
                        self.assertEqual([probe['x'+str(i)] for i in range(1,4)],['0x0']*3)
                        self.assertEqual(int(m['trace']['after_probe_first_step']['pc'],16),int(probe['pc'],16)+4)
                        self.assertEqual(m['stderr'],f'EL{el}\n');self.assertEqual(m['exit'],0)
                        results.append({'el':el,'mmu':mmu,'daif':daif,'passed':True,'manifest':str(d/'manifest.json')})
        (self.out/'results.json').write_text(json.dumps({'results':results},indent=2)+'\n')


if __name__=='__main__':unittest.main()
