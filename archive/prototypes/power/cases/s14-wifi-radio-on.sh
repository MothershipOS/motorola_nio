#!/bin/sh
# S14: Wi-Fi radio enabled and associated
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
