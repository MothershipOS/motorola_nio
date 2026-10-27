#!/bin/sh
# S11: Normal power-key recovery polling
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 "$@"
