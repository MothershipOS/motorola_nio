# Standby: testing and implementation checklist

Prepared 2026-10-13. Scope: mothershipOS host, Android/other guests, and the nio port.

This is a planning checklist. Tests are pending unless an entry records a completed experiment; the
checklist itself authorizes no runtime changes. Keep the existing power behavior until we decide which entries to implement.
The current-state notes describe repository code, not a verified live-device configuration.

The user authorized an unattended measurement sweep on 2026-10-13. Each available
condition gets 30 minutes of sampling, with control runs, saved settings, and
restoration between tests. Follow the [live measurement table](standby-measurements.md)
for results and gaps. The sweep finished on 2026-10-15: **38 conditions completed,
19 comparisons recorded, and the Android screen-on condition is not required by
user decision**. Each accepted condition measured for 30 minutes after five minutes
of settling; original settings were restored. This authorizes temporary experiments; implementation
decisions and new automatic sleep/VM-consensus logic remain pending.

## Recorded measurement sweep — 2026-10-13 to 2026-10-15

- [x] Complete all 38 required conditions and save the 19 measured comparisons below.
- [x] Restore original CPU, charging, display, and sleep settings after the sweep.
- Android screen-on comparison: **not required**, per user decision on 2026-10-15.
  Its short diagnostic runs were invalidated by the lock-screen timeout and are not power results.
- [x] Archive raw samples, snapshots, restoration records, and reports on the NAS:
  `<backups>/phone-power-tests/20261013-power-sweep/`.

The [measurement table](standby-measurements.md) contains control/option power,
current, temperature, and individual runs. Raw evidence is available through
`reports/standby/20261013-power-sweep/`; its live local directory is RAM-backed, so
the NAS archive is the durable copy.

Results below are whole-phone battery-gauge readings with USB power input suspended,
USB data connected unless explicitly disabled, and the host awake. Positive savings mean
lower measured draw; negative savings mean higher draw. They are estimates from one
sweep, not independently calibrated measurements. Small differences need replication;
savings from separate comparisons must not be added together. They do not establish
whole-system suspend power, wake reliability, or approval for a runtime policy change.

## How to track an entry

Each entry separates investigation from a possible change. Check a test only after recording its result.
Check an implementation only after choosing it, making the change, and validating its behavior.
Existing behavior is described in prose; an unchecked box does not mean that behavior is absent.

For each decision, record **implement**, **keep current behavior**, **defer**, or **decline**, with a reason.
All decisions start as **pending**. Effort estimates are preliminary: small, medium, or large.

Record results under `reports/standby/<date>-<scenario>/` (untracked): kernel/build identity, configuration,
guest/VMM versions, battery level and temperature, charging/USB state, screen state, workload, test duration,
power readings, wake reasons, logs, and the conclusion. Record the decision and report path in this file.

## Test setup and baseline

### S01 — Measure standby power and wake activity

Current: no stock-Android versus mothershipOS standby baseline was established by the code inspection.
Effort: small–medium.

- [x] Measure awake screen-off host baseline: **1229.5 mW / 313.4 mA**;
  Android/crosvm idle with Doze disabled: **1362.3 mW / 342.6 mA**.
  A fresh host control after VM shutdown measured **1226.2 mW / 325.8 mA**.
  Shutting down the idle VM reduced whole-phone draw by **136.1 mW (10.0%)**.
  Stock Android and Ubuntu Touch remain unmeasured.

- [ ] Test: compare stock Android and mothershipOS under matching battery, temperature, radio, and
  screen conditions. Separate host-only, Android/crosvm, and Ubuntu Touch/QEMU scenarios.
- [ ] Test: distinguish screen-off while awake from actual system suspend. Record current/power,
  CPU activity, suspend residency, wake frequency/reasons, and peripheral runtime state.
- [ ] Test: compare USB disconnected, development USB connected, and charging separately. Allow the
  device to settle; report the measurement duration and instrumentation limits.
