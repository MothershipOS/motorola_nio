#!/bin/sh
# S17: USB SSH upload at 1 MiB/s
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
