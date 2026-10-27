# Standby power measurements

Queue: **complete**. Current condition: `—`. Updated: 2026-10-15T14:14:55+00:00.

Completed all **38 required conditions**; **1 Android screen-on condition not required** by user decision on 2026-10-15. The original plan had 39 conditions.

Each accepted condition samples for 30 minutes after five minutes of settling. Every condition is restored before the next.
USB power input is suspended; the cable remains attached. Logs use RAM. Settings and CPU idle counters are checked with the device awake.
Positive savings mean lower draw with the option. Matched control runs are used; these are estimates from one sweep, not independently calibrated power readings.

| Entry | Tested option | Status | Control mW | Option mW | Saving mW (%) |
|---|---|---|---:|---:|---:|
| S02 | Panel/display path off | Measured; temperature drift | 1911.6 | 1230.3 | +681.4 (+35.6%) |
| S03 | Touch delivery disabled | Measured | 1226.6 | 1218.0 | +8.5 (+0.7%) |
| S04 | Minimum CPU caps | Measured | 1222.4 | 1352.2 | -129.8 (-10.6%) |
| S04 | Existing powersave profile | Measured | 1222.4 | 1216.8 | +5.6 (+0.5%) |
| S04 | Balanced vs performance | Measured | 1270.2 | 1226.5 | +43.7 (+3.4%) |
| S05 | Deeper CPU idle enabled | Measured | 1294.0 | 1227.2 | +66.8 (+5.2%) |
| S11 | Power-key polling paused | Measured | 1229.7 | 1210.3 | +19.4 (+1.6%) |
| S13 | Host GPU runtime suspend | Measured | 1251.9 | 1237.9 | +14.0 (+1.1%) |
| S14 | Wi-Fi power saving | Measured | 1521.2 | 1225.3 | +295.8 (+19.4%) |
| S14 | Wi-Fi radio off | Measured | 1220.4 | 1172.3 | +48.0 (+3.9%) |
| S15 | UFS runtime suspend | Measured | 1237.6 | 1230.0 | +7.6 (+0.6%) |
| S15 | Secondary USB runtime PM | Measured | 1214.6 | 1233.6 | -19.0 (-1.6%) |
| S17 | USB development data link disabled | Measured | 1220.2 | 999.4 | +220.8 (+18.1%) |
| S17 | USB transfer ended | Measured | 1237.7 | 1217.3 | +20.4 (+1.7%) |
| S18 | Bluetooth radio off | Measured | 1242.7 | 1387.3 | -144.6 (-11.6%) |
| S02/S07 | Android display path off | Not required (user decision) | — | — | — |
| S11 | Android forced Doze | Measured | 1359.9 | 1351.0 | +8.9 (+0.7%) |
| S13 | Android GPU runtime suspend | Measured | 1446.1 | 1359.8 | +86.2 (+6.0%) |
| S01/S09 | Idle Android VM shut down | Measured | 1362.3 | 1226.2 | +136.1 (+10.0%) |
| S15 | Idle camera ISP runtime suspend | Measured | 1246.4 | 1224.8 | +21.6 (+1.7%) |

## Completed conditions

