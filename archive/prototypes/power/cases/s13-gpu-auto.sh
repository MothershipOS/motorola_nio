#!/bin/sh
# S13: GPU normal runtime PM
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
