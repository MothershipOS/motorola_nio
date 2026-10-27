#!/bin/sh
# S15: UFS runtime suspend prevented
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 --runtime-device ufs --runtime-control on "$@"
