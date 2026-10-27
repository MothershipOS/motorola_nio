#!/bin/sh
# S11: Android panel off, forced deep Doze
exec /usr/local/sbin/mship-power-test doze --seconds 1800 --settle 300 "$@"