- [ ] Candidate implementation: add repeatable measurement/reporting tools if existing tools are insufficient.
- [ ] Validate any selected tooling: it must not materially prevent the idle/suspend state being measured.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

Prepared tooling (archived: [`motorola_nio/archive/prototypes/power/`](../archive/prototypes/power/README.md))
provides host-only, Android idle, and forced-Doze measurements with USB input
suspended and automatic restoration. The charger-module update and
`mship-power-test` command are installed on the phone. A 2026-10-13 host-only
commissioning test verified real battery discharge with working USB data and
successful restoration; evidence: `reports/nio-power-install-20261013T182709Z/`.
The host/Android/Doze comparisons above are complete and measure screen-off
operation while the host stays awake.

## Display, touch, and CPU

### S02 — Panel and backlight power

Current: host and Android guest paths switch off the panel/CRTC and backlight. Effort: small.

- [x] Measure host panel/display path off: **1911.6 → 1230.3 mW**,
  a reduction of **681.4 mW (35.6%)**, at the existing brightness with touch
  delivery disabled in both runs. Mean temperature differed by **2.2°C**;
  thermal drift limits attribution. This includes scanout/rendering changes.
- Android screen-on versus screen-off power comparison: **not required** by the user
  on 2026-10-15; no valid 30-minute screen-on result is claimed.

- [ ] Test: screen ownership changes and guest exit while the panel is off; check reliable display recovery.
- [ ] Candidate implementation: correct any remaining display clocks, resources, or resume behavior found by testing.
- [ ] Validate any selected change: repeated off/on and ownership cycles restore the expected frame and brightness.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

### S03 — Touch-controller sleep and wake

Current: host screen-off disables touch delivery; controller low-power state is unverified. Effort: medium.

- [x] Compare software touch delivery enabled/disabled with the panel off:
  **1226.6 → 1218.0 mW**, saving **8.5 mW (0.7%)** in this sweep.
  This does not establish controller hardware sleep, gesture wake, or input-isolation correctness.

- [ ] Test: inspect controller activity, interrupts, and power with the screen off. Check host and guest paths separately.
- [ ] Test: verify that screen-off touches cannot reach a guest or trigger unwanted actions.
- [ ] Candidate implementation: controller sleep, with a separately chosen gesture-wake policy if supported.
- [ ] Validate any selected change: no pocket input, reliable wake, and correct touch behavior after resume.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

### S04 — CPU frequency policy

Current: CPU governors and power profiles are available. Effort: small.

- [x] Measure existing profiles with the host awake and screen off, recording CPU
  caps/governors and power. Against the matched balanced control (**1222.4 mW**),
  minimum caps measured **1352.2 mW**: **129.8 mW more draw (10.6%)**.
  The existing powersave profile measured **1216.8 mW**, saving **5.6 mW (0.5%)**.
  Returning from performance to balanced reduced **1270.2 → 1226.5 mW**,
  saving **43.7 mW (3.4%)**. Minimum caps did not demonstrate an idle saving.

- [x] Host-only experiment, 2026-10-13: compare balanced `schedutil` limits with the existing fixed
  minimum-frequency caps, crossed with deeper idle enabled/disabled. Eight windows completed, screen
  off, no VMs, USB disconnected. With deeper idle enabled, balanced averaged 216.2 mA and minimum caps
  221.4 mA: no demonstrated additional idle saving from the minimum caps. See the
  [measurement report](../reports/nio-power-idle-20261013T173630Z/results.md).
- [ ] Test: compare foreground workloads and responsiveness under the existing CPU profiles.
- [ ] Test: identify background work keeping CPUs active; distinguish useful work from polling.
- [ ] Candidate implementation: tune frequency limits/governor policy or remove unnecessary work, based on measurements.
- [ ] Validate any selected change: quantify savings and check interactive, guest, and audio performance.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

### S05 — CPU and SoC idle states

Current: the inspected kernel build enables PSCI CPU idle and Qualcomm RPMh support. The CPU idle-state
comparison below measured savings; deepest SoC states and physical rail behavior remain unverified.
Effort: medium.

