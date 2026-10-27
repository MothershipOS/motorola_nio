#!/bin/sh
# S15: Secondary USB controller automatic runtime PM
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 --runtime-device usb-secondary --runtime-control auto "$@"
