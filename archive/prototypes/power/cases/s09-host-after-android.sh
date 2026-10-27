#!/bin/sh
# S09: Host only after clean Android shutdown
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
