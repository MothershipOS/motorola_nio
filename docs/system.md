# CPU scaling, shell UI, RTC

> Bring-up log moved from the old PORT-NOTES diary (2026-10-08..12); dated entries are as written then.
> Paths were updated to the current repo layout.

## CPU scaling, shell UI, RTC (2026-10-12)
- cpufreq: qcom-cpufreq-hw deferred forever ("Failed to find icc paths") because the EPSS L3 interconnect
  (icc_osm_l3) is a module; now loaded via /etc/modules-load.d. 3 policies (A55 0.3-1.8, A77 0.71-2.42,
  prime 0.84-3.09 GHz), schedutil; cpufreq cooling devices throttle at ~90 C. Profiles via mship-cpu.service.
- Shell UI: host/shell (GTK4/libadwaita `mothership-shell` as mship + root helper `mship-admin`
  via sudoers; wvkbd OSK shown while a text widget has focus). Popovers are dismissed when the OSK (another
  client) is touched -> searchable choices use full-page pickers. Assist key = home (mship-home), VMs on
  workspace 2 at scale 1, shell on workspace 1 at scale 2. Host had no sudo: installed sudo-rs.
- RTC: rtc-pm8xxx reads the PM8150 counter (seconds since PMIC init, ~1970-01-04) and HCTOSYS set that at boot
  = the "clock resets" cause. HLOS can't write the counter (stock uses an offset in time_daemon), the only
  stock-described SDAM (pm8150 sdam@b100) is used by FG/PBS, so the offset lives in
  /var/lib/mothership/rtc-offset: mship-rtc.service restores RTC+offset before sysinit, saves at shutdown;
  mship-timesync (now direct over Wi-Fi first, proxy fallback) saves after each sync. Verified: after a reboot
  without network the clock was within 1 s of the PC.
- Screen & sleep: power key (XF86PowerOff, sway --locked binding) -> mship-power toggle: DSI-1 DPMS off
  (CRTC off, WLED bl_power=4) + panel touchscreen input disabled (by identifier, not type:touch: that rule
  sticks to future touch devices). swayidle (mship-idle, timeout from /etc/mothership/power.json).
  mothershipd (root; formerly mship-sleepd): screen off + every mship.power participant agrees (USB gadget not
  'configured' unless disabled) -> after 10 s `systemctl suspend` (s2idle). Verified: suspend/resume OK at EL2 (ath11k powers down and reloads fw,
  rejoins in ~13 s; touch re-inits; USB gadget re-enumerates), RTC alarm wakes it. pm8941_pwrkey and gpio-keys
  are wakeup sources. Not measured: power draw in s2idle (no fuel gauge driver yet), cluster/CX collapse.
- Power key "does nothing" (2026-10-12): PON INT_EN 0x815 bit0 was clear again long after boot (0x03 at boot,
  0x02 later, pwrkey IRQ count 0). Not caused by s2idle suspend/resume nor by DPMS off/on (both tested). After a
  rebind, real presses interrupt and toggle the screen. mship-pwrkey-rearm.service is now a watchdog (2 s) that
  re-arms and logs each occurrence -> use its journal timestamps to find the culprit. Also fixed mship-sleepd
  VM detection (matched the shell's own `pgrep qemu-system-[a]arch64` command line).
