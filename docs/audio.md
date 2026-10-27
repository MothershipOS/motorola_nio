# Audio: ADSP at EL2, speaker (AW882xx), speaker protection

> Bring-up log moved from the old PORT-NOTES diary (2026-10-08..12); dated entries are as written then.
> Paths were updated to the current repo layout.

## Audio: ADSP bring-up at EL2 (2026-10-12) - WORKING (built-in speaker)
**Resolved later on 2026-10-12** (FIT `nio-el2-audio.itb`, kernel #31, patch 0016). Root cause: on stock,
QHEE (not TZ) starts the LPASS Q6. QHEE's `pil_auth_reset_api_ns` runs PILSubsys_memAssign -> TZ auth
(envAuthReset) -> PILSubsys_bringUp; TZ's auth_and_reset only authenticates and leaves the core stopped,
hence "auth=0, ready=-110, zero IRQs". Found in the stock hyp binary (kernel-work/out/qhee-pil-empty/hyp-code.bin,
load 0x80040000): subsystem table @0x80095b98 (entry id 1 = ADSP) -> bring_up 0x8004f200 / tear_down 0x8004f288 /
mem_assign 0x8004f2cc; LPASS clock helpers ClockSetup(0)=0x80063eb8, ClockEnable(0)=0x80064b7c, ClockReset(0)=0x80064d20,
boot vector 0x8004f610. MMIO sequence recovered with a unicorn trace (same as mainline qcom_q6v5_adsp sc7280 adsp_start):
LPASS AON CBCRs 0x0338901c/0x03389020, 0x03383090, 0x03c04000, Q6SS XO/SLEEP/CORE CBCR (+0x38/+0x3c/+0x20), memories
0x03555014..20, 0x03c08000; RST_EVB(+0x10)=carveout>>4, efuse 0x0355b000 bit0=0; CORE_START(+0x400)=1, BOOT_CMD(+0x404)=1,
poll BOOT_STATUS(+0x408). Four things replace QHEE, all needed:
1. qcom_q6v5_pas: the LPASS bring-up after auth_and_reset (EL2, pas 1). Boot vector = mem_phys 0x8a100000, NOT
   mem_reloc (0x89500000 = ELF link address; Q6 executing there reset the SoC). Guarded: only runs when 2.+3. are in the DT.
2. apps SMMU: the Q6 fetches as SID 0x1800 (GFSYNR1=0x1800 seen). Blocked unmatched stream -> SoC reset within ~250 ms.
   Fix: `iommus = <apps_smmu 0x1800 0>` on remoteproc@17300000 + qcom,sm8250-adsp-pas in arm-smmu-qcom's identity
   client list (precedent: sc7280/sdm845 mss-pil). (Runtime test used sCR0.USFCFG=0; not used now.)
3. CMD-DB HLOS+ADSP RO shared *before* SHM bridge enable (`mothership,el2-cmdb-share-adsp` on /firmware/scm). After
   bridge enable TZ rejects it (-6/TZ30), and a kexec keeps the bridge enabled -> needs a cold boot to test.
4. SMEM ADSP<->SLPI partition 0x80a73000+0xc000 (HLOS R, ADSP RW, SLPI RW) enabled in el2-mem-assign (5 regions).
Sound: DT nodes in nio-el2-display.dts (AW882xx speaker@34 on i2c15, TERT_MI2S pins gpio133/135/137, AFE dai@20 sd-lines 1,
ASM dai@0, sm8250-sndcard "mothership-nio-speaker"; FE link before BE link or q6routing probes before q6asm-dai -> card -19).
Runtime overlays must be applied *before* the ADSP starts (else new DAI devices get the wrong parent -> q6afe NULL oops).
Userspace: aw882xx_nio.ko in /lib/modules/.../extra; UCM motorola_nio/rootfs/audio/ucm2 (needs alsa-ucm-conf; without
it PipeWire's fallback profile is "unavailable" because of the card's unused Headset Jack); default sink "Built-in Audio
Speaker". Verified: amp SYSST 0x4800->0x0811 (PLL lock + switching), SYSCTRL PWDN/HMUTE cleared during playback, from cold boot.
Amp gain stays fixed at -36 dB (no ADSP speaker protection yet). Not done: headset/mics (WCD938x/SoundWire/macros),
ADSP stop/restart path (QHEE tear_down = ClockReset(0) not ported; pas_shutdown only), CDSP/SLPI.
Old PAS module: /root/qcom_q6v5_pas.ko.pre-audio on the phone. kexec-tools installed (no reboot hook).

### History before the fix
- Hardware (stock DT): speaker = Awinic AW882xx smart PA, i2c15 (i2c@884000) addr 0x34, chip ID 0x1852 (no
  mainline driver; Motorola GPL driver in kernel-work/reference/aw882xx, reg config aw882xx_spk_reg.bin from
  vendor_a /firmware, saved in motorola_nio/firmware/nio-audio with mixer_paths.xml), reset tlmm 139, irq tlmm 138, fed by
  ADSP AFE TERTIARY_MI2S_RX (0x1004) / TX 0x1005 (I/V feedback). Headset/mics: WCD938x over SoundWire + LPASS
  rx/tx/va macros. Kernel config already has q6 APR stack, SM8250 sound card, WCD938x, LPASS macros, PD mapper.
- ADSP: stock /image/adsp.mdt+b00-b18 (motorola_nio/firmware/nio-adsp -> /lib/firmware/qcom/sm8250/nio). Enabled
  remoteproc@17300000 (nio-el2-display.dts, FIT nio-el2-adsp.itb). TZ PAS init+auth_and_reset SUCCEED (EL2 SHM
  bridge over the 0x8a100000/29 MiB carve-out) but the DSP never signals: start timed out, zero wdog/smp2p IRQs,
  no SMMU faults.
- MEM_ASSIGN blocker resolved: TZ uses x7 to select buffer-validation identity. Linux x7=0
  returned raw -6; x7=HLOS(3) succeeded on a disposable page with restoration. Patch 0011
  changes only EL2 MEM_ASSIGN identity. Patch 0012 records the boot/on-demand SMEM sharing code.
- Current FIT nio-el2-audio-smem.itb (#25): only four early SMEM regions are active (TOC,
  ADSP partition, global, header), all assign successfully. CMD-DB/other regions are disabled.
  ADSP still times out, with no inbound SMP2P handshake; PAS caller/metadata alternatives were reverted.
- Explicitly approved offline ADSP reservation probe: 0x8a100000 + 0x1d00000 HLOS ->
  HLOS+ADSP RW succeeded, immediate HLOS RWX restoration succeeded. ADSP stayed offline.
  First probe had a NULL lookup Oops before any memory call; fixed and rebooted before the passing test.
- Direct Q6 MMIO sampling reset the phone; it recovered. Do not repeat. SCM reads returned -EINVAL.
- ALSA/PipeWire/Pulse/WirePlumber installed and persistent; mship-sway environment configured.
  VM Ubuntu Touch launcher uses QEMU PipeWire. Backend connection passed, but only Dummy Output
  exists: no ALSA sound card, no physical or guest playback verified.
- Approved bounded startup tests (patch 0013): HLOS and genuine HYP image assignments succeed;
  authentication succeeds; ready remains -110. All image restorations and shutdowns succeed.
  During the wait LCX/LMX are active; no incoming SMEM/ready/fatal event is observed.
- Genuine HYP descriptor validation solved on private pages: share private descriptor with
  HLOS+HYP and register an NS VMID4 SHM bridge. x7=0 target assignment then succeeds. Private
  target/descriptor restorations and bridge deletion all succeed. No global switch deployed.
- Approved CMD-DB diagnostics: HLOS+ADSP RO assignment returns TZ30; temporary HLOS+secure RO
  registration returns68. No successful CMD-DB assignment/registration occurred. Static TZ
  analysis connects the destination restriction to the SHM mode flag, motivating a pre-enable
  share/restore test. Patch 0014 / FIT nio-el2-cmdb-order-test.itb (#26) was later booted, as were #27-#29 (see report).
- AW882xx 0x1852 bring-up component: motorola_nio/kernel/drivers/aw882xx_nio.c physically binds I2C15@0x34.
  Stock register profile and efuse calibration applied; measured SYSCTRL4441 (PWDN), SYSCTRL2
  0038 (HMUTE), volume6064 (-36 dB), calibration2112. No speaker playback yet; proprietary
  speaker-protection integration and monitoring remain unfinished. Do not raise gain.
- Reversible runtime motorola_nio/kernel/dts/overlays/nio-speaker.dts describes MultiMedia1 -> q6routing ->
  TERTIARY_MI2S RX SD1 (GPIO133/135/137) -> amp. Sound card defers awaiting Q6 services.
  Runtime module/overlay changes are not autoloaded. Linux boot_b/hyp_b remain unchanged this turn.
- Full evidence and approval scopes: reports/nio-audio-20261012/README.md. No broad multi-VMID
  CMD-DB experiment was run. Physical built-in speaker playback remains the completion gate.

## Report 2026-10-12 (from reports/nio-audio-20261012, local only)


### Update (afternoon): built-in speaker WORKS

Boot image `motorola_nio/boot/nio-el2-audio.itb` (kernel #31, sha256 1f08ab2c…) on boot_b. The ADSP starts at
boot, ALSA card `mothership-nio-speaker` appears, PipeWire default sink "Built-in Audio Speaker" plays
(AW882xx SYSST 0x0811 = PLL locked + switching during playback; verified after a cold boot).
Cause: QHEE, not TZ, released the LPASS Q6 (`pil_auth_reset_api_ns` → memAssign → TZ auth → bringUp).
Fix = patch `motorola_nio/kernel/patches/0016-nio-adsp-el2-lpass-bringup.patch` + DT in `nio-el2-display.dts`;
details in PORT-NOTES "Audio". Backups of the pre-change sources are in this folder
(`*.before-lpass-bringup.c`, `*.before-adsp-identity.c`, `*.before-cmdline-cmdb.c`, `nio-el2-display.before-audio.dts`).
Build log: `audio-kernel-build.log`. Rollback: deploy `nio-el2-audio-smem.itb` (#25); the new PAS module refuses
to start the Q6 on images without the SMMU/CMD-DB prerequisites, so rollback stays safe.

### Earlier status (morning)

**Built-in speaker playback was not working yet at this point.** Linux/KVM, the host desktop,
Wi-Fi and Bluetooth remain available. The current boot uses the tested
`nio-el2-audio-smem.itb` (#25), with narrow MEM_ASSIGN caller-identity repair and
only four early SMEM sharing requests. No changed hyp firmware was flashed.

### Measured progress

- A disposable page call with x7=0 returned raw TZ -6. x7=3 succeeded and the
  page was restored to HLOS. The secure decoder rejects extended argument
  buffers under its HYP-buffer rule; x7 supplies the HLOS forwarding identity.
- Patch 0011 sets x7=HLOS only for MEM_ASSIGN on an EL2 host. Patch 0012 records
  the earlier on-demand/boot-time SMEM sharing code that was previously local.
- Latest physical boot: four SMEM assignments succeed, zero fail; KVM VHE still
  initializes. ADSP firmware authentication is accepted but ready times out.
- PAS identity and non-bridge metadata variants did not fix startup; these
  changes were reverted. ADSP publishes no inbound SMP2P entry/crash record.
- A direct Q6 MMIO sample reset the phone; it recovered automatically. Do not
  repeat it. SCM-mediated register reads return -EINVAL, not register values.
- Private-buffer tests did not make HYP-mode calls work. An exclusive-buffer
  test retained its allocations after restoration failed; the subsequent reboot
  cleared that experiment. None of those modules are installed/autoloaded.
- ALSA utilities, PipeWire, Pulse compatibility, WirePlumber and Bluetooth SPA
  were installed. Services run persistently as mship. Its audio-group membership
  and sway audio-server environment are configured. PipeWire currently has only
  Dummy Output, so service health is **not audible playback validation**.
- The VM launcher now uses QEMU's native PipeWire backend instead of silent
  `none`; MSHIP_VM_AUDIO=none remains a debug option. A paused QEMU backend
  connection probe is recorded separately; no actual guest playback is claimed.

### Approved guarded image test — passed

The user explicitly approved the isolated 29 MiB test. The first invocation
hit a NULL remoteproc lookup before any ownership call; the phone remained
responsive and was rebooted. The corrected lookup pins the exact PAS driver,
checks its matching kernel-private prefix and device parent, and locks remoteproc.

The corrected physical test returned:
- share: 0, owners 0x48 (HLOS + ADSP RW)
- immediate restore: 0, owners 0x8 (HLOS RWX only)
- ADSP state: offline; no new Oops or reset during the corrected test.

Evidence: `approved-image-probe-fixed.txt`; exact code/module hashes and approval
in `proposed-image-probe.json`. The module deliberately returns -EAGAIN after the
test, so insmod's “Resource temporarily unavailable” is expected.

### Bounded startup tests — approved and executed

Patch 0013 records the disabled, root-controlled diagnostic PAS driver. The user
approved image startup tests, further bounded repetitions, narrow CMD-DB RO
sharing and temporary CMD-DB RO registration. Physical outcomes and remaining
cold-boot experiment are below. Every accepted ADSP image assignment was restored;
CMD-DB sharing and registration were rejected before any successful change.

### Continued implementation and physical results

- The user approved further bounded ADSP tests, narrow CMD-DB RO tests, and
  temporary CMD-DB RO SHM registration. Earlier automatic-review blocks were
  resolved by those approvals; the full multi-VMID CMD-DB operation remains unrun.
- During the bounded startup wait LCX and LMX are active. No ready/fatal/handshake
  interrupt occurs and no incoming SMEM item appears. HLOS startup: share0,
  auth0, ready-110, shutdown0, restore0 (`image-start-live-status.txt`).
- Private VMID4 SHM registration fixes genuine HYP x7=0 descriptor validation:
  private data assignment, restoration, bridge deletion and descriptor restoration
  all succeed (`hyp-shm-probe.txt`). A HYP image startup variant still times out;
  shutdown, image restoration, descriptor restorations and bridge deletions succeed.
- CMD-DB HYP share to only HLOS+ADSP RO returns TZ30; no accepted target assignment.
  Temporary HLOS+secure RO registration returns68; no bridge was created. Both
  tests stop before releasing DSP reset. Exact evidence in `cmdb-guarded-start-result.txt`
  and `cmdb-bridge-result.txt`. The CMD-DB state was unchanged by these rejected calls.
- Static TZ handler analysis links the class/destination restriction to the SHM
  mode flag; the flag is set in the enable handler. Early versus late ordering is
  an inference, pending physical validation. A cold-boot diagnostic image #26 is
  compiled: `nio-el2-cmdb-order-test.itb`, approval pending; manifest in
  `proposed-cmdb-order-boot.json`. It immediately restores after the early RO share.
- Read-only TZ diagnostic ring snapshot collected using stock driver mapping;
  there is no directly decoded DSP boot error. No new Q6 MMIO reads attempted.
- New `motorola_nio/kernel/drivers/aw882xx_nio.c` bring-up component compiles and physically binds
  on I2C15 address0x34, identifying chip0x1852 and applying the stock 144-byte profile
  with efuse calibration. It remains muted/powered down, fixed -36 dB gain for any
  future playback. Proprietary ADSP speaker protection and monitoring are not yet
  integrated: do not increase gain. This is a bring-up component, not production-ready.
- Reversible runtime `motorola_nio/kernel/dts/overlays/nio-speaker.dts` adds the TERTIARY_MI2S RX
  SD1 GPIO133/135/137 route and MultiMedia1 front end. Linux live-overlay phandle
  caching prevented references to existing new-provider phandles; replacement
  child nodes resolved that. Sound card correctly defers awaiting Q6 services.
  Review initially blocked replacement; read-only proof of offline DSP and absent
  APR/Q6 devices allowed the safer retry. No DSP service was running during the change.
- Runtime test drivers/overlays are not installed for automatic boot. Reboot uses
  the installed original PAS driver and clears the temporary speaker description.
  Audio userspace configuration and QEMU backend changes remain persistent.

**Completion gate remains physical speaker playback.** The amplifier now responds;
ADSP readiness and the resulting PCM/card availability are still blockers.
