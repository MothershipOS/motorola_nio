#!/bin/sh
# S04: Fixed minimum CPU caps
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 --profile minimum "$@"
