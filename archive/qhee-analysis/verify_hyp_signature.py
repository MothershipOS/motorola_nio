#!/usr/bin/env python3
"""Verify the QHEE (hyp) MBN hash-table-segment OEM signature.

Qualcomm secure boot signs the hash-table segment (file 0x1000..0x1168) with an
RSA-2048 PSS/SHA-256 signature (256 bytes at 0x1168), using the embedded Motorola
leaf certificate (0x1268), chaining to the fused Root CA 716. The per-segment code
hash (SHA-384) lives *inside* that signed region at 0x1138.

Repairing the code hash after editing hyp (as build_firmware_candidate.py does)
changes the signed region but NOT the signature, so PSS verification fails: the
image is authentic-looking (hash matches code) but no longer signed. XBL rejects it.

Usage: verify_hyp_signature.py <hyp.img> [<hyp2.img> ...]
Exit 0 if all verify; non-zero if any fails.
"""
import sys, hashlib
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidSignature

SIGNED=(0x1000,0x1168); SIG=(0x1168,0x1168+256)
LEAF=(0x1268,0x1268+1238); CODE_HASH=(0x1138,0x1168)

def verify(path):
    d=open(path,'rb').read()
    cert=x509.load_der_x509_certificate(d[LEAF[0]:LEAF[1]])
    leaf=cert.subject.rfc4514_string().split(',')[0]
    try:
        cert.public_key().verify(d[SIG[0]:SIG[1]], d[SIGNED[0]:SIGNED[1]],
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.AUTO),
            hashes.SHA256())
        ok=True; why=""
    except InvalidSignature:
        ok=False; why="PSS signature does not match signed region 0x1000..0x1168"
    code_hash=d[CODE_HASH[0]:CODE_HASH[1]].hex()
    print(f"{path}")
    print(f"  leaf cert : {leaf}")
    print(f"  code SHA384 entry @0x1138 : {code_hash[:32]}...")
    print(f"  OEM signature (PSS/SHA256 over 0x1000..0x1168): {'VALID' if ok else 'INVALID'}  {why}")
    return ok

if __name__=="__main__":
    if len(sys.argv)<2: sys.exit("usage: verify_hyp_signature.py <hyp.img> ...")
    all_ok=all(verify(p) for p in sys.argv[1:])
    sys.exit(0 if all_ok else 2)
