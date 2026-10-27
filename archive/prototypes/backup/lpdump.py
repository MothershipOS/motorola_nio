#!/usr/bin/env python3
"""Minimal Android super (LP metadata v10) parser: prints logical partitions and linear extents.
usage: lpdump.py <first-1MiB-of-super> [slot]"""
import struct, sys
d = open(sys.argv[1], "rb").read(); slot = int(sys.argv[2]) if len(sys.argv) > 2 else 0
g = 4096
magic, ssize = struct.unpack_from("<II", d, g); assert magic == 0x616C4467, hex(magic)
meta_max, slots, lbs = struct.unpack_from("<III", d, g + 40)
m = 4096 + 2 * 4096 + slot * meta_max
mg, major, minor, hsize = struct.unpack_from("<IHHI", d, m); assert mg == 0x414C5030, hex(mg)
tsize, = struct.unpack_from("<I", d, m + 44)
desc = lambda o: struct.unpack_from("<III", d, m + o)
parts, exts = desc(80), desc(92)
T = m + hsize
E = [struct.unpack_from("<QIQI", d, T + exts[0] + i * exts[2]) for i in range(exts[1])]
for i in range(parts[1]):
    o = T + parts[0] + i * parts[2]
    name = d[o:o+36].split(b"\0")[0].decode(); attr, fe, ne, grp = struct.unpack_from("<IIII", d, o + 36)
    ex = [(E[j][0], E[j][2]) for j in range(fe, fe + ne)]
    size = sum(e[0] for e in ex) * 512
    print(f"{name:24s} size={size/2**20:8.1f}MiB extents=" + ",".join(f"[start_sector={s},sectors={n}]" for n, s in ex))
