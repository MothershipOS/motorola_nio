#!/usr/bin/env python3
"""MIPI-packed RAW10 Bayer frame -> quick-look PNG (half-res, per-channel gray-world, gamma).
usage: raw10view.py frame.raw width height stride CFA out.png   (CFA: BGGR|GBRG|GRBG|RGGB)"""
import sys
import numpy as np
from PIL import Image

def unpack(buf, w, h, stride):
    a = np.frombuffer(buf, np.uint8)[:stride * h].reshape(h, stride)[:, :w * 5 // 4]
    g = a.reshape(h, w // 4, 5).astype(np.uint16)
    px = np.empty((h, w // 4, 4), np.uint16)
    for i in range(4):
        px[..., i] = (g[..., i] << 2) | ((g[..., 4] >> (2 * i)) & 3)
    return px.reshape(h, w)

def rgb(raw, cfa):
    pos = {c: [] for c in 'RGB'}
    for i, c in enumerate(cfa):
        pos[c].append((i // 2, i % 2))
    ch = {c: np.mean([raw[y::2, x::2] for y, x in pos[c]], axis=0) for c in 'RGB'}
    img = np.stack([ch['R'], ch['G'], ch['B']], -1) - 64.0          # 10-bit black level ~64
    img = np.clip(img, 0, None)
    img /= np.maximum(img.reshape(-1, 3).mean(0), 1e-3)              # gray-world white balance
    img = np.clip(img / np.percentile(img, 99.5), 0, 1) ** (1 / 2.2)
    return (img * 255).astype(np.uint8)

if __name__ == '__main__':
    f, w, h, stride, cfa, out = sys.argv[1], *map(int, sys.argv[2:5]), sys.argv[5], sys.argv[6]
    raw = unpack(open(f, 'rb').read(), w, h, stride)
    print(f'raw min {raw.min()} max {raw.max()} mean {raw.mean():.1f}; 2x2 means',
          [round(float(raw[y::2, x::2].mean()), 1) for y in (0, 1) for x in (0, 1)])
    Image.fromarray(rgb(raw, cfa)).save(out)
