#!/bin/sh
# S13: Android panel off; GPU normal runtime PM
exec /usr/local/sbin/mship-power-test android --seconds 1800 --settle 300 "$@"
