#!/bin/sh
# S17: USB gadget unbound; cable connected, USB power input suspended
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 --usb-data off "$@"
