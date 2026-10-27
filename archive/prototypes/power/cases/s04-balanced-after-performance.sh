#!/bin/sh
# S04: Balanced profile after performance
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
