Out-of-tree drivers for the nio host kernel: `cargo xtask host-kernel` builds every `*.c` here as its own module
(headers beside them) into the release's `extra/`.

| Module | Source |
|---|---|
| `aw882xx_nio` | mothershipOS: the Awinic speaker amplifiers |
| `v4l2loopback` | upstream v4l2loopback 0.15.3 as Ubuntu ships it (source package `v4l2loopback_0.15.3-1ubuntu2`, Debian patches applied), GPL-2.0. The cameras' processed frames for VMs (`mship.camera`). One change (marked mothershipOS): `VIDIOC_DQBUF` accepts `memory` 0 as MMAP, as vb2 drivers do (crosvm's V4L2 proxy dequeues that way) |

v4l2loopback files as shipped (sha256): `v4l2loopback.c` 33ff2c271c9676b7ae694a9202a50fc0acf73f41c7bb4e874722250fefe8320a,
`v4l2loopback.h` 8f07396a5432b191ed094b421dc756849ea0468a44b4ea6cef0afa9acd77e055,
`v4l2loopback_formats.h` cdabbb0c28f577590f6bba2eb2bb3d6fdb32b70fbc3e2b42abadf48b9cbc31d7.
