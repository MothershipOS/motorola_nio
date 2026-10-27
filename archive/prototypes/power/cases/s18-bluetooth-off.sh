#!/bin/sh
# S18: Bluetooth radio blocked
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 --bluetooth off "$@"
