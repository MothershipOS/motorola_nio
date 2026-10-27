#!/usr/bin/env python3
"""Integrity, containment and pinned-input guards for the physical candidate."""
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from build_firmware_candidate import candidate, EXPERIMENT
from handoff import loaded_code
from qhee import QheeImage
from transition import START, END


class CandidateTests(unittest.TestCase):
    def test_container_and_every_changed_byte(self):
        image = QheeImage()
        data, metadata = candidate(image)
        code, _ = loaded_code(image, EXPERIMENT)
        self.assertEqual(len(data), 0x800000)
        self.assertEqual(data[0x3000:0x6db88], code)
        self.assertEqual(data[0x1138:0x1168], hashlib.sha384(code).digest())
        # Independent full-image reconstruction defines all permitted edits.
        expected = bytearray(image.data)
        struct.pack_into('<I', expected, 0x31d8, 0xd2807925)
        expected[0x32b0:0x332c] = code[START-0x80040000:END-0x80040000]
        expected[0x1138:0x1168] = hashlib.sha384(expected[0x3000:0x6db88]).digest()
        self.assertEqual(data, expected)
        self.assertEqual(data[:0x1138], image.data[:0x1138])
        self.assertEqual(data[0x1168:0x3000], image.data[0x1168:0x3000])
        self.assertFalse(metadata['hardware_boot_validated'])
        self.assertIn('STALE', metadata['oem_signature'])
        self.assertEqual(metadata['changed_bytes'], 157)

    def test_changed_input_rejected(self):
        image = QheeImage()
        image.data = image.data[:10]+bytes([image.data[10]^1])+image.data[11:]
        with self.assertRaisesRegex(ValueError, 'pinned original'):
            candidate(image)

    def test_extra_code_edit_rejected(self):
        image = QheeImage()
        code, metadata = loaded_code(image, EXPERIMENT)
        corrupted = bytearray(code); corrupted[0x2000] ^= 1
        with patch('build_firmware_candidate.loaded_code', return_value=(bytes(corrupted), metadata)):
            with self.assertRaisesRegex(ValueError, 'outside the two instruction'):
                candidate(image)

    def test_existing_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'candidate'; out.mkdir()
            sentinel = out/'hyp-el2-xbl-masked.img'; sentinel.write_bytes(b'keep')
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('build_firmware_candidate.py')),
                                     '--out', str(out)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(sentinel.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
