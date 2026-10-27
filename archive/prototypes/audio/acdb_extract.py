#!/usr/bin/env python3
"""Extract the nio Awinic SKT speaker-protection setup from the stock (PixelOS/Moto vendor) ACDB.

usage: acdb_extract.py <acdbdata dir> <persist aw_cali.bin or Re value> <out dir>
Writes (to /lib/firmware/qcom/sm8250/nio/ on the phone):
  nio-avcs-topologies.bin  Global_cal property 0x132ac: AVCS v2 custom topology list
                           (q6core "mothership,custom-topologies")
  nio-spk-afe-cal.bin      ACDB device 14 (speaker) @48 kHz AFE instance cal + calibrated Re
  nio-vi-afe-cal.bin       ACDB device 102 (V/I feedback) @48 kHz AFE instance cal
Cal record format (q6afe_port_set_cal): le32 module, le16 instance, le16 0, le32 param, le32 size,
data padded to 4 bytes. Topology per device (property 0x13150): speaker 0x1000FF01, feedback 0x1000FF00.
"""
import os, struct, sys

SPK, VI, RATE = 14, 102, 48000
AW_RX_MODULE, AW_PARAM_RE = 0x10013D01, 0x10013D1B


def chunks(path):
    d = open(path, 'rb').read()
    assert d[:8] == b'QCMSNDDB', path
    off, out = 0x10 + 12 + 4, {}
    while off + 12 <= len(d):
        name = d[off:off + 8].rstrip(b'\0').decode('latin1')
        ln = struct.unpack_from('<I', d, off + 8)[0]
        out.setdefault(name, d[off + 12:off + 12 + ln])
        off += 12 + ln
    return out


def blob(pool, o):
    n = struct.unpack_from('<I', pool, o)[0]
    return pool[o + 4:o + 4 + n]


def afe_instance_cal(c, dev):
    lut, cdft, cdot, pool = c['AFEILUT0'], c['AFEICDFT'], c['AFEICDOT'], c['DATAPOOL']
    for r in range(struct.unpack_from('<I', lut, 0)[0]):
        d, rate, fo, do = struct.unpack_from('<4I', lut, 4 + 16 * r)
        if (d, rate) != (dev, RATE):
            continue
        nd, no = struct.unpack_from('<I', cdft, fo)[0], struct.unpack_from('<I', cdot, do)[0]
        assert nd == no
        return [(struct.unpack_from('<3I', cdft, fo + 4 + 12 * i),
                 blob(pool, struct.unpack_from('<I', cdot, do + 4 + 4 * i)[0])) for i in range(nd)]
    raise SystemExit(f'no AFE instance cal for device {dev}')


def topology(c, dev):
    lut, pool = c['DPROPLUT'], c['DATAPOOL']
    for r in range(struct.unpack_from('<I', lut, 0)[0]):
        d, prop, o = struct.unpack_from('<3I', lut, 4 + 12 * r)
        if d == dev and prop == 0x13150:
            return struct.unpack_from('<I', blob(pool, o))[0]


def record(module, instance, param, data):
    return struct.pack('<IHHII', module, instance, 0, param, len(data)) + data + b'\0' * (-len(data) % 4)


def main():
    src, cali, out = sys.argv[1:4]
    re_q12 = int(open(cali).read().strip()) if os.path.exists(cali) else int(cali)
    assert 4 * 4096 < re_q12 < 16 * 4096, f'implausible Re {re_q12}'
    g, spk = chunks(os.path.join(src, 'Global_cal.acdb')), chunks(os.path.join(src, 'Speaker_cal.acdb'))
    glut, gpool = g['GPROPLUT'], g['DATAPOOL']
    topo = None
    for r in range((len(glut) - 4) // 8):
        prop, o = struct.unpack_from('<2I', glut, 4 + 8 * r)
        if prop == 0x132ac:
            topo = blob(gpool, o)
    assert topo and topo.find(struct.pack('<I', 0x1000FF01)) > 0
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, 'nio-avcs-topologies.bin'), 'wb').write(topo)
    for dev, name, extra in ((SPK, 'nio-spk-afe-cal.bin', record(AW_RX_MODULE, 0, AW_PARAM_RE, struct.pack('<i', re_q12))),
                             (VI, 'nio-vi-afe-cal.bin', b'')):
        recs = b''.join(record(m, i, p, d) for (m, i, p), d in afe_instance_cal(spk, dev)) + extra
        open(os.path.join(out, name), 'wb').write(recs)
        print(f'{name}: device {dev} topology {topology(spk, dev):#x}, {len(recs)} bytes')
    print(f'nio-avcs-topologies.bin: {struct.unpack_from("<I", topo)[0]} topologies, {len(topo)} bytes; Re {re_q12} ({re_q12 / 4096:.2f} ohm)')


main()
