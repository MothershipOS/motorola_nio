#!/bin/sh
# S11: Android panel off, Doze disabled after Doze
exec /usr/local/sbin/mship-power-test android --seconds 1800 --settle 300 "$@"