- [x] Repeat the deeper-idle comparison with 30-minute conditions and USB data
  connected: WFI-only **1294.0 mW**, original deeper idle **1227.2 mW**;
  saving **66.8 mW (5.2%)**. Saved CPU idle counters/residency for host and Android
  conditions. These awake, USB-connected conditions differ from the earlier unplugged test.

- [x] Host-only experiment, 2026-10-13: compare WFI-only with the already-enabled rail-power-collapse
  idle states on all eight cores, under balanced and minimum-frequency caps. Balanced draw fell from
  272.9 to 216.2 mA (56.7 mA, 20.8%); at minimum caps it fell from 239.7 to 221.4 mA (18.3 mA, 7.6%).
  Kernel-reported deeper-state residency averaged about 76% under balanced scaling and 71% at minimum
  caps, versus zero while those states were disabled. This does not independently verify physical rail
  states or whole-system suspend. Original CPU/idle settings, persistent configuration, and the sleep
  daemon were restored and verified. See the
  [measurement report](../reports/nio-power-idle-20261013T173630Z/results.md).
- [x] Test: record available idle states and residency with no VM and with idle Android/crosvm.
- [ ] Test: inspect relevant clock/power-domain votes and wake sources to identify blockers.
- [ ] Candidate implementation: correct device-tree, driver, or firmware integration only where evidence identifies a gap.
- [ ] Validate any selected change: demonstrate deeper-state residency, lower power, and reliable wake.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

## Host and guest suspend coordination

