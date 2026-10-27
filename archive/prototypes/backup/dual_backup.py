#!/usr/bin/env python3
"""Back up a raw nio partition in 4 GiB chunks over two paths at once:
  SD worker  (runs ON the phone): lowest unclaimed chunks -> microSD card folder, sha256 alongside
  USB worker (driven from here):  highest unclaimed chunks -> PC staging dir over USB-NCM
Chunks are claimed atomically on the phone (mkdir /tmp/bk-claims/N), so the two never overlap.
A separate uploader sends PC-staged chunks to the NAS (zstd), verifies sha256 there, deletes local.
State: NAS_DIR/PART.manifest lists chunks verified on the NAS ("idx raw_sha256 zst_sha256 len").
Progress goes to the UART monitor log via nsh.gui. Re-running resumes.

usage: dual_backup.py run   PART NAS_DIR --stage DIR [--sd-max N]
       dual_backup.py ingest PART NAS_DIR --from DIR      # card mounted on the PC: upload its chunks"""
import argparse, hashlib, os, queue, shlex, subprocess, sys, threading, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "tools")); import nsh  # noqa: E402

CHUNK = 4 << 30; BS = 4 << 20; BLOCKS = CHUNK // BS
NAS = "user@nas"; q = shlex.quote

def sh(c): return subprocess.run(c, shell=True, executable="/bin/bash", capture_output=True, text=True)
def nas(c): return sh(f"ssh {NAS} {q(c)}")
def manifest(nas_dir, part):
    r = nas(f"mkdir -p {q(nas_dir)} && touch {q(nas_dir + '/' + part + '.manifest')} && cat {q(nas_dir + '/' + part + '.manifest')}")
    return {int(l.split()[0]): l.split() for l in r.stdout.splitlines() if len(l.split()) == 4}

def upload(path, idx, raw_sha, ln, nas_dir, part):
    """zstd a local raw chunk to the NAS, verify, append manifest. True on success."""
    name = f"{part}.{idx:04d}.img.zst"; dst = f"{nas_dir}/{name}"
    for _ in range(3):
        r = sh(f"set -o pipefail; zstd -q -3 -T0 -c {q(path)} | tee >(sha256sum | cut -d' ' -f1 > {q(path + '.zsha')}) "
               f"| ssh {NAS} {q('cat > ' + q(dst + '.part'))}")
        time.sleep(0.5)
        try: zs = open(path + ".zsha").read().strip()
        except OSError: zs = ""
        if r.returncode or len(zs) != 64: continue
        rem = nas(f"sha256sum {q(dst + '.part')} | cut -d' ' -f1").stdout.strip()
        if rem == zs and nas(f"mv {q(dst + '.part')} {q(dst)} && echo '{idx} {raw_sha} {zs} {ln}' >> {q(nas_dir + '/' + part + '.manifest')}").returncode == 0:
            os.remove(path + ".zsha"); return True
    return False