| Condition | Minutes | Mean mA | Mean mW | Mean °C |
|---|---:|---:|---:|---:|
| Host balanced baseline | 30.00 | 313.4 | 1229.5 | 33.5 |
| Panel on, existing brightness, touch delivery disabled | 30.00 | 504.1 | 1911.6 | 35.0 |
| Panel off, touch delivery disabled | 30.00 | 324.6 | 1230.3 | 32.8 |
| Touch delivery enabled, panel off | 30.00 | 326.2 | 1226.6 | 32.0 |
| Touch delivery disabled, panel off | 30.00 | 326.1 | 1218.0 | 31.7 |
| Fixed minimum CPU caps | 30.00 | 339.7 | 1352.2 | 32.7 |
| Existing powersave profile | 30.00 | 309.3 | 1216.8 | 31.7 |
| Existing balanced profile | 30.00 | 316.0 | 1226.7 | 31.5 |
| Existing performance profile | 30.00 | 332.4 | 1270.2 | 31.5 |
| Balanced profile after performance | 30.00 | 323.6 | 1226.5 | 31.5 |
| WFI-only CPU idle | 30.00 | 344.4 | 1294.0 | 31.5 |
| Original deeper CPU idle enabled | 30.00 | 328.5 | 1227.2 | 31.5 |
| Power-key recovery polling paused; host awake, USB connected | 30.00 | 303.1 | 1210.3 | 32.1 |
| Normal power-key recovery polling | 30.00 | 312.4 | 1229.7 | 31.3 |
| GPU runtime suspend prevented | 30.00 | 316.5 | 1251.9 | 32.2 |
| GPU normal runtime PM | 30.00 | 316.8 | 1237.9 | 32.5 |
| Wi-Fi associated, power save off | 30.00 | 401.2 | 1521.2 | 31.7 |
| Wi-Fi associated, power save on | 30.00 | 324.5 | 1225.3 | 31.2 |
| Wi-Fi radio disabled | 30.00 | 312.3 | 1172.3 | 30.6 |
| Wi-Fi radio enabled and associated | 30.00 | 327.6 | 1220.4 | 30.7 |
| UFS runtime suspend prevented | 30.00 | 310.1 | 1237.6 | 31.7 |
| UFS normal runtime PM | 30.00 | 312.5 | 1230.0 | 31.0 |
| Secondary USB controller automatic runtime PM | 30.00 | 317.5 | 1233.6 | 31.2 |
| Original secondary USB controller power policy | 30.00 | 317.2 | 1214.6 | 31.2 |
| USB gadget unbound; cable connected, USB power input suspended | 30.00 | 262.0 | 999.4 | 29.8 |
| USB development data link bound and idle | 30.00 | 323.4 | 1220.2 | 31.2 |
| USB SSH upload at 1 MiB/s | 30.00 | 330.4 | 1237.7 | 31.6 |
| USB data link idle after transfer | 30.00 | 326.9 | 1217.3 | 31.7 |
| Bluetooth radio blocked | 30.00 | 361.6 | 1387.3 | 32.8 |
| Bluetooth normal radio state | 30.00 | 326.4 | 1242.7 | 33.3 |
| Android running, panel off, Doze disabled | 30.00 | 342.6 | 1362.3 | 33.2 |
| Android panel off, forced deep Doze | 30.00 | 344.0 | 1351.0 | 33.3 |
| Android panel off, Doze disabled after Doze | 30.00 | 350.1 | 1357.5 | 33.0 |
| Android panel off; GPU runtime suspend prevented | 30.00 | 379.3 | 1446.1 | 33.0 |
| Android panel off; GPU normal runtime PM | 30.00 | 359.6 | 1359.8 | 33.4 |
| Host only after clean Android shutdown | 30.00 | 325.8 | 1226.2 | 33.7 |
| Idle camera ISP (CAMSS) runtime suspend prevented | 30.00 | 331.9 | 1246.4 | 33.6 |
| Idle camera ISP (CAMSS) normal runtime PM | 30.00 | 328.1 | 1224.8 | 34.0 |

## Remaining coverage and dependencies

- **S01:** Stock Android and Ubuntu Touch comparisons need separately verified measurement adapters; current sweep covers host and Android/crosvm.
- **S03:** Controller hardware sleep has no implemented independent switch; only existing touch delivery can be compared.
- **S06:** Only s2idle is advertised. Continuous CPU sampling keeps the host awake; the driver lacks a high-resolution sleep-energy counter. A 30-minute true-suspend power average needs suitable external instrumentation. No misleading awake samples will be labeled sleep power.
- **S07:** State propagation is a correctness issue, not an independent implemented power switch. Guest/host state snapshots are collected during Android tests.
- **S08:** Existing sleep blocker only matches QEMU, not crosvm. New VM lifecycle/voting behavior is not implemented; testing runs under an explicit sleep inhibitor.
- **S09:** Guest/host suspend coordination is not implemented. Idle VM overhead is measurable; coordinated suspend saving is not yet measurable.
- **S10:** Scoped guest wake-lock bridge and VM consensus protocol remain design drafts; there is no runtime on/off option.
- **S11:** Doze and the existing power-key polling loop are testable; broader timer batching has no implemented switch.
- **S12:** Physical PM8xxx RTC exposes wakealarm and wake is enabled. Guest deadline aggregation is not implemented; no independent saving can yet be assigned.
- **S13:** Runtime-PM savings can be measured; eliminating rendering work requires a separate implementation/performance decision.
- **S14:** Native host idle power save/radio-off can be measured; WoWLAN, notification delivery, and shared/native guest networking need functional tests.
- **S15:** GPU/UFS/CAMSS/secondary USB runtime controls are available. Sensor/camera capture, DSP/audio, interconnect and other paths need functionality and supported-control evidence.
- **S16:** Charging limits are preserved. The charger poll interval has no runtime tuning control; charging-current samples cannot serve as discharge-power comparisons.
- **S17:** USB data unbinding and active transfer are measurable with cable attached. Physical-unplug and charging-only cases cannot be inferred from them.
- **S18:** Bluetooth idle radio can be compared. Modem, sensors, call/SMS and audio wake paths require working integration and event tests.

## Condition not required by user decision

- `s01-android-screen-on`: **not required**, per user decision on 2026-10-15. Short diagnostic checks were rejected because Android keyguard forced sleep after 10 seconds. No valid screen-on measurement is claimed and no retry is planned. Raw failure records are retained in the archived evidence.

Raw results and saved settings: `reports/standby/20261013-power-sweep/cases/` (untracked).
The queue pauses for recharging/cooling when necessary. No new sleep or VM-voting policy is enabled.
Full queue: 39 conditions, about 22.8 hours plus recharge/cooldown time.
