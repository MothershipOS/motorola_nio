#!/bin/sh
# S11: Power-key recovery polling paused; host awake, USB connected
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 --pause-pwrkey-poll "$@"
