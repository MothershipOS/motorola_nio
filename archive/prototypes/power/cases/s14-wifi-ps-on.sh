#!/bin/sh
# S14: Wi-Fi associated, power save on
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 --wifi-power-save on "$@"
