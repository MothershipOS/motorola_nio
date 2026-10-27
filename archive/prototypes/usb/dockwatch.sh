#!/bin/sh
# log Type-C / DP / USB state changes while a dock or monitor is tested (read over Wi-Fi ssh)
P=/sys/class/typec/port0
prev=""
while true; do
	s="roles=$(cat $P/data_role 2>/dev/null | tr -d '\n')|$(cat $P/power_role 2>/dev/null | tr -d '\n') orient=$(cat $P/orientation 2>/dev/null)"
	s="$s partner=$([ -d ${P}-partner ] && echo yes || echo no) pd=$(cat ${P}-partner/supports_usb_power_delivery 2>/dev/null)"
	s="$s idhdr=$(cat ${P}-partner/identity/id_header 2>/dev/null)"
	s="$s altmodes=$(for a in ${P}-partner/${P##*/}-partner.*; do [ -d $a ] && echo -n "$(cat $a/svid 2>/dev/null):$(cat $a/active 2>/dev/null) "; done)"
	s="$s dp=$(cat /sys/class/drm/card1-DP-1/status 2>/dev/null) dpmodes=$(head -1 /sys/class/drm/card1-DP-1/modes 2>/dev/null)"
	s="$s usbdevs=$(ls /sys/bus/usb/devices 2>/dev/null | grep -c -E '^[0-9]+-[0-9.]+$') udc=$(ls /sys/class/udc | tr '\n' ',')"
	if [ "$s" != "$prev" ]; then echo "$(date +%T) $s"; prev=$s; fi
	sleep 2
done
