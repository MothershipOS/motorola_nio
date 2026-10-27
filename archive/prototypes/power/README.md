# Temporary phone power tests

`power_test.py` runs on the **nio Linux host as root**, not inside Android or on
the PC. It compares the host alone, an Android VM with Doze disabled, and the
same VM in forced deep Doze. Each run settles for 60 seconds, then samples for
five minutes at three-second intervals. Repeat the conditions in reverse order
to check for battery/temperature drift.

The test uses the existing `mship-power` display control, temporarily stops
`mship-sleepd`, and applies the existing nio balanced CPU limits with `schedutil`.
It preserves CPU-idle enable flags. It does not install sleep policy, broker
handles, VM voting logic, or persistent configuration.

## Charger prerequisite

Before the module update on 2026-10-13, the charger driver only advertised `auto` and
`inhibit-charge`. **Inhibiting battery charging leaves USB supplying the phone**;
battery current then does not measure the phone's total consumption. Setting
`input_current_limit=0` is also unsuitable: this driver selects USB 500 mA mode
for that value.

The updated
[`0010` charger patch](../../kernel/patches/0010-power-supply-qcom-pm8150b-charger-fg.patch)
adds the standard Linux `charge_behaviour=force-discharge` setting. It disables
charging and sets the PM8150B USB input suspend bit. Returning to `auto` or
`inhibit-charge` clears input suspend through the normal charging policy,
including its existing temperature and charge thresholds.

The updated module is installed and loaded on the phone. A commissioning test
on 2026-10-13 confirmed `force-discharge`, negative battery current, USB input
offline, and working SSH over the USB data connection while the cable stayed
connected. The 15-second measurement completed and restored charging, CPU
settings, the screen state, and the original sleep daemon. Installation preserved
the battery's 75%/80% charging thresholds and existing current limits. Evidence:
`reports/nio-power-install-20261013T182709Z/` (untracked). This short check validates
the controls and cleanup; Android/Doze comparisons remain pending.
The script refuses unsupported drivers and only measures if the charger reports
`online=0`, battery status is `Discharging`, and battery current is negative.
This checks the reported hardware power path, rather than treating the requested
charging setting as proof. No raw PMIC register writes from the script.

