#!/usr/bin/env python3
"""Upload backup chunks from the PC-mounted microSD card to the NAS, verified end to end.

For each <part>.NNNN.img on the card (with its phone-written .img.sha256), per attempt in ONE read:
  1. the bytes read from the card are hashed and compressed/uploaded at the same time; the attempt only
     counts if that hash equals the phone-written sum (a USB card reader returned different data on
     different reads of the same file, 2026-10-12),
  2. the NAS re-hashes the stored .part (must equal the compressed-stream hash) and the round trip
     zstd -dc | sha256sum (must equal the phone sum),
  3. rename into place and append '<idx> <raw_sha> <zst_sha> <raw_len>' to <part>.manifest.
Chunks already in the manifest are skipped. Never writes to or deletes from the card.

usage: card_to_nas.py <card_dir> <nas_dir> [--part userdata] [-j 3]
"""
import argparse
import concurrent.futures as cf
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import time

NAS = "user@nas"
SSH = ["ssh", "-o", "BatchMode=yes", "-c", "aes128-gcm@openssh.com", NAS]
lock = threading.Lock()


def log(msg):
    with lock:
        print(time.strftime("%H:%M:%S"), msg, flush=True)


def nas(cmd, **kw):
    return subprocess.run(SSH + [cmd], capture_output=True, text=True, **kw)


def manifest(nas_dir, part):
    r = nas(f"touch {shlex.quote(nas_dir)}/{part}.manifest && cat {shlex.quote(nas_dir)}/{part}.manifest")
    if r.returncode:
        sys.exit(f"cannot read NAS manifest: {r.stderr.strip()}")
    return {int(l.split()[0]) for l in r.stdout.splitlines() if len(l.split()) == 4}


def sha256_file(path):
    return subprocess.run(["sha256sum", path], capture_output=True, text=True, check=True).stdout.split()[0]


def one(path, idx, nas_dir, part, tmp, tries=6):
    """Single pass per attempt: the exact bytes read from the card are hashed AND compressed+uploaded, so an
    attempt is only accepted if that stream matches the phone-written sha256 (the card reader was seen to
    return different data on different reads). The NAS then re-checks the stored file and its round trip."""
    name = f"{part}.{idx:04d}.img.zst"
    dst = f"{nas_dir}/{name}"
    q = shlex.quote(dst + ".part")
    want = open(path + ".sha256").read().split()[0]
    raw_file = os.path.join(tmp, f"{idx}.raw")
    z_file = os.path.join(tmp, f"{idx}.zsha")
    for attempt in range(1, tries + 1):
        for f in (raw_file, z_file):
            if os.path.exists(f):
                os.remove(f)
        t0 = time.time()
        cmd = (f"set -o pipefail; cat {shlex.quote(path)} | tee >(sha256sum | cut -d' ' -f1 > {shlex.quote(raw_file)}) "
               f"| zstd -q -3 -T2 -c | tee >(sha256sum | cut -d' ' -f1 > {shlex.quote(z_file)}) "
               f"| {' '.join(SSH)} {shlex.quote('cat > ' + q)}")
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        for _ in range(20):	# the process substitutions finish just after the pipeline
            if all(os.path.exists(f) and len(open(f).read().strip()) == 64 for f in (raw_file, z_file)):
                break
            time.sleep(0.5)
        raw = open(raw_file).read().strip() if os.path.exists(raw_file) else ""
        zs = open(z_file).read().strip() if os.path.exists(z_file) else ""
        mb = os.path.getsize(path) / 1e6 / max(time.time() - t0, 1)
        if r.returncode or len(zs) != 64:
            log(f"chunk {idx} try {attempt}: upload failed: {r.stderr.strip()[-200:]}")
            continue
        if raw != want:
            log(f"chunk {idx} try {attempt}: card read was corrupt (stream sha {raw[:12]} != phone {want[:12]}), retrying")
            nas(f"rm -f {q}")
            continue
        chk = nas(f"a=$(sha256sum {q} | cut -d' ' -f1); b=$(set -o pipefail; zstd -dc {q} | sha256sum | cut -d' ' -f1) "
                  f"|| b=zstd-error; echo $a $b")
        parts = chk.stdout.split()
        if len(parts) != 2 or parts[0] != zs or parts[1] != want:
            log(f"chunk {idx} try {attempt}: NAS check failed (stored {parts[:1]} vs {zs[:12]}, "
                f"round trip {parts[1:2]} vs {want[:12]}), retrying")
            nas(f"rm -f {q}")
            continue
        line = f"{idx} {want} {zs} {os.path.getsize(path)}"
        fin = nas(f"mv {q} {shlex.quote(dst)} && echo {shlex.quote(line)} >> {shlex.quote(nas_dir)}/{part}.manifest")
        if fin.returncode == 0:
            log(f"chunk {idx}: VERIFIED (card stream = phone sha, NAS stored + round trip), {mb:.1f} MB/s, try {attempt}")
            return True
    log(f"chunk {idx}: giving up after {tries} attempts")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("card_dir")
    ap.add_argument("nas_dir")
    ap.add_argument("--part", default="userdata")
    ap.add_argument("-j", type=int, default=1)
    a = ap.parse_args()
    done = manifest(a.nas_dir, a.part)
    todo = []
    for f in sorted(os.listdir(a.card_dir)):
        if f.startswith(a.part + ".") and f.endswith(".img"):
            idx = int(f.split(".")[1])
            if idx in done:
                log(f"chunk {idx}: already in the NAS manifest")
            else:
                todo.append((os.path.join(a.card_dir, f), idx))
    log(f"{len(todo)} chunks to upload: {[i for _, i in todo]}")
    with tempfile.TemporaryDirectory() as tmp, cf.ThreadPoolExecutor(a.j) as ex:
        results = list(ex.map(lambda t: one(t[0], t[1], a.nas_dir, a.part, tmp), todo))
    final = manifest(a.nas_dir, a.part)
    missing = [i for i in range(max(final | {0}) + 1) if i not in final]
    log(f"done: {sum(results)}/{len(todo)} uploaded; manifest has {len(final)} chunks, missing: {missing or 'none'}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
