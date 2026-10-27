#!/bin/sh
# S13: Android panel off; GPU runtime suspend prevented
exec /usr/local/sbin/mship-power-test android --seconds 1800 --settle 300 --runtime-device gpu --runtime-control on "$@"
