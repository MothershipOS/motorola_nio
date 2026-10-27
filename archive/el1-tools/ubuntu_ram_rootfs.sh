#!/bin/sh
# Re-create the Ubuntu 26.04 arm64 rootfs in phone RAM (/ub) after a reboot and install the GPU stack.
# Needs: phone up on USB-NCM, tools/nio-el2/proxy.py running on the host (10.42.0.1:3128).
# Progress streams to the UART monitor (el2-debug/uart/live.log) via nsh.py.
set -eu
R=$(cd "$(dirname "$0")/../.." && pwd); N=$R/tools/nio-el2/nsh.py
T=ubuntu-base-26.04.1-base-arm64.tar.gz; PORT=$((8100 + $$ % 800))
[ -f "$R/rootfs/dl/$T" ] || curl -sL -o "$R/rootfs/dl/$T" https://cdimage.ubuntu.com/ubuntu-base/releases/26.04/release/$T
(cd "$R/rootfs/dl" && exec python3 -m http.server $PORT --bind 10.42.0.1 >/dev/null 2>&1) & HP=$!; trap 'kill $HP' EXIT; sleep 1
$N "date -u -s '$(date -u '+%Y-%m-%d %H:%M:%S')' >/dev/null
mountpoint -q /ub || { mkdir -p /ub && mount -t tmpfs -o size=5G tmpfs /ub && cd /ub && wget -q -O- http://10.42.0.1:$PORT/$T | tar xz && for m in proc sys dev dev/pts; do mount --bind /\$m /ub/\$m; done; }
echo 'Acquire::http::Proxy \"http://10.42.0.1:3128\";' > /ub/etc/apt/apt.conf.d/90proxy
chroot /ub /bin/bash -c 'export DEBIAN_FRONTEND=noninteractive; apt-get update -q && apt-get install -y --no-install-recommends -o Dpkg::Progress-Fancy=0 mesa-utils mesa-vulkan-drivers libgl1-mesa-dri libegl1 vulkan-tools glmark2-es2-drm kmscube'" 1200
