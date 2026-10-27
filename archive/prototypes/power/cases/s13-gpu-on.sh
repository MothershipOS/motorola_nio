#!/bin/sh
# S13: GPU runtime suspend prevented
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 --runtime-device gpu --runtime-control on "$@"