Linux interface: [power supply ABI](https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-class-power).
Guest procedure: [Android Doze testing](https://developer.android.com/training/monitoring-device-state/doze-standby).

## Commands on the phone

The installed command is `/usr/local/sbin/mship-power-test`. Check readiness
without changing settings:

```sh
mship-power-test host --check
```

Close VMs for the host measurement, then start Android normally for the two VM
measurements. The harness does not boot or stop VMs. Only one VM may be running
in either Android condition; specify its actual ADB transport (the current
launcher uses `vsock:3:5555`, but CID allocation may change).

```sh
# No VMs running:
mship-power-test host

# Android running, booted, and available in `adb devices`:
mship-power-test android --adb-serial vsock:3:5555
mship-power-test doze --adb-serial vsock:3:5555
```

Run one condition at a time and leave the phone untouched. Each command starts
the transient `mship-power-test.service` and prints the output directory. The
worker runs locally with a sleep inhibitor, so losing SSH does not stop it.
Guest battery unplugging is an Android **simulation** to make the guest eligible
for Doze; the separate host charger control switches actual power input off.
Both VM modes use the same simulated battery state. Doze and guest sleep are
checked before and after measurement, without ADB polling during sampling.
Keep Wi-Fi, apps, and network workload comparable between runs.

```sh
journalctl -fu mship-power-test
systemctl stop mship-power-test     # cancel and restore
```

For a short commissioning test, use `--seconds 15 --settle 10`; if USB disappears,
wait for the local job to finish and restore its charging policy, then retrieve
the log. This cable-connected setup includes USB data overhead, so compare its
conditions with each other rather than assuming they match unplugged readings.

## Restoration and results

The script saves the original charger policy, CPU frequency settings, host and
guest display states, guest Doze enables, and sleep-daemon activity before
changing anything. It restores them on normal completion and caught signals.
`ExecStopPost` retries cleanup if the worker is killed or fails; a systemd
runtime limit prevents an abandoned test running indefinitely. Failed guest
cleanup does not prevent charger, CPU, host display, or sleep-daemon restoration.
Reboot/power loss cannot run cleanup; these runtime settings are not persisted.

Tests stop below 20% battery, at 42 C, on a host screen wake, or if the running
VM PID set changes. A guest with an already simulated battery or forced Doze
state is refused so cleanup does not overwrite an earlier experiment.

Results live in `/var/tmp/mship-power-TIMESTAMP/`:

- `original.json`: saved settings and guest diagnostic dumps.
- `samples.jsonl`: current, power, temperature, CPU counters and frequencies.
- `summary.json`: mean mA/mW, CPU busy percentage, interrupt/context-switch
  rates, and per-CPU idle-state residency. Interrupt counts are a proxy for
  activity, not a count of SoC wakeups.
- `restoration.json`: cleanup errors; an empty list means restoration succeeded.

If cleanup reports an error, use the saved output directory after resolving the
missing transport/service:

```sh
mship-power-test --restore --output /var/tmp/mship-power-TIMESTAMP
```

Snapshots from earlier boots are refused. Battery gauge absolute calibration is
unverified; three-second readings are correlated, so compare repeated whole-run
means rather than treating each sample as an independent trial.

The old module and pre-install settings are retained on the phone at
`/var/lib/mothership/module-backups/charger-20261013T182709Z/`. The updated module
replaces the root filesystem's module for `6.18.54-mothership-nio-dev`; installation
used a live module reload and did not require a boot-image update.

Host-side validation:

```sh
python3 -m unittest discover -s motorola_nio/tools/power -p 'test_*.py'
```

## Unattended checklist sweep

[`sweep.json`](sweep.json) schedules 39 conditions with 30 minutes of sampling and
five minutes of settling each (about 23 hours, plus recharging/cooling).
Each condition has a separate script under [`cases/`](cases/). The PC coordinator
[`sweep.py`](sweep.py) archives each result before continuing and maintains the
[live measurement table](../../../../docs/standby-measurements.md). It runs host
options first and groups the Android tests later to avoid repeated VM boots.

The active PC service is `mship-power-sweep-20261013.service`. It adopts the first
baseline already running, then installs the extended harness/case scripts on the
phone. Battery/temperature checks pause the queue for recharge/cooldown. A failed
measurement produces an incomplete row; failed restoration stops progression.
An external screen/VM change also stops the queue. The short installation check
is not counted as a 30-minute measurement.

On the PC:

```sh
systemctl --user status mship-power-sweep-20261013
journalctl --user -fu mship-power-sweep-20261013
systemctl --user stop mship-power-sweep-20261013
```

Stopping the PC coordinator stops the phone test and restores the initial
settings. During the USB-data-off condition, SSH is deliberately unavailable;
the phone's local runtime limit and cleanup restore the link after the condition.
If the PC disappears, the current phone condition still restores locally; the
queue cannot advance until the PC coordinator is available again.

Raw data and queue state are in `reports/standby/20261013-power-sweep/` on the PC.
The old module backup from commissioning remains on the phone. Planned sleep,
VM consensus, wake-lock and alarm protocols do not receive invented power-saving
values: their missing implementation/instrumentation is recorded in the table.

Recovery notes (2026-10-15): VM guards also inspect `/proc/PID/exe`, since `crosvm --name` changes the process name to the guest name. Screen status reads compositor output power while the host owns DSI-1, and the existing `/run/mothership/screen` handle while the handover state leases that panel to a VM. Production sleep and power controls are unchanged.

When the PC filesystem is full, use a RAM output directory and `--archive-target user@nas:/path` to archive results after each condition. The live state, raw samples, bundle and coordinator log must all stay off that filesystem. The repository measurement table is updated when space permits; a failed table mirror does not abort a run whose live results are safe. The recovery run uses `/dev/shm/mship-power-sweep-20261013-pc`; the usual `reports/standby/20261013-power-sweep` path links there. Its durable archive is `<backups>/phone-power-tests/20261013-power-sweep` on the NAS. Copy from that archive if the PC restarts and loses RAM.
