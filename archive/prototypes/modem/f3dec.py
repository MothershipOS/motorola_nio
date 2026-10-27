#!/usr/bin/env python3
"""Throwaway: decode the SDX55's QShrink-4 F3 messages ("<< 99 ..." lines of f3log.py) with the modem's qdb text.
usage: f3dec.py <qdb text> <f3log output> [regex on file name or text]"""
import re
import sys

FMT = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?(?:hh|h|ll|l|z|j|t)?([diouxXcspn%])")


def load(path):
    db = {}
    for line in open(path, encoding="latin-1"):
        if line.startswith("#"):
            continue
        parts = line.rstrip("\n").split(":", 5)
        if len(parts) == 6 and parts[0].isdigit():
            db[int(parts[0])] = (parts[4], parts[3], parts[5])
    return db


def render(fmt, args):
    it = iter(args)

    def sub(m):
        if m.group(1) == "%":
            return "%"
        v = next(it, None)
        if v is None:
            return "?"
        c = m.group(1)
        if c in "xXp":
            return "%x" % v
        if c == "s":
            return "<str>"
        if c == "c":
            return chr(v & 0x7F) if 32 <= (v & 0x7F) < 127 else "?"
        if c in "di":
            bits = 8 * 4
            return str(v - (1 << bits) if v >= 1 << (bits - 1) else v)
        return str(v)

    return FMT.sub(sub, fmt)


def main():
    db = load(sys.argv[1])
    pat = re.compile(sys.argv[3], re.I) if len(sys.argv) > 3 else None
    for line in open(sys.argv[2]):
        m = re.match(r"\s*([\d.]+) << 99 ([0-9a-f]+)", line)
        if not m:
            continue
        p = bytes.fromhex(m.group(2))
        if len(p) < 18:
            continue
        n, size = p[2] >> 4, p[2] & 0xF
        h = int.from_bytes(p[12:16], "little")
        raw = p[18:]
        args = [int.from_bytes(raw[i * size:(i + 1) * size], "little") for i in range(n)] if size else []
        f, ln, fmt = db.get(h, ("?", "?", "hash %d" % h))
        text = "%s:%s %s" % (f, ln, render(fmt, args))
        if pat is None or pat.search(text):
            print("%s %s" % (m.group(1), text))


if __name__ == "__main__":
    main()
