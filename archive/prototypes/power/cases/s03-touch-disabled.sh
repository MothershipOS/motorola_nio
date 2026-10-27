#!/bin/sh
# S03: Touch delivery disabled, panel off
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
