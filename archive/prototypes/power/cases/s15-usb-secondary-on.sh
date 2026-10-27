#!/bin/sh
# S15: Original secondary USB controller power policy
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
