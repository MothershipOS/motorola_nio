#!/bin/sh
# S05: Original deeper CPU idle enabled
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
