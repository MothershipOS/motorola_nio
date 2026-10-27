#!/usr/bin/env python3
"""Decode QTI Chromatix "Parameter Parser V2.0.0" sensor-module binaries (com.qti.sensormodule.*.bin).

File layout (mothershipOS reverse engineering, nio stock vendor):
  0x00  "QTI Chromatix Header", 0x28 "Parameter Parser V2.0.0 (...)"
  0x98  u32 section-table offset, u32 section count; each section = {u64 type, u64 offset, u64 size}
        type 0: symbol table, type 1: data blob, type 2: trailer
  symbol record (0x48 bytes): {u64 index, char name[32], u64 a, u64 b, u64 data_off, u64 data_size}
        data_off/size point into the data blob; size 0 = optional field absent.
  Generated structs are arrays of u64; "...ID" fields hold the symbol index of a nested record.
  regSetting element (10 x u64): slaveAddrExists, slaveAddrID, registerAddr, registerDataCount,
        registerDataID, regAddrType(1=byte,2=word), regDataType, operation(0=write), delayUsExists, delayUsID
  resolutionData element (36 x u64): colorFilter, nStreams, streamCfgID, lineLengthPixelClock,
        frameLengthLines, minHBlank, minVBlank, outputPixelClock, hBin, vBin, frameRate(f64), laneCount, ...,
        regSettingCount @18, regSettingID @19
  streamConfiguration element (8 x u64): vc, dt, x, y, width, height, bitWidth, type(1=image,2=PDAF)
  powerSetting element (3 x u64): type(0 MCLK,1 VANA,2 VDIG,3 VIO,4 VAF,8 RESET), value, delayMs

usage: chromatix.py summary <bin>
       chromatix.py ctable <bin> <prefix> <mode#> > regs.h
"""
import struct
import sys

POWER = {0: 'MCLK', 1: 'VANA', 2: 'VDIG', 3: 'VIO', 4: 'VAF', 8: 'RESET', 9: 'STANDBY'}
DT = {0x2a: 'RAW8', 0x2b: 'RAW10', 0x2c: 'RAW12', 0x30: 'PD/user'}


