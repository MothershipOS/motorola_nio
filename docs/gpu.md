# GPU: Adreno 650 at EL2

> Bring-up log moved from the old PORT-NOTES diary (2026-10-08..12); dated entries are as written then.
> Paths were updated to the current repo layout.

### A4: Adreno 650 GPU runs at EL2 (2026-10-11)
- First open of /dev/dri/renderD128 (card0 = headless adreno; card1 = dpu/panel): a650_sqe.fw + a650_gmu.bin load
  (GMU fw v2.1.8), `gpu-initialized: 1`, RBBM idle.
- No `zap-shader` node in the DT -> msm logs "Zap shader not enabled - using SECVID_TRUST_CNTL instead" and writes
  RBBM_SECVID_TRUST_CNTL=0 itself. Without QHEE/hyp the GPU is not locked to secure mode, so the write sticks and
  no SCM/PAS call is needed for the GPU. (a650_zap.mbn is in /usr/lib/firmware/qcom/sm8250 if it is ever needed for
  secure content.) **The "secure world refuses GPU at EL2" risk does not apply.**
- Userspace: Ubuntu Mesa 26.0.8 freedreno, `FD650`, OpenGL ES 3.2. `kmscube -D /dev/dri/card1` renders on the GPU
  and scans out on the panel: 1786 retired GPU fences / 900 msm-kms irqs in 10 s = 90 fps at vsync, no faults/hangs.
- Gotcha: kmscube (legacy mode) treats readable stdin as "user interrupted!" — under non-interactive ssh run
  `sleep N | kmscube ...`.
- Open: GPU devfreq/OPP not tuned; cpufreq-hw still deferred (icc paths), so CPUs run at boot frequency.
