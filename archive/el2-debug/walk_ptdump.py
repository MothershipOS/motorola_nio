#!/usr/bin/env python3
"""Walk the EL2 page-table dump captured by `build_uart_marker.py --mode ptdump`.

Input: el2-debug/uart/ptdump-20261007.txt (the `== PTDUMP ==` block). It carries
TTBR0_EL2/TCR_EL2 + the stage-1 top table (S1L1, 64 entries) and the L2 under L1[2]
(S1L2, the 2-3GB window), and the stage-2 VTTBR/VTCR + S2L1 + the S2L2 under L1[2].

4KB granule, 36-bit VA/IPA (TCR/VTCR T0SZ=0x1c): L1 index = VA[35:30] (idx into the
2-3GB window is L2 index = (VA-0x80000000)>>21). We only have the 2-3GB L2, which is
exactly where 0x80040000 (QHEE), 0x9fc00000 and 0xa16cd1dc live.
"""
import re, sys
from pathlib import Path

TXT = Path(sys.argv[1] if len(sys.argv) > 1 else "el2-debug/uart/ptdump-20261007.txt")
t = TXT.read_text()

def row(tag):
    m = re.search(rf"{tag}:(.*?)(?:\n[A-Z=]|\n== |\Z)", t, re.S)
    return [int(x, 16) for x in re.findall(r"0x[0-9a-f]+", m.group(1))] if m else []

def nz(tag):
    m = re.search(rf"{tag}@0x[0-9a-f]+:(.*?)(?:\n[A-Z=]|\n== |\Z)", t, re.S)
    out = {}
    if m:
        for idx, val in re.findall(r"(0x[0-9a-f]+)=(0x[0-9a-f]+)", m.group(1)):
            out[int(idx, 16)] = int(val, 16)
    return out

s1l1, s1l2 = row("S1L1"), nz("S1L2")
s2l1, s2l2 = row("S2L1"), nz("S2L2")

def desc(v):
    if v == 0: return "—(unmapped)"
    typ = v & 3
    oa = v & 0x0000FFFFFFFFF000
    kind = {0: "invalid", 1: "block", 2: "invalid", 3: "table/page"}[typ]
    return f"{kind} oa={oa:#x} raw={v:#018x}"

def el2_s1_lookup(va):
    l1 = (va >> 30) & 0x3f
    if l1 != 2:
        return f"L1[{l1}] (only L1[0],[2] dumped)"
    l2 = (va - 0x80000000) >> 21
    e = s1l2.get(l2, 0)
    return f"S1 L1[2]→L2[{l2:#x}] = {desc(e)}"

def s2_lookup(ipa):
    l2 = (ipa - 0x80000000) >> 21
    e = s2l2.get(l2, 0)
    return f"S2 L1[2]→L2[{l2:#x}] = {desc(e)}"

print(f"S1L1 nonzero: " + ", ".join(f"[{i}]={v:#x}" for i, v in enumerate(s1l1) if v))
print(f"S1L2 (2-3GB) mapped indices: {len(s1l2)} entries; ranges:")
# summarize contiguous mapped VA ranges in the 2-3GB L2
idxs = sorted(s1l2)
if idxs:
    start = prev = idxs[0]
    for i in idxs[1:] + [None]:
        if i != (prev + 1 if prev is not None else None):
            va0 = 0x80000000 + start*0x200000
            va1 = 0x80000000 + (prev+1)*0x200000
            print(f"    VA {va0:#x}..{va1:#x}  (L2[{start:#x}..{prev:#x}])")
            start = i
        prev = i
print()
for name, va in [("QHEE entry 0x80040000", 0x80040000),
                 ("HLOS entry  0x9fc00000", 0x9fc00000),
                 ("ABL entry   0xa16cd1dc", 0xa16cd1dc)]:
    print(f"{name}:")
    print(f"    EL2 stage-1: {el2_s1_lookup(va)}")
    print(f"    stage-2    : {s2_lookup(va)}")
print()
print("CONCLUSION: an address mapped in stage-2 (guest) but NOT in EL2 stage-1 can run")
print("at EL1 (guest) but faults if eret'd to EL2 — matches ESR_EL2=0x8600000e (S1 xlat fault).")
