#!/bin/sh
# S17: USB development data link bound and idle
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
