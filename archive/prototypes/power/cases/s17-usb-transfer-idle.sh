#!/bin/sh
# S17: USB data link idle after transfer
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
