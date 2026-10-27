#!/usr/bin/env python3
"""Independent progress reporter for dual_backup.py -> UART monitor log every 10 s.
Reads: PC stage dir, NAS manifest, phone SD log (over the telnet shell, short timeout)."""
import os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "tools")); import nsh
STAGE = "/media/buzz/36AF16E209FE6F65/nio-backup-stage"
MAN = "<backups>/mothershipOS-backups/nio-userdata-20261008/userdata.manifest"
N = 25; t0 = time.time(); last = {}
while True:
    try:
        nasd = subprocess.run(["ssh", "-o", "ConnectTimeout=5", "user@nas", f"cut -d' ' -f1 {MAN} | sort -n | tr '\\n' ' '"],
                              capture_output=True, text=True, timeout=20).stdout.split()
    except Exception: nasd = []
    st = {f: os.path.getsize(os.path.join(STAGE, f)) for f in os.listdir(STAGE) if f.endswith(".img")}
    try:
        o, _ = nsh.run("grep -c 'SD done' /tmp/bk-sd.log; for f in /mnt/sd/nio-backup/*.part; do [ -f $f ] && echo PART $(basename $f) $(stat -c %s $f); done", 8)
    except Exception: o = ""
    lines = o.splitlines(); sd_done = next((l for l in lines if l.strip().isdigit()), "?")
    sd_part = next((l for l in lines if l.startswith("PART userdata")), "")
    usb = ", ".join(f"{f.split('.')[1]}:{s/2**30:.1f}G" for f, s in sorted(st.items()))
    sdp = (f"{sd_part.split()[1].split('.')[1]}:{int(sd_part.split()[2])/2**30:.1f}G") if sd_part else "-"
    nsh.gui(f"BACKUP STATUS: NAS verified {len(nasd)}/{N} [{' '.join(nasd)}] | card done {sd_done}/11, writing {sdp} "
            f"| PC staging {usb or '-'} | {(time.time()-t0)/60:.0f} min")
    if len(nasd) >= N: break
    time.sleep(10)
