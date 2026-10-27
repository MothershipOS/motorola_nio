# mothershipOS: Motorola nio implementation plan

## Goal
Run a Linux hardware host on Motorola nio with multiple Android ARM64 VMs and
an Ubuntu ARM64 VM. Guests share CPU capacity, dynamically allocated RAM, and
host-mediated access to physical devices. Priorities below are provisional and
can be reordered by the owner while preserving dependencies.

## Proposed architecture
- Kernel: upstream-based Linux 6.18.y LTS with a versioned nio patch series.
  Initial baseline pinned to 6.18.54 on 2026-09-27; track later LTS updates.
- Host: minimal Debian ARM64, systemd, networking, logs and hardware services.
- Virtualization: KVM; evaluate crosvm/Cuttlefish for Android and crosvm for Ubuntu.
  Confirm the Ubuntu boot and virtual-device path experimentally.
- Graphics: Linux DRM/MSM and Mesa Freedreno/Turnip; evaluate Gfxstream for Android.
- Resource manager: common CPU set, cgroup weights, guest memory statistics and
  virtio-balloon, with host headroom and explicit pressure policy.
- Device services: virtual devices and guest adapters; custom Android HAL work
  where needed. Linux owns physical devices and arbitrates conflicting requests.
- Interface: host compositor presents guest environments and routes focused input.

## Milestones and completion tests

| ID | Priority | Goal | Depends on | Completion test |
| --- | --- | --- | --- | --- |
| M01 | P0 | Inventory exact phone, boot state, workloads and tools | None | Reproducible read-only report; unknowns explicitly recorded |
| M02 | P0 | Establish recovery and reproducible builds | M01 | Original images and device data preserved; tested recovery path; versioned build inputs |
| M03 | P0 | Prove access to EL2 and working KVM | M01, enough of M04 to boot | Small ARM64 guest runs with KVM explicitly required, including timers and multiple vCPUs |
| M04 | P0 | Bring up upstream-based LTS kernel | M01, M02 | Repeatable boot, USB diagnostics, UFS, thermal monitoring, charging and CPU power management |
| M05 | P1 | Establish persistent minimal Linux host | M04 | Host boots reliably and starts, stops and logs test guests |
| M06 | P1 | Run one Android VM and Ubuntu VM together | M03, M05 | Both have private persistent storage and networking and reboot independently |
| M07 | P1 | Implement shared CPU/RAM budget | M06 | Capacity shifts under demand without host starvation or uncontrolled guest loss |
| M08 | P1 | Enable accelerated graphics and guest switching | M04, M06 | Host and both guests render; display, touch and focus switching work |
| M09 | P2 | Share physical peripherals | Relevant M04 drivers, M06 | Each supported device passes host, guest and concurrency/conflict tests |
| M10 | P2 | Add Android instances and shared-file service | M06, M07 | Requested instance count works; private data stays private and shared files are coherent |
| M11 | P2 | Tune daily use and power management | M07, M08, relevant M09 | Sustained workload, charging, idle and suspend/resume meet measured targets |
| M12 | P2 | Package updates, rollback and regression checks | Working milestones | Updates and restore tested without rebuilding everything manually |

M03 is the first feasibility gate: CPU capabilities or a /dev/kvm node alone do
not prove usable virtualization. If EL2 is inaccessible, investigate the boot
chain before investing in VM integration. Containers are a possible alternative,
but require an explicit architectural decision because the goal is real VMs.

First end-to-end milestone: Android plus Ubuntu running concurrently through KVM
with networking and dynamic CPU/RAM allocation. This is an intermediate milestone;
all physical-device sharing remains part of the overall objective.

## Resource allocation
- A vCPU is a concurrency ceiling, not a reserved physical core.
- Prefer shared scheduling and weights to dedicated cores; prioritize interactive
  guests without starving host services.
- Reserve measured headroom for host, VM processes and graphics buffers.
- Give each guest a measured minimum and a configurable maximum, and rebalance
  with virtio-balloon using guest/host pressure and foreground state.
- Coordinate Android lmkd with balloon policy. Ballooning can induce app kills;
  live memory cannot be reclaimed arbitrarily. Pausing alone does not free RAM.
- Define overload behavior: cache reclaim, bounded compression/swap, guest app
  reclaim, and controlled guest shutdown. Do not promise unlimited concurrency.

## Physical-device sharing
| Device | Proposed sharing behavior |
| --- | --- |
| GPU | Virtual graphics backends sharing the host GPU; validate each guest stack |
| Display and input | Host composition with focused input routing |
| Speakers and microphone | Mix playback and distribute allowed capture streams |
| Cameras | Host capture with shared streams; arbitrate lens/exposure conflicts |
| GPS and sensors | Distribute readings; coordinate sampling rates and power |
| Wi-Fi and mobile data | Per-guest virtual networking over host connections |
| Calls, SMS and SIM | Host telephony with guest adapters; real IMS support is a separate milestone |
| Bluetooth, NFC and USB | Broker supported operations or grant temporary ownership |
| Hardware video codecs | Validate drivers and implement guest acceleration integration |
| Fingerprint and secure hardware | Investigate host authentication interfaces and identity constraints |
| Files | Independent guest disks plus explicit shared-file service |

Sharing may mean simultaneous use, queuing, or temporary ownership. Independent
stock-style attestation and every vendor feature are unproven, not guaranteed.

## Current evidence and next actions
- Connected nio / XT2125-4 has about 8 GB RAM and existing Magisk root access.
- Running kernel is 4.19.325-cip136-st20-perf+. Its config disables virtualization;
  missing /dev/kvm does not prove EL2 is unavailable.
- Root-read boot command line reports orange and slot A, contradicting the
  green/locked Android properties. Bootloader-level verification is pending.
- Captured live DT, kernel config and command line. Validated current slot-A
  boot/vendor_boot/dtbo/vbmeta/vbmeta_system backups with hashes; recovery untested.
- Pinned Linux 6.18.54 LTS, implemented repeatable configuration/build tools and
  a draft nio DTS checked against all 25 fixed live memory reservations.
- Linux 6.18.54 boots via RAM-only `fastboot boot` to a USB-shell initramfs;
  logs come out over USB ACM, ramoops, ABL `logfs` and `fastboot oem logdump`.
  No flash, unlock or phone partition write has been performed.
- M03 blocker: Linux is entered at EL1 and reports "HYP mode not available";
  the firmware keeps EL2. KVM needs a boot-chain solution or an architecture
  decision before VM work.
- M02/M04 are in progress. See [kernel status](kernel/STATUS.md) and
  [build instructions](kernel/README.md) for the next steps and current limits.

## Adjustable priorities / open decisions
- Number of Android instances and simultaneous workloads.
- Ubuntu desktop versus headless Linux tasks.
- Order within M09: audio/camera, cellular telephony, sensors, Bluetooth/NFC/USB.
- Battery life, suspend and thermal targets.
- Guest trust/isolation requirements and per-device access policies.

## Reference starting points
- https://www.kernel.org/releases.html
- https://github.com/LineageOS/android_device_motorola_nio
- https://gitlab.com/sm8250-mainline/linux
- https://source.android.com/docs/devices/cuttlefish/get-started
- https://source.android.com/docs/devices/cuttlefish/gpu
- https://crosvm.dev/book/devices/balloon.html
- https://docs.mesa3d.org/drivers/freedreno.html

## Running discovery
Run `python3 tools/inspect_nio.py --serial DEVICE_SERIAL`.
Reports are local and may contain device identifiers and firmware metadata.
The tool issues only diagnostic ADB commands; it does not request root, reboot,
unlock or write to the phone. ADB may start its normal host-side server.
