#!/bin/sh
# S05: WFI-only CPU idle
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 --deep-idle wfi-only "$@"
