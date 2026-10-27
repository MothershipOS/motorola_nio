#!/bin/sh
# S14: Wi-Fi radio disabled
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 --wifi-radio off "$@"
