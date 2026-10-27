#!/bin/sh
# S15: Idle camera ISP (CAMSS) normal runtime PM
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
