#!/usr/bin/env python3
"""Collect a bounded, read-only nio diagnostic report without rebooting or rooting."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess


def run(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        return {"argv": argv, "returncode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired:
        return {"argv": argv, "returncode": None, "error": "timed out after 20s"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "reports")
    args = parser.parse_args()
    adb = shutil.which("adb")
    if not adb:
        parser.error("adb is not installed or not on PATH")
    prefix = [adb, "-s", args.serial]
    identity = run(prefix + ["shell", "getprop", "ro.product.device"])
    if identity.get("returncode") != 0 or identity.get("stdout", "").strip() != "nio":
        raise SystemExit("Target is not a confirmed nio: " + json.dumps(identity))
    checks = {"device": identity}
    properties = ["ro.product.model", "ro.build.version.release", "ro.build.version.sdk",
                  "ro.build.fingerprint", "ro.bootimage.build.fingerprint",
                  "ro.lineage.version", "ro.boot.flash.locked", "ro.boot.vbmeta.device_state",
                  "ro.boot.verifiedbootstate", "ro.boot.slot_suffix", "ro.boot.bootloader"]
    commands = [(name, ["getprop", name]) for name in properties]
    commands += [
        ("uname", ["uname", "-a"]), ("shell_identity", ["id"]),
        ("memory", ["cat", "/proc/meminfo"]),
        ("cpu", ["cat", "/proc/cpuinfo"]),
        ("kvm_node", ["ls", "-l", "/dev/kvm"]),
        ("kvm_sysfs", ["ls", "-ld", "/sys/module/kvm"]),
        ("kernel_config_access", ["ls", "-l", "/proc/config.gz"]),
        ("null_device", ["ls", "-lZ", "/dev/null"]),
        ("partitions", ["ls", "-l", "/dev/block/by-name"]),
        ("pstore_access", ["ls", "-ld", "/sys/fs/pstore"]),
    ]
    for name, command in commands:
        checks[name] = run(prefix + ["shell"] + command)
    timestamp = datetime.now(timezone.utc)
    report = {"collected_at": timestamp.isoformat(), "device_serial": args.serial,
              "scope": "read-only ADB discovery; no root or boot-state changes",
              "checks": checks,
              "interpretation": "Reported boot properties are not independently verified. "
              "Permission failures or missing KVM nodes do not establish EL2 availability."}
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = args.output_dir / ("nio-inventory-" + timestamp.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    with path.open("x") as stream:
        path.chmod(0o600)
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print("Saved", path)
    for name, result in checks.items():
        if result.get("returncode") != 0:
            print("UNAVAILABLE:", name, result.get("stderr") or result.get("error"))


if __name__ == "__main__":
    main()