def run(a):
    out, _ = nsh.run(f"for d in /sys/class/block/*; do grep -q '^PARTNAME={a.part}$' $d/uevent && basename $d; done", 20)
    dev = out.strip().splitlines()[-1].strip()
    size = int(nsh.run(f"echo $(( $(cat /sys/class/block/{dev}/size) * 512 ))", 10)[0].strip().splitlines()[-1])
    n = (size + CHUNK - 1) // CHUNK
    done = manifest(a.nas_dir, a.part)
    os.makedirs(a.stage, exist_ok=True)
    # claims: everything already on the NAS, plus anything already sitting on the card
    pre = " ".join(str(i) for i in done)
    nsh.run(f"mkdir -p /tmp/bk-claims /mnt/sd; grep -q ' /mnt/sd ' /proc/mounts || mount /dev/mmcblk0p1 /mnt/sd; "
            f"mkdir -p /mnt/sd/nio-backup; for i in {pre}; do mkdir -p /tmp/bk-claims/$i; done; "
            f"for f in /mnt/sd/nio-backup/{a.part}.*.img.sha256; do [ -f \"$f\" ] || continue; "
            f"i=$(echo $f | sed 's/.*\\.\\([0-9][0-9][0-9][0-9]\\)\\.img\\.sha256$/\\1/'); mkdir -p /tmp/bk-claims/$(expr $i + 0); done; true", 30)
    nsh.gui(f"DUAL BACKUP {a.part}=/dev/{dev} {size/2**30:.2f} GiB = {n} x 4 GiB; {len(done)} already on NAS; "
            f"SD takes low chunks (max {a.sd_max}), USB takes high chunks")
    # ---- SD worker: a shell loop on the phone, detached; logs to /tmp/bk-sd.log ----
    sd = f"""cat > /tmp/bk-sd.sh <<'EOF'
n={n}; c=0
for i in $(seq 0 $((n-1))); do
  [ $c -ge {a.sd_max} ] && break
  mkdir /tmp/bk-claims/$i 2>/dev/null || continue
  f=/mnt/sd/nio-backup/{a.part}.$(printf %04d $i).img
  echo "SD start chunk $i" >> /tmp/bk-sd.log
  if dd if=/dev/{dev} bs=4M skip=$((i*{BLOCKS})) count={BLOCKS} 2>/dev/null | tee $f.part | sha256sum | cut -d' ' -f1 > $f.sha256.part && sync && mv $f.part $f && mv $f.sha256.part $f.sha256; then
    echo "SD done chunk $i $(cat $f.sha256) $(stat -c %s $f)" >> /tmp/bk-sd.log; c=$((c+1))
  else
    echo "SD FAIL chunk $i" >> /tmp/bk-sd.log; rm -f $f.part $f.sha256.part; rmdir /tmp/bk-claims/$i; break
  fi
done
echo "SD worker finished ($c chunks)" >> /tmp/bk-sd.log
EOF
: > /tmp/bk-sd.log; setsid sh /tmp/bk-sd.sh </dev/null >/dev/null 2>&1 &"""
    nsh.run(sd, 20)
    stop = threading.Event(); upq = queue.Queue(); stats = {"usb": 0, "usb_bytes": 0, "nas": 0}; t0 = time.time()

    def usb_worker():
        for i in range(n - 1, -1, -1):
            if stop.is_set(): return
            o, _ = nsh.run(f"mkdir /tmp/bk-claims/{i} 2>/dev/null && echo CLAIMED", 10)
            if "CLAIMED" not in o: continue
            expect = min(CHUNK, size - i * CHUNK); path = f"{a.stage}/{a.part}.{i:04d}.img"; port = 9600 + i
            ok = False
            for attempt in range(3):
                p = subprocess.Popen(f"nc -d -l 10.42.0.1 {port} | tee {q(path)} | sha256sum | cut -d' ' -f1 > {q(path + '.sha256')}",
                                     shell=True, executable="/bin/bash")
                time.sleep(0.5)
                nsh.run(f"dd if=/dev/{dev} bs=4M skip={i * BLOCKS} count={BLOCKS} 2>/dev/null | nc 10.42.0.1 {port}", 3600)
                p.wait(); time.sleep(0.3)
                try: rs = open(path + ".sha256").read().strip(); ln = os.path.getsize(path)
                except OSError: rs, ln = "", -1
                if ln == expect and len(rs) == 64: ok = True; break
                nsh.gui(f"DUAL BACKUP: USB chunk {i} short ({ln}/{expect}), retry {attempt + 1}")
            if not ok:
                nsh.run(f"rmdir /tmp/bk-claims/{i}", 10); continue
            stats["usb"] += 1; stats["usb_bytes"] += ln; upq.put((path, i, rs, ln))

    def uploader():
        while True:
            it = upq.get()
            if it is None: return
            path, i, rs, ln = it
            if upload(path, i, rs, ln, a.nas_dir, a.part):
                stats["nas"] += 1; os.remove(path); os.remove(path + ".sha256")
            else:
                nsh.gui(f"DUAL BACKUP: chunk {i} NAS upload/verify FAILED, kept at {path}")

    up = threading.Thread(target=uploader); up.start()
    uw = threading.Thread(target=usb_worker); uw.start()
    seen = 0
    while uw.is_alive() or not upq.empty():
        time.sleep(10)
        log, _ = nsh.run("cat /tmp/bk-sd.log; ls /tmp/bk-claims | wc -l; df -m /mnt/sd | tail -1", 15)
        lines = [l for l in log.splitlines() if l.startswith("SD ")]
        for l in lines[seen:]: nsh.gui("DUAL BACKUP: " + l)
        seen = len(lines)
        sd_done = sum(1 for l in lines if l.startswith("SD done"))
        el = time.time() - t0
        nsh.gui(f"DUAL BACKUP: SD {sd_done} chunks | USB {stats['usb']} chunks ({stats['usb_bytes']/max(el,1)/1e6:.1f} MB/s) "
                f"| NAS verified {stats['nas']} | {(time.time()-t0)/60:.1f} min elapsed")
    upq.put(None); up.join()
    log, _ = nsh.run("cat /tmp/bk-sd.log", 15)
    nsh.gui(f"DUAL BACKUP: phone side complete. USB->NAS verified {stats['nas']}; card holds: "
            + ", ".join(l.split()[3] for l in log.splitlines() if l.startswith("SD done")))

def ingest(a):
    """Card chunks (mounted on the PC at --from) -> NAS, after checking each against its phone-written sha256."""
    done = manifest(a.nas_dir, a.part)
    files = sorted(f for f in os.listdir(a.src) if f.startswith(a.part + ".") and f.endswith(".img"))
    for f in files:
        i = int(f.split(".")[1]); path = os.path.join(a.src, f)
        if i in done: nsh.gui(f"INGEST: chunk {i} already on NAS"); continue
        want = open(path + ".sha256").read().strip()
        got = sh(f"sha256sum {q(path)} | cut -d' ' -f1").stdout.strip()
        if got != want: nsh.gui(f"INGEST: chunk {i} on card DOES NOT match phone sha256 -- skipped"); continue
        ok = upload(path, i, want, os.path.getsize(path), a.nas_dir, a.part)
        nsh.gui(f"INGEST: chunk {i} -> NAS {'VERIFIED' if ok else 'FAILED'}")
        if ok and a.delete: os.remove(path); os.remove(path + ".sha256")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("mode", choices=["run", "ingest"])
    ap.add_argument("part"); ap.add_argument("nas_dir")
    ap.add_argument("--stage", default="/media/buzz/36AF16E209FE6F65/nio-backup-stage")
    ap.add_argument("--sd-max", type=int, default=11)
    ap.add_argument("--from", dest="src"); ap.add_argument("--delete", action="store_true")
    a = ap.parse_args()
    run(a) if a.mode == "run" else ingest(a)
