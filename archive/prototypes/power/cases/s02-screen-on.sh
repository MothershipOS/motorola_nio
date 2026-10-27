#!/bin/sh
# S02: Panel on, existing brightness, touch delivery disabled
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 --screen on "$@"
