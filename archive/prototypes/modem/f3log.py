#!/usr/bin/env python3
"""Throwaway diagnostic: the SDX55's F3 messages over DIAG (/dev/wwan0qcdm0).

HDLC framing (CRC-16/X.25, 0x7d escapes, 0x7e terminator). Sends a version request, enables
extended messages at the given level mask, prints every message record's printable text.
usage: f3log.py <seconds> [mask] [ssid=mask ...]   (mask bits: 4 high, 8 error, 0x10 fatal)
"""
import os
import struct
import sys
import time

PORT = "/dev/wwan0qcdm0"


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def frame(payload):
    out = bytearray()
    for b in payload + struct.pack("<H", crc16(payload)):
        if b in (0x7E, 0x7D):
            out += bytes([0x7D, b ^ 0x20])
        else:
            out.append(b)
    out.append(0x7E)
    return bytes(out)


def packets(buf):
    *chunks, rest = buf.split(b"\x7e")
    out = []
    for c in chunks:
        p, esc = bytearray(), False
        for b in c:
            if esc:
                p.append(b ^ 0x20)
                esc = False
            elif b == 0x7D:
                esc = True
            else:
                p.append(b)
        if len(p) > 2:
            out.append(bytes(p[:-2]))
    return out, rest


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 30
    mask = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x1C
    fd = os.open(PORT, os.O_RDWR | os.O_NONBLOCK)
    os.write(fd, frame(bytes([0x00])))  # version
    os.write(fd, frame(struct.pack("<BBHI", 0x7D, 0x05, 0, mask)))  # ext msg config 5: every SSID at mask
    # then "ssid=mask" arguments, ext msg config 4: one SSID range (here one SSID) at its own mask
    for arg in sys.argv[3:]:
        ssid, m = (int(x, 0) for x in arg.split("="))
        os.write(fd, frame(struct.pack("<BBHHHI", 0x7D, 0x04, ssid, ssid, 0, m)))
    start = time.monotonic()
    buf = b""
    while time.monotonic() - start < secs:
        try:
            data = os.read(fd, 0x4000)
        except BlockingIOError:
            time.sleep(0.01)
            continue
        except OSError as e:
            print("read error: %s" % e, flush=True)
            break
        buf += data
        pkts, buf = packets(buf)
        for p in pkts:
            t = time.monotonic() - start
            if p[0] in (0x79, 0x92):
                text = bytes(c for c in p[1:] if 32 <= c < 127).decode()
                print("%6.2f F3 %s" % (t, text), flush=True)
            else:
                print("%6.2f << %02x %s" % (t, p[0], p.hex()), flush=True)


if __name__ == "__main__":
    main()