Design input for S06–S12: [draft `mship.power` handle contract](https://github.com/MothershipOS/mothershipOS/blob/main/docs/contracts/mship.power-1.draft.md).
Every running VM participates through the existing slot/contract model. The draft records strongest-profile
aggregation and unanimous sleep permission, with broker-owned attachment state. It adds no runtime logic
and is not listed as supported in the compatibility registry; its detailed choices remain pending.

### S06 — Existing whole-system suspend policy

Current: `mship-sleepd` requests suspend after screen-off and a grace period, unless a configured blocker
applies; it retries after a wake without screen-on. Documentation describes suspend-to-idle. Effort: small–medium.

Measurement coverage: **not measured**. Only `s2idle` is advertised; continuous
CPU sampling keeps the host awake. The driver lacks a suitable high-resolution
sleep-energy counter. True-suspend average power needs suitable external instrumentation;
awake samples must not be reported as whole-system sleep power.

- [ ] Test: establish the deployed settings and selected kernel sleep state before evaluating behavior.
- [ ] Test: in a later agreed test session, verify entry, time asleep, wake reasons, and repeated resume cycles.
- [ ] Test: verify power-key wake and preservation of host state, network recovery, and hardware ownership.
- [ ] Candidate implementation: revise the existing policy only after deciding the desired behavior and supported wake sources.
- [ ] Validate any selected change: repeated cycles succeed and measured standby power improves.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

### S07 — Android display state and host screen state

Current: Android display-power messages signal the presenter; that path does not update the screen-state
file consumed by `mship-sleepd`. Display-off alone does not establish that a guest is ready for host suspend.
Effort: small for state plumbing; suspend eligibility depends on S09/S10.

Measurement coverage: guest/host state snapshots were saved during the Android idle,
forced-Doze, and GPU conditions. The Android screen-on power comparison is **not required**
by user decision. The correctness test for state propagation and ownership remains pending.

- [ ] Test: compare guest display state, physical panel state, and `/run/mothership/screen` through off/on cycles.
- [ ] Candidate implementation: define ownership-aware propagation of guest screen state to host policy.
- [ ] Validate any selected change: stale guest events cannot override the current owner's screen state or cause premature suspend.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

### S08 — VM detection

Current: the sleep blocker detects QEMU processes but not crosvm. Effort: small.

- [x] Diagnose measurement-harness VM detection: `crosvm --name pixelos` changes
  `/proc/PID/comm` to `pixelos`; detection now also checks the executable. The corrected
  harness accepted the five Android conditions. This is a test-tool fix; the production
  sleep blocker and VM lifecycle/voting protocol were not changed.

- [ ] Test: check blocker behavior for QEMU, crosvm, both together, guest shutdown, and stale launcher processes.
- [ ] Candidate implementation: cover both VMMs, preferably through authoritative VM lifecycle state rather than process-name matching.
- [ ] Validate any selected change: preserve the chosen conservative policy until guest-aware suspend is explicitly selected.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

### S09 — Guest suspend and physical-host suspend

Current: no coordinated guest-to-host suspend protocol was identified. Effort: large.

- [x] Measure idle Android VM overhead with screen off and Doze disabled, then
  cleanly stop the VM and measure a fresh host control: **1362.3 → 1226.2 mW**,
  saving **136.1 mW (10.0%)**. This is VM shutdown, not coordinated guest/host suspend.
  Guest states, CPU activity, interrupts, and idle counters were saved with each condition.

- [ ] Test: determine what the Android guest actually does on screen-off, Doze, idle, and virtual suspend.
- [ ] Test: identify host activity generated by idle virtual CPUs, device emulation, graphics, and guest timers.
- [ ] Candidate implementation: define a generic guest readiness protocol and host eligibility rules for all guests and host workloads.
- [ ] Candidate implementation: define virtual-device quiescing, resume ordering, failure handling, and guest timekeeping behavior.
- [ ] Validate any selected change: multi-guest operation, active-work blockers, resume correctness, and loss-free device recovery.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

### S10 — Wake locks and suspend inhibitors

Current: host blockers are coarse; no guest/host wake-lock bridge was identified. Effort: medium–large.

Measurement coverage: **not measured**. Scoped guest wake-lock bridging and VM
consensus remain drafts without an independent runtime switch. No power saving is assigned.

- [ ] Test: enumerate operations that must keep the host awake, including transfers, audio, guest work, and hardware activity.
- [ ] Candidate implementation: scoped inhibitors with ownership, cleanup on disconnect/crash, and diagnostics.
- [ ] Candidate implementation: define how guests express necessary activity without permanently preventing standby.
- [ ] Validate any selected change: required work completes; crashed clients and expired work cannot leave permanent blockers.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

### S11 — Doze and background-work batching

Current: forced deep Doze was measured in this guest; normal Doze/App Standby eligibility and behavior remain unverified.
No comparable host-wide background-work policy was identified. Effort: medium.

- [x] Compare forced Android deep Doze against the two Doze-disabled idle controls:
  **1359.9 → 1351.0 mW**, saving **8.9 mW (0.7%)**. Guest deep-Doze state was
  checked; normal eligibility, maintenance windows, exemptions, and notifications remain unvalidated.
- [x] Compare the host power-key recovery poll loop active/paused while awake with
  USB connected: **1229.7 → 1210.3 mW**, saving **19.4 mW (1.6%)**.
  Diagnostic only: this loop repairs a power-key IRQ issue; removal is not approved.

- [ ] Test: verify guest Doze eligibility, configuration, maintenance windows, and exemptions.
- [ ] Test: inventory host timers, polling loops, logs, and scheduled maintenance during screen-off.
- [ ] Candidate implementation: batch deferrable host work and remove unnecessary polling; adjust guest settings only if selected.
- [ ] Validate any selected change: fewer wakeups without breaking chosen notification, maintenance, or background-task behavior.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

### S12 — Guest alarms and timed wake

Current: no coordinated guest wake-deadline scheduling through a physical host RTC was identified. Effort: large.

Measurement coverage: the PM8xxx RTC exposes `wakealarm` with wake enabled, but
physical timed-wake reliability and guest deadline aggregation were not tested in this
power sweep. No independent saving is assigned; aggregation remains unimplemented.

- [ ] Test: inventory guest alarm/deadline mechanisms and physical RTC wake capabilities.
- [ ] Candidate implementation: aggregate wake deadlines, program the host wake source, and resume the required guest.
- [ ] Validate any selected change: simultaneous guest alarms, cancellation, clock changes, overdue deadlines, and acceptable timing accuracy.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

## Physical devices and external connections

### S13 — GPU idle and power-down

Current: guest screen-off stops scanout and drops queued frames; host and Android GPU runtime-PM comparisons are recorded below. Physical rail power-off remains unverified.
Effort: medium.

- [x] Compare GPU runtime-PM `on` versus `auto` with the host screen off:
  **1251.9 → 1237.9 mW**, saving **14.0 mW (1.1%)**.
- [x] Repeat with Android running and screen off: **1446.1 → 1359.8 mW**,
  saving **86.2 mW (6.0%)**. Runtime state/counters were saved. These measurements
  do not independently prove GPU rail power-off or validate rendering after resume.

- [ ] Test: inspect rendering activity, GPU utilization, clocks, and runtime state with host and guest screens off.
- [ ] Candidate implementation: eliminate unnecessary rendering/work and release resources that prevent runtime suspend.
- [ ] Validate any selected change: measurable GPU idle/power improvement and correct rendering after resume or ownership changes.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

### S14 — Wi-Fi power saving and network wake

Current: the Wi-Fi bridge forwards guest power-save requests to the physical driver; effectiveness and
wake-on-WLAN behavior are unverified. Effort: medium.

- [x] Compare native host Wi-Fi power save while associated with the existing AP:
  **1521.2 → 1225.3 mW**, saving **295.8 mW (19.4%)**.
- [x] Compare associated radio-on versus radio-off: **1220.4 → 1172.3 mW**,
  saving **48.0 mW (3.9%)**, with Wi-Fi connectivity lost. Guest/native bridge modes,
  WoWLAN, notifications, and network recovery remain functional-test work.

- [ ] Test: confirm driver/firmware capabilities and power-save behavior for native Wi-Fi and shared-network modes.
- [ ] Test: check association retention, traffic, wake reasons, and notification/network recovery during standby.
- [ ] Candidate implementation: select supported power-save settings and firmware wake filters, with a documented connectivity policy.
- [ ] Validate any selected change: useful network events still work while irrelevant traffic does not cause excessive wakes.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

### S15 — Storage and other device runtime PM

Current: kernel runtime-PM support exists; the OV64B camera driver has explicit runtime-PM/autosuspend code.
End-to-end peripheral power coverage is unverified. Effort: medium–large.

- [x] Compare UFS runtime-PM `on` versus `auto`: **1237.6 → 1230.0 mW**,
  saving **7.6 mW (0.6%)**. Samples used RAM; ordinary background writes could still wake storage.
- [x] Compare secondary USB controller original `on` policy versus `auto`:
  **1214.6 → 1233.6 mW**; **19.0 mW more draw (1.6%)**, with no demonstrated saving.
- [x] Compare idle CAMSS ISP runtime-PM `on` versus `auto`: **1246.4 → 1224.8 mW**,
  saving **21.6 mW (1.7%)**. This does not establish sensor rail behavior, capture,
  audio/DSP, interconnect coverage, or peripheral correctness after resume.

- [ ] Test: audit storage, camera, audio/DSP, USB, interconnect, and other device runtime states, clocks, and power domains.
- [ ] Test: distinguish hardware absent/off from hardware operational in a verified low-power state.
- [ ] Candidate implementation: fix identified missing callbacks, resource releases, or autosuspend settings per device.
- [ ] Validate any selected change: data integrity, peripheral operation after resume, and measured power reduction.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

### S16 — Charging limits during suspend

Current: charging toward a configured limit blocks suspend because enforcement depends on a polling loop.
Effort: medium.

- [x] Establish the measurement charging setup: PM8150B `force-discharge` suspends
  USB power input while USB data stays usable; validate `online=0`, battery discharging,
  and negative battery current. Normal charging policy/limits were restored after each run.
  `inhibit-charge` alone leaves USB powering the host and is not a discharge-power measurement.

Measurement gap: charger polling has no runtime tuning switch; its power cost and
hardware charge-limit enforcement through physical suspend remain unmeasured.

- [ ] Test: establish charger/PMIC hardware-limit and wake-event capabilities; measure the existing polling policy.
- [ ] Candidate implementation: use verified hardware limits or a suitable wake-capable enforcement mechanism.
- [ ] Validate any selected change: charge limits and charger safety behavior remain correct through suspend and reconnects.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

### S17 — USB development connection

Current: the configured USB development link blocks suspend by default; this is configurable. Effort: small–medium.

- [x] Compare USB development link bound-idle versus unbound with the cable attached:
  **1220.2 → 999.4 mW**, saving **220.8 mW (18.1%)**. This is not a physical-unplug
  or charging-only measurement; USB power input was suspended in both conditions.
- [x] Compare 1 MiB/s encrypted USB upload versus the idle link after transfer:
  **1237.7 → 1217.3 mW**, saving **20.4 mW (1.7%)**. This includes encryption/CPU cost.

- [ ] Test: separate connected-idle, active transfer, disconnected, and charging-only cases.
- [ ] Candidate implementation: choose an explicit development/normal-use policy and supported USB suspend/resume behavior.
- [ ] Validate any selected change: transfer inhibitors work, connection recovery is reliable, and the policy remains discoverable.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

### S18 — Modem, Bluetooth, sensors, and audio wake

Current: Android guest integration is incomplete; modem support is untested. Host audio and Bluetooth
functionality do not establish low-power or guest-wake correctness. Effort: large; split by subsystem when selected.

- [x] Compare idle Bluetooth normal radio state versus blocked/off:
  **1242.7 → 1387.3 mW**; **144.6 mW more draw (11.6%)**, with no demonstrated saving.
  Calls, audio, Bluetooth wake, modem/SMS, sensors, and guest-wake behavior were not validated.

- [ ] Test: inventory working host and guest paths, autonomous firmware capabilities, and supported wake events per subsystem.
- [ ] Candidate implementation: define low-power and wake requirements separately for calls/SMS, Bluetooth, sensors, and audio playback.
- [ ] Validate any selected change: required events wake the correct guest; idle hardware sleeps; ongoing playback/calls retain correct behavior.

Implementation decision: pending. Results and remaining coverage recorded above; [measurement table](standby-measurements.md).

## Decision session

- [ ] Review baseline results and agree on measurable standby and wake-behavior goals.
- [ ] Choose implement / keep / defer / decline for each entry; record dependencies and rationale.
- [ ] Choose a test and implementation order. S01 supplies evidence; S07/S08 expose known state/detection gaps.
- [ ] Agree on S09/S10/S12 semantics before enabling automatic physical suspend with running guests.
- [ ] Turn selected entries into scoped implementation tasks with acceptance criteria and rollback plans.

## Reference code and documentation

- [Host sleep policy](../host/power/mship-sleepd), [screen power](../host/power/mship-power),
  [CPU profiles](../host/shell/mship-admin).
- [Android launcher](../guests/android/launcher/mship-vm-pixelos-crosvm),
  [display presenter](../host/vm-display/mship-vm-display.c),
  [display-power contract](https://github.com/MothershipOS/mothershipOS/blob/main/docs/contracts/mship.display-power-1.md).
- [Wi-Fi bridge](../host/wifi-bridge/mship-wifi-bridge),
  [camera driver patch](../kernel/patches/0008-camera-wl2864c-regulator-ov64b-sensor.patch),
  [nio kernel configuration](../kernel/configs/nio-host.config).
- Kernel-build observations came from the local, untracked `kernel-work/out/lts/.config`; verify the deployed
  kernel separately. Compiled support is not proof that hardware enters a low-power state.
- Android: [SystemSuspend](https://source.android.com/docs/core/power/systemsuspend),
  [Doze and App Standby](https://developer.android.com/training/monitoring-device-state/doze-standby).
- Linux: [device power management](https://www.kernel.org/doc/html/latest/driver-api/pm/devices.html).
