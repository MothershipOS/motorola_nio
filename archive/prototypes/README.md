# Prototypes

One-off bring-up, measurement and reverse-engineering tools, kept as they were written (Python, shell, C). They are
not part of the build and not maintained: paths and commands in them refer to the system at the time
(e.g. `/usr/local/bin/mship-power`, `mship-vm-pixelos-crosvm`, `root@10.42.0.2`).

| | |
|---|---|
| `camera/` | Chromatix sensor-module parser (`chromatix.py summary|ctable`), RAW10 quick-look (`raw10view.py`) |
| `audio/acdb_extract.py` | Awinic speaker-protection setup from the stock ACDB (produced the nio-*-cal.bin firmware files) |
| `power/` | The standby power campaign: phone harness `power_test.py`, PC queue `sweep.py`, its plan `sweep.json` and cases; results in motorola_nio/docs/standby-measurements.md |
| `backup/` | The userdata rescue: dual SD+USB backup, card ingest/salvage, progress watch, `lpdump.py` (super partition layout) |
| `gpubench/` | `mshbench.c`: GLES 3 benchmark, host vs. Android guest |
| `touchinject/` | Synthetic uinput touchscreen for testing touch without a finger |
| `usb/` | `usb-test-device.sh` (dummy_hcd + mass-storage gadget: a USB device without a cable, for testing the USB handle), `dockwatch.sh` (log Type-C/DP/USB changes while testing docks) |
| `modem/` | SDX55 DIAG: `f3log.py` (F3 messages over /dev/wwan0qcdm0), `f3dec.py` (QShrink-4 decode against the stock `qdsp6m.qdb`), `gnss-probe.py` (QMI LOC session over QRTR with libqmi; motorola_nio/docs/gnss.md) |
| `diag-initramfs/` | The first RAM-only diagnostic init (ACM shell, auto return to fastboot), superseded by mship-init |
