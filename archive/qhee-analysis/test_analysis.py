#!/usr/bin/env python3
"""Regression checks for firmware analysis coverage and copy-only patching."""
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from analyze import scan
from qhee import QheeImage, DEFAULT_IMAGE
from run_qemu import classify_output, decode_stop


def synthetic_elf(code):
    data = bytearray(0x100) + code
    data[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', data, 18, 183)
    struct.pack_into('<QQ', data, 24, 0x80000000, 64)
    struct.pack_into('<HH', data, 54, 56, 1)
    struct.pack_into('<IIQQQQQQ', data, 64, 1, 7, 0x100, 0x80000000,
                     0x80000000, len(code), len(code) + 16, 0x1000)
    return data


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'input.elf'

    def image(self, data):
        self.path.write_bytes(data)
        return QheeImage(self.path)

    def test_scan_continues_after_embedded_invalid_word(self):
        code = bytes.fromhex('1f2003d5 ffffffff e0039fd6')
        q = self.image(synthetic_elf(code))
        insns, _, erets, _, _ = scan(q)
        self.assertEqual(sum(i.size for i in insns), len(code))
        self.assertEqual(erets, [0x80000008])
        self.assertEqual(insns[1].id, 0)

    def test_bss_read_zero_fills_and_rejects_cross_segment(self):
        q = self.image(synthetic_elf(b'abcd'))
        self.assertEqual(q.read(0x80000002, 6), b'cd\0\0\0\0')
        with self.assertRaises(ValueError): q.read(0x80000013, 2)
        with self.assertRaises(ValueError): q.read(0x80000000, -1)

    def test_rejects_truncated_and_wrong_architecture(self):
        good = synthetic_elf(b'abcd')
        bad_arch = good.copy()
        struct.pack_into('<H', bad_arch, 18, 62)
        for data in [good[:10], good[:90], good[:-1], bad_arch]:
            with self.subTest(length=len(data)):
                with self.assertRaises(ValueError): self.image(data)

    def test_rejects_load_filesz_larger_than_memsz(self):
        bad = synthetic_elf(b'abcd')
        struct.pack_into('<Q', bad, 64 + 40, 1)
        with self.assertRaises(ValueError): self.image(bad)

    def test_el3_stop_is_not_success_even_when_qemu_exits_zero(self):
        self.assertEqual(classify_output(b'EL3_STOP ESR ELR:\n', 0, 'exited'),
                         'blocked_at_unmodeled_el3_exception')
        self.assertEqual(classify_output(b'', None, 'timeout'), 'timeout_without_handoff')
        self.assertEqual(classify_output(b'EL1\n', 0, 'exited'), 'synthetic_probe_reached')

    def test_semihosting_probe_after_model_messages_requires_clean_exit(self):
        preface=b'MODEL_SHM_BRIDGE_CREATE_ASSUMED_SUCCESS\n'
        self.assertEqual(classify_output(preface,0,'exited',b'EL1\n'),'synthetic_probe_reached')
        self.assertEqual(classify_output(preface,0,'exited',b'EL2\n'),'synthetic_probe_reached')
        self.assertEqual(classify_output(preface,1,'exited',b'EL1\n'),'unexpected_exit')
        self.assertEqual(classify_output(preface,None,'timeout',b'EL1\n'),'timeout_without_handoff')
        self.assertEqual(classify_output(preface+b'EL3_STOP ESR ELR:\n',0,'exited',b'EL1\n'),
                         'blocked_at_unmodeled_el3_exception')

    def test_watchdog_call_is_terminal_and_retains_root_cause(self):
        output = (b'EL3_STOP ESR ELR FAR SPSR X0 X1 X2 X3:\n'
                  b'000000005e000000\n0000000080041a50\n0000000000000000\n'
                  b'00000000800003c9\n00000000c2000108\n0000000000000001\n'
                  b'0000000000000000\n0000000000000000\n'
                  b'Faulting Address: 0x1fc8000\r\n Address of Last Instruction Executed: 0x80093da0 at EL2')
        stop = decode_stop(output)
        self.assertEqual(stop['service'], 'TZ_SECURE_WDOG_TRIGGER_ID')
        self.assertTrue(stop['terminal'])
        self.assertEqual(stop['qhee_fault'], {'address':'0x1fc8000','pc':'0x80093da0'})
        self.assertEqual(classify_output(output, 0, 'exited'), 'qhee_fatal_watchdog_request')
        # The same x0 under a data-abort syndrome is not an SMC request.
        other = output.replace(b'000000005e000000', b'0000000092000010')
        self.assertNotIn('service', decode_stop(other))
        self.assertEqual(classify_output(other, 0, 'exited'), 'blocked_at_unmodeled_el3_exception')

    @unittest.skipUnless(DEFAULT_IMAGE.exists(), 'local firmware backup unavailable')
    def test_patch_changes_only_expected_word_and_retains_input(self):
        original = DEFAULT_IMAGE.read_bytes()
        target = Path(self.tmp.name) / 'experiment.img'
        tool = Path(__file__).with_name('hyp_patch.py')
        command = [sys.executable, str(tool), '--out', str(target)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('NOT flash-ready', result.stdout)
        patched = target.read_bytes()
        self.assertEqual(len(original), len(patched))
        changed = {i for i, (a, b) in enumerate(zip(original, patched)) if a != b}
        self.assertTrue(changed)
        self.assertTrue(changed.issubset(set(range(0x31d8, 0x31dc))))
        self.assertEqual(DEFAULT_IMAGE.read_bytes(), original)
        # A second invocation must not replace an existing file.
        target.write_bytes(b'preserve me')
        result = subprocess.run(command, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), b'preserve me')
        result = subprocess.run([sys.executable, str(tool), '--out', str(DEFAULT_IMAGE)],
                                capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(DEFAULT_IMAGE.read_bytes(), original)

    @unittest.skipUnless(DEFAULT_IMAGE.exists(), 'local firmware backup unavailable')
    def test_stock_code_digest_is_embedded(self):
        q = QheeImage()
        self.assertEqual(q.data.find(hashlib.sha384(q.code_bytes()[1]).digest()), 0x1138)


if __name__ == '__main__':
    unittest.main()
