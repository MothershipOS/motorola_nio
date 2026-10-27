#!/bin/sh
# S04: Existing powersave profile
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 --profile powersave "$@"