class Module:
    def __init__(self, path):
        self.d = d = open(path, 'rb').read()
        assert d.startswith(b'QTI Chromatix Header'), 'not a chromatix bin'
        tab, n = struct.unpack_from('<II', d, 0x98)
        self.secs = [struct.unpack_from('<QQQ', d, tab + i * 24) for i in range(n)]
        _, off, size = self.secs[0]
        self.recs = {}
        self.order = []
        for p in range(off, off + size - 0x47, 0x48):
            idx, = struct.unpack_from('<Q', d, p)
            name = d[p + 8:p + 0x28].split(b'\0')[0].decode(errors='replace')
            a, b, doff, dsz = struct.unpack_from('<QQQQ', d, p + 0x28)
            self.recs[idx] = (idx, name, a, b, doff, dsz)
            self.order.append(idx)

    def q(self, off, n):
        return list(struct.unpack_from('<%dQ' % n, self.d, self.secs[1][1] + off))

    def raw(self, rec):
        _, _, _, _, off, size = rec
        b = self.secs[1][1] + off
        return self.d[b:b + size]

    def find(self, name, after=0):
        for i in self.order:
            if i > after and self.recs[i][1] == name:
                return self.recs[i]
        return None

    def string(self, name, after=0):
        r = self.find(name, after)
        return self.raw(r).split(b'\0')[0].decode(errors='replace') if r and r[5] else None

    def regsetting(self, rec):
        out = []
        _, _, _, _, off, size = rec
        for e in range(off, off + size, 0x50):
            sa_ex, sa_id, addr, cnt, data_id, at, dt, op, dl_ex, dl_id = self.q(e, 10)
            dr = self.recs[data_id]
            data = self.q(dr[4], dr[5] // 8) if dr[5] else []
            delay = self.q(self.recs[dl_id][4], 1)[0] if dl_ex and self.recs[dl_id][5] else 0
            slave = self.q(self.recs[sa_id][4], 1)[0] if sa_ex and self.recs[sa_id][5] else None
            out.append((addr, data, at, dt, op, delay, slave))
        return out

    def power(self, which):
        recs = [self.recs[i] for i in self.order if self.recs[i][1] == 'powerSetting'][:2]
        v = self.q(recs[which][4], recs[which][5] // 8)
        return [(POWER.get(v[i], v[i]), v[i + 1], v[i + 2]) for i in range(0, len(v), 3)]

    def modes(self):
        r = self.find('resolutionData')
        out = []
        for m in range(r[5] // 0x120):
            v = self.q(r[4] + m * 0x120, 36)
            sc = self.recs[v[2]]
            streams = [self.q(sc[4] + j, 8) for j in range(0, sc[5], 0x40)]
            out.append(dict(cfa=v[0], llp=v[3], fll=v[4], min_hb=v[5], min_vb=v[6], opclk=v[7],
                            hbin=v[8], vbin=v[9], fps=struct.unpack('<d', struct.pack('<Q', v[10]))[0],
                            lanes=v[11], streams=streams, regs=self.recs[v[19]]))
        return out

    def named_regsetting(self, container):
        """first regSetting following a container record, e.g. initSettings"""
        c = self.find(container)
        return self.find('regSetting', c[0]) if c else None


def summary(path):
    m = Module(path)
    print(f'== {path}')
    drv = m.q(0, 24)
    print(f'sensor {m.string("sensorName")}  id reg {drv[8]:#06x} = {drv[9]:#x}')
    print(f'regs: x_out {drv[16]:#x} y_out {drv[17]:#x} VTS {drv[18]:#x} HTS {drv[19]:#x} '
          f'exposure {drv[20]:#x} gain {drv[23]:#x}')
    print('power up  ', m.power(0))
    print('power down', m.power(1))
    for i, md in enumerate(m.modes()):
        s = ', '.join(f'vc{st[0]} {DT.get(st[1], hex(st[1]))} {st[4]}x{st[5]}@({st[2]},{st[3]})'
                      f'{" PD" if st[7] == 2 else ""}' for st in md['streams'])
        print(f'mode{i}: {md["fps"]:.2f} fps, {md["lanes"]} lanes, llp {md["llp"]} fll {md["fll"]}, '
              f'bin {md["hbin"]}x{md["vbin"]}, opclk {md["opclk"]}, cfa {md["cfa"]}, '
              f'{md["regs"][5] // 0x50} regs: {s}')
    ini = m.named_regsetting('initSettings')
    print(f'init: {ini[5] // 0x50} regs' if ini else 'init: none')
    small = [r for r in (m.recs[i] for i in m.order) if r[1] == 'regSetting' and r[5] <= 0xa0]
    for r in small[:6]:
        print('  small regSetting', ' '.join(f'{a:#06x}={",".join("%02x" % x for x in dv)}'
                                             for a, dv, *_ in m.regsetting(r)))


def ctable(path, prefix, mode):
    m = Module(path)
    def emit(name, rs):
        print(f'static const struct cci_reg_sequence {prefix}_{name}[] = {{')
        for a, dv, at, dt, op, delay, slave in rs:
            assert op == 0 and len(dv) == 1 and at == 2 and dt == 1 and slave is None and not delay, (a, dv)
            print(f'\t{{ CCI_REG8({a:#06x}), {dv[0]:#04x} }},')
        print('};\n')
    print(f'/* SPDX-License-Identifier: GPL-2.0-only */\n/* Generated by tools/camera/chromatix.py from '
          f'{path.split("/")[-1]} (mode {mode}) */\n')
    emit('init_regs', m.regsetting(m.named_regsetting('initSettings')))
    emit(f'mode{mode}_regs', m.regsetting(m.modes()[mode]['regs']))


if __name__ == '__main__':
    if sys.argv[1] == 'summary':
        for p in sys.argv[2:]:
            summary(p)
    elif sys.argv[1] == 'ctable':
        ctable(sys.argv[2], sys.argv[3], int(sys.argv[4]))
