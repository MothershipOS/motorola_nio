#!/bin/sh
# S04: Existing balanced profile
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
