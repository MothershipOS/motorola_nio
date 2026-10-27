#!/bin/sh
# S01/S07/S09: Android running, panel off, Doze disabled
exec /usr/local/sbin/mship-power-test android --seconds 1800 --settle 300 "$@"
