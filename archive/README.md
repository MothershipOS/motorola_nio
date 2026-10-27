# motorola_nio/archive/: history, read-only

Kept for reference. Nothing here describes the current system; `docs/` and `motorola_nio/docs/` do.

| Dir | What |
|---|---|
| `qhee-analysis/` | offline analysis + emulation of Qualcomm's hypervisor (QHEE) and the XBL/TZ handoff, from when the plan was to patch QHEE. Still useful when a remote processor needs a QHEE-replacement (see `motorola_nio/docs/audio.md`) |
| `el2-debug/` | EL2 bring-up debugging before u-boot replaced QHEE: run logs, C shim, UART fault dumps, patched hyp images (untracked) |
| `el1-tools/` | tools for the stock ABL → Linux at EL1 path (`fastboot boot` diagnostics, SCM/SMEM captures, RAM rootfs) |
| `kvmtool-bringup/` | the A1 kvmtool guest (source and initrd untracked) |
| `docs/` | EL1 kernel README/STATUS, the hyp_b non-boot analysis, the userdata backup handoff, `stale-2026-10-08/` (QHEE-era plans and models) |

The full PORT-NOTES diary (2026-10-08..12) is in git history (`git log --all -- archive/docs/PORT-NOTES.md`). Its
content now lives in `motorola_nio/docs/`, `vms/ubuntu-touch/README.md` and `vms/docs/android-vm.md`.
