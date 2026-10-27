#!/bin/sh
# A USB device for testing USB handles without a cable: dummy_hcd (virtual host controller + UDC) with a
# configfs mass-storage gadget (64 MiB backing file). The host sees it as a device plugged into a USB port.
# The real UDC (the dev link) is not touched.  usage (root): usb-test-device.sh up [dummy_hcd.ko] | down
set -e
G=/sys/kernel/config/usb_gadget/mship-test
IMG=/var/lib/mothership/usb-test.img
case "$1" in
up)
	[ -d /sys/class/udc/dummy_udc.0 ] || { [ -n "$2" ] && insmod "$2" || modprobe dummy_hcd; }
	# blank disk; FAT if dosfstools is installed
	[ -f "$IMG" ] || { truncate -s 64M "$IMG"; ! command -v mkfs.vfat >/dev/null || mkfs.vfat -n MSHIPTEST "$IMG" >/dev/null; }
	mkdir -p $G && cd $G
	echo 0x1d6b > idVendor; echo 0x0104 > idProduct	# Linux Foundation multifunction composite gadget
	mkdir -p strings/0x409 configs/c.1/strings/0x409 functions/mass_storage.0
	echo mothershipOS > strings/0x409/manufacturer; echo "mship test disk" > strings/0x409/product
	echo 0001 > strings/0x409/serialnumber; echo storage > configs/c.1/strings/0x409/configuration
	echo "$IMG" > functions/mass_storage.0/lun.0/file
	[ -e configs/c.1/mass_storage.0 ] || ln -s functions/mass_storage.0 configs/c.1/
	echo dummy_udc.0 > UDC
	;;
down)
	[ -d $G ] || exit 0
	cd $G; echo "" > UDC 2>/dev/null || true
	rm -f configs/c.1/mass_storage.0; rmdir configs/c.1/strings/0x409 configs/c.1 functions/mass_storage.0 strings/0x409
	cd /; rmdir $G
	;;
*) echo "usage: $0 up [dummy_hcd.ko] | down" >&2; exit 2 ;;
esac
