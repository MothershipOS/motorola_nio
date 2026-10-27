#!/usr/bin/env python3
"""Parse a Qualcomm SDI 'Raw_Dmp!' ramdump TOC and help extract/scan regions.

The full dump lives on the device 'ramdump' partition (large). Pull just the first
~64 KiB (the TOC) and small regions by the offsets this prints.

Usage:
  parse_rawdump.py toc  <head.bin>                 # list regions + dd recipes
  parse_rawdump.py scan <region.bin> [--base HEX]   # hunt AArch64 CPU context / PCs
"""
import struct, sys, re, argparse

ENTRY=0x40
def parse_toc(d):
    assert d[:8]==b"Raw_Dmp!", "not a Raw_Dmp! image"
    regions=[]
    for m in re.finditer(rb'[A-Z0-9_]{2,}\.BIN', d):
        e=m.start()-0x20
        if e<0: continue
        off,size,base=struct.unpack_from('<QQQ', d, e)
        regions.append((m.group().decode(), off, size, base))
    return regions

def cmd_toc(a):
    d=open(a.file,'rb').read()
    regs=parse_toc(d)
    print(f"{len(regs)} regions")
    print(f"{'name':14s} {'part_offset':>12s} {'size':>12s} {'phys_base':>14s}   dd (bs=1)")
    for n,off,size,base in regs:
        dd=f"dd if=/dev/block/by-name/ramdump bs=1 skip={off} count={size}" if size else "(empty)"
        print(f"{n:14s} {off:#12x} {size:#12x} {base:#14x}   {dd}")

def cmd_scan(a):
    d=open(a.file,'rb').read()
    base=int(a.base,16) if a.base else None
    # AArch64 kernel VA space (typical): 0xffffff8000000000 .. 0xffffffffffffffff
    def is_ktext(v): return 0xffffff8000000000 <= v <= 0xffffffffffffffff
    def is_el2hyp(v): return 0x80000000 <= v <= 0x90000000  # QHEE text window on this SoC
    hits=[]
    for i in range(0, len(d)-8, 8):
        v=struct.unpack_from('<Q', d, i)[0]
        if is_ktext(v) or is_el2hyp(v):
            hits.append((i,v))
    print(f"scanned {len(d)} bytes; {len(hits)} kernel/hyp-space qwords")
    # Report clusters (likely register frames: many pointers close together)
    last=-999; cluster=[]
    clusters=[]
    for i,v in hits:
        if i-last<=8*40: cluster.append((i,v))
        else:
            if len(cluster)>=4: clusters.append(cluster)
            cluster=[(i,v)]
        last=i
    if len(cluster)>=4: clusters.append(cluster)
    print(f"{len(clusters)} dense pointer clusters (candidate register frames):")
    for c in clusters[:20]:
        a0=c[0][0]
        print(f"  @+{a0:#x}  ({len(c)} ptrs)  first: "+" ".join(f"{v:#x}" for _,v in c[:6]))

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest='cmd', required=True)
    p=sub.add_parser('toc'); p.add_argument('file'); p.set_defaults(fn=cmd_toc)
    p=sub.add_parser('scan'); p.add_argument('file'); p.add_argument('--base'); p.set_defaults(fn=cmd_scan)
    a=ap.parse_args(); a.fn(a)
