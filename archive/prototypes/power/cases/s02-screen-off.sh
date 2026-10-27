#!/bin/sh
# S02: Panel off, touch delivery disabled
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
