#!/usr/bin/env python3
"""Copy backup chunks off an unreliable card reader, block by block, then upload them verified.

The microSD reader (Super Top SY-T18) silently returns different data on different reads of the same file,
so whole-file retries rarely succeed. Per chunk:
  1. read every 8 MiB block at least twice, dropping the page cache in between so each read really comes
     from the card; a block is accepted once two reads agree (up to MAX_READS reads),
  2. the assembled copy (on the PC disk) must equal the phone-written sha256 exactly,
  3. upload it with card_to_nas.one() (NAS stored hash + zstd round trip == phone sha256, manifest append),
  4. delete the local copy. The card is only ever read.

usage: card_salvage.py <card_dir> <stage_dir> <nas_dir> [--part userdata]
"""
import argparse
import hashlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import card_to_nas as up  # noqa: E402

BLOCK = 8 << 20
MAX_READS = 8


def read_block(fd, off, n):
    os.posix_fadvise(fd, off, n, os.POSIX_FADV_DONTNEED)	# force a real read from the card
    data = os.pread(fd, n, off)
    os.posix_fadvise(fd, off, n, os.POSIX_FADV_DONTNEED)
    return data


def salvage(src, dst, want):
    size = os.path.getsize(src)
    fd = os.open(src, os.O_RDONLY)
    h = hashlib.sha256()
    disagreements = 0
    try:
        with open(dst + ".tmp", "wb") as out:
            for off in range(0, size, BLOCK):
                n = min(BLOCK, size - off)
                seen = {}
                good = None
                for _ in range(MAX_READS):
                    d = read_block(fd, off, n)
                    k = hashlib.sha256(d).digest()
                    seen[k] = seen.get(k, 0) + 1
                    if seen[k] >= 2:
                        good = d
                        break
                if good is None:
                    raise RuntimeError(f"block at {off:#x}: no two of {MAX_READS} reads agree")
                if len(seen) > 1:
                    disagreements += 1
                out.write(good)
                h.update(good)
                if off % (512 << 20) == 0:
                    up.log(f"  {os.path.basename(src)}: {off >> 20} / {size >> 20} MiB, {disagreements} bad reads fixed")
    finally:
        os.close(fd)
    got = h.hexdigest()
    if got != want:
        os.remove(dst + ".tmp")
        return False, disagreements
    os.replace(dst + ".tmp", dst)
    with open(dst + ".sha256", "w") as f:
        f.write(want + "\n")
    return True, disagreements


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("card_dir")
    ap.add_argument("stage_dir")
    ap.add_argument("nas_dir")
    ap.add_argument("--part", default="userdata")
    a = ap.parse_args()
    os.makedirs(a.stage_dir, exist_ok=True)
    done = up.manifest(a.nas_dir, a.part)
    ok_all = True
    with tempfile.TemporaryDirectory() as tmp:
        for f in sorted(os.listdir(a.card_dir)):
            if not (f.startswith(a.part + ".") and f.endswith(".img")):
                continue
            idx = int(f.split(".")[1])
            if idx in done:
                up.log(f"chunk {idx}: already in the NAS manifest")
                continue
            want = open(os.path.join(a.card_dir, f + ".sha256")).read().split()[0]
            staged = os.path.join(a.stage_dir, f)
            for attempt in range(1, 4):
                up.log(f"chunk {idx}: copying off the card (attempt {attempt})")
                ok, fixed = salvage(os.path.join(a.card_dir, f), staged, want)
                if ok:
                    up.log(f"chunk {idx}: local copy == phone sha256 ({fixed} blocks needed extra reads)")
                    break
                up.log(f"chunk {idx}: assembled copy does not match the phone sha256 ({fixed} disagreeing blocks), again")
            else:
                up.log(f"chunk {idx}: could not get a correct copy, skipped")
                ok_all = False
                continue
            if up.one(staged, idx, a.nas_dir, a.part, tmp):
                os.remove(staged)
                os.remove(staged + ".sha256")
            else:
                ok_all = False
                up.log(f"chunk {idx}: upload failed, verified local copy kept at {staged}")
    final = up.manifest(a.nas_dir, a.part)
    missing = [i for i in range(25) if i not in final]
    up.log(f"finished; NAS manifest has {len(final)} chunks, missing: {missing or 'none'}")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
