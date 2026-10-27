#!/bin/sh
# S15: Idle camera ISP (CAMSS) runtime suspend prevented
exec /usr/local/sbin/mship-power-test host --seconds 1800 --settle 300 --runtime-device camss --runtime-control on "$@"
