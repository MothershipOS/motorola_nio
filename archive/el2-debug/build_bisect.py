#!/usr/bin/env python3
"""Build flash-ready single-change hyp bisect variants (SPSR-only, teardown-only, combined).

Each variant edits the stock QHEE code and repairs the executable SHA-384 at 0x1138 so the
image is integrity-consistent. The OEM signature is left stale — harmless here because this
device does not verify it (kernel/EL2-hypb-nonboot-cause.md). Writes outside backups only.

The patch byte-ranges are taken from the known combined candidate so variants are exact
subsets of it. `--check` rebuilds 'combined' and asserts it reproduces that candidate.
"""
import sys, struct, hashlib, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/hyp_re'))
from qhee import QheeImage  # noqa

ROOT = Path(__file__).resolve().parents[1]
STOCK = ROOT/'backups/nio-firmware-20260927T163534Z/hyp_b.img'
COMBINED = ROOT/'reports/nio-el2-firmware-20261006/hyp_b-after.img'
HASH_OFFSET = 0x1138
# file ranges (from build_firmware_candidate.py / the combined diff)
SPSR = (0x31d8, 0x31dc)      # movz x5 EL1h->EL2h
TEARDOWN = (0x32b0, 0x3325)  # masked cache/MMU teardown + original ERET
COMBINED_SHA = 'fbdc0fbf190e605d2d8e89cea53d1ac29d7c99c4de7f25c2458f21aed1ea43ec'

def build(which):
    img = QheeImage(STOCK); seg = img.code
    data = bytearray(img.data)
    comb = COMBINED.read_bytes()
    if which in ('spsr','combined'):
        a,b = SPSR; data[a:b] = comb[a:b]
    if which in ('teardown','combined'):
        a,b = TEARDOWN; data[a:b] = comb[a:b]
    code = bytes(data[seg.file_off:seg.file_off+seg.filesz])
    data[HASH_OFFSET:HASH_OFFSET+48] = hashlib.sha384(code).digest()
    return bytes(data)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--which', choices=['spsr','teardown','combined'])
    ap.add_argument('--out')
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    if a.check:
        got = hashlib.sha256(build('combined')).hexdigest()
        ok = got == COMBINED_SHA
        print(f"rebuilt combined sha256 = {got}\nexpected               = {COMBINED_SHA}\n{'MATCH - method validated' if ok else 'MISMATCH - do not trust variants'}")
        sys.exit(0 if ok else 2)
    data = build(a.which)
    out = Path(a.out)
    if out.exists() or 'backups' in out.resolve().parts: raise SystemExit('bad output path')
    out.write_bytes(data)
    print(f"{a.which}: wrote {out} ({len(data)} bytes) sha256={hashlib.sha256(data).hexdigest()}")

if __name__=='__main__': main()
