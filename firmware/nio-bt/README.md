QCA6390 Bluetooth firmware for the nio host (/lib/firmware/qca): the stock pair from the bluetooth_a partition
(/image/htbtfw20.tlv = ROM patch, /image/htnv20.bin = nio NVM/RF config). linux-firmware's generic pair is kept
on the phone as *.linux-firmware. The phone's BD address (stock androidboot.btmacaddr) is set by the DT
property local-bd-address, from `boot/bd-address` (not in git).
