#!/bin/sh
# S01/S02/S07: Android running with panel on; Doze disabled
exec /usr/local/sbin/mship-power-test android --seconds 1800 --settle 300 --screen on "$@"
