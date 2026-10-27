#!/usr/bin/env python3
"""Read rooted nio kernel evidence and optionally back up current boot partitions."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--backup-slot", choices=["a", "b"])
    args = parser.parse_args()
    adb = ["adb", "-s", args.serial]
    identity = subprocess.run(adb + ["shell", "getprop", "ro.product.device"], capture_output=True, text=True, timeout=15)
    if identity.returncode or identity.stdout.strip() != "nio":
        parser.error("target must identify as nio")
    root_check = subprocess.run(adb + ["exec-out", "su", "-c", "id"], capture_output=True, timeout=15)
    if root_check.returncode or not root_check.stdout.startswith(b"uid=0("):
        parser.error("existing root access unavailable; this tool does not install root")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "reports" / ("nio-kernel-" + stamp)
    output.mkdir(parents=True, mode=0o700)
    manifest = {"serial": args.serial, "scope": "read-only phone access", "files": {}}
    def capture(name, command, validate):
        result = subprocess.run(adb + ["exec-out", "su", "-c", command], capture_output=True, timeout=40)
        try:
            if result.returncode:
                raise ValueError("exit " + str(result.returncode))
            validate(result.stdout)
        except Exception as error:
            manifest["files"][name] = {"status": "unavailable", "error": str(error),
                "diagnostic": (result.stderr + result.stdout[:300]).decode(errors="replace")}
            print("UNAVAILABLE", name, str(error), flush=True)
            return
        path = output / name
        with path.open("xb") as stream:
            path.chmod(0o600)
            stream.write(result.stdout)
        manifest["files"][name] = {"status": "captured", "bytes": len(result.stdout),
            "sha256": hashlib.sha256(result.stdout).hexdigest()}
        print("Captured", name, len(result.stdout), flush=True)
    def config(data):
        if b"CONFIG_ARM64=y" not in gzip.decompress(data):
            raise ValueError("not an ARM64 kernel configuration")
    def fdt(data):
        if len(data) < 40 or data[:4] != bytes.fromhex("d00dfeed") or struct.unpack(">I", data[4:8])[0] != len(data):
            raise ValueError("invalid flattened device tree")
    def archive(data):
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            if not tar.getmembers(): raise ValueError("empty tree archive")
    def commandline(data):
        if b"androidboot.hardware=qcom" not in data:
            raise ValueError("unexpected boot command line")
    capture("running.config.gz", "cat /proc/config.gz", config)
    capture("live.dtb", "cat /sys/firmware/fdt", fdt)
    capture("live-tree.tar", "tar -C /sys/firmware/devicetree/base -cf - .", archive)
    capture("boot-command-line.txt", "cat /proc/cmdline", commandline)
    if args.backup_slot:
        backup = ROOT / "backups" / ("nio-current-" + stamp)
        backup.mkdir(parents=True, mode=0o700)
        manifest["backup"] = {"path": str(backup.relative_to(ROOT)),
            "scope": "Selected boot slot only; not full device backup; restore untested", "files": {}}
        for stem, expected, magic in [("boot", 100663296, b"ANDROID!"),
                ("vendor_boot", 67108864, b"VNDRBOOT"), ("dtbo", 25165824, bytes.fromhex("d7b7ab1e")),
                ("vbmeta", 65536, b"AVB0"), ("vbmeta_system", 65536, b"AVB0")]:
            name = stem + "_" + args.backup_slot
            temporary = backup / (name + ".img.partial")
            with temporary.open("xb") as stream:
                temporary.chmod(0o600)
                result = subprocess.run(adb + ["exec-out", "su", "-c", "cat /dev/block/by-name/" + name],
                                        stdout=stream, stderr=subprocess.PIPE, timeout=90)
            data = temporary.read_bytes()
            if result.returncode or len(data) != expected or not data.startswith(magic):
                raise SystemExit("Backup validation failed; retained partial file: " + str(temporary))
            path = temporary.with_suffix("")
            temporary.rename(path)
            manifest["backup"]["files"][path.name] = {"bytes":len(data), "sha256":hashlib.sha256(data).hexdigest()}
            print("Backed up", path.name, len(data), flush=True)
        (backup / "manifest.json").write_text(json.dumps(manifest["backup"], indent=2) + "\n")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Evidence:", output)


if __name__ == "__main__":
    main()
