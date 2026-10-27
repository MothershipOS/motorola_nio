#!/bin/sh
# S18: Bluetooth normal radio state
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
