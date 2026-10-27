/* Exact captured regions; ownership contracts checked against original QHEE requests. */
smem_partition_ledger:
    .quad 0x80acf000, 0x30000, 0x48, 0x48
    .quad smem_partition_dest_0, 48, 8, 0
    .quad 0x80aaf000, 0x20000, 0x40000008, 0x40000008
    .quad smem_partition_dest_1, 48, 8, 0
    .quad 0x80a7f000, 0x30000, 0x28, 0x28
    .quad smem_partition_dest_2, 48, 8, 0
    .quad 0x80a73000, 0xc000, 0x68, 0x60
    .quad smem_partition_dest_3, 72, 8, 0
    .quad 0x80a6b000, 0x8000, 0x8000008, 0x8000008
    .quad smem_partition_dest_4, 48, 8, 0
    .quad 0x80a67000, 0x4000, 0x400000a, 0x4000002
    .quad smem_partition_dest_5, 72, 8, 0
    .quad 0x80a57000, 0x10000, 0x10000000008, 0x10000000008
    .quad smem_partition_dest_6, 48, 8, 0
    .quad 0x80a47000, 0x10000, 0x10040000008, 0x10040000000
    .quad smem_partition_dest_7, 72, 8, 0
    .quad 0x80901000, 0x146000, 0x1004c000078, 0x1004c000078
    .quad smem_partition_dest_8, 192, 8, 0
    .quad 0x80900000, 0x1000, 0x1004c000078, 0x1004c000078
    .quad smem_partition_dest_9, 192, 8, 0
smem_partition_dest_0:
    .long 3, 6
    .quad 0
    .long 0, 0
    .long 6, 6
    .quad 0
    .long 0, 0
smem_partition_dest_1:
    .long 3, 6
    .quad 0
    .long 0, 0
    .long 30, 6
    .quad 0
    .long 0, 0
smem_partition_dest_2:
    .long 3, 6
    .quad 0
    .long 0, 0
    .long 5, 6
    .quad 0
    .long 0, 0
smem_partition_dest_3:
    .long 3, 4
    .quad 0
    .long 0, 0
    .long 6, 6
    .quad 0
    .long 0, 0
    .long 5, 6
    .quad 0
    .long 0, 0
smem_partition_dest_4:
    .long 3, 6
    .quad 0
    .long 0, 0
    .long 27, 6
    .quad 0
    .long 0, 0
smem_partition_dest_5:
    .long 3, 4
    .quad 0
    .long 0, 0
    .long 1, 6
    .quad 0
    .long 0, 0
    .long 26, 6
    .quad 0
    .long 0, 0
smem_partition_dest_6:
    .long 3, 6
    .quad 0
    .long 0, 0
    .long 40, 6
    .quad 0
    .long 0, 0
smem_partition_dest_7:
    .long 3, 4
    .quad 0
    .long 0, 0
    .long 30, 6
    .quad 0
    .long 0, 0
    .long 40, 6
    .quad 0
    .long 0, 0
smem_partition_dest_8:
    .long 3, 6
    .quad 0
    .long 0, 0
    .long 6, 6
    .quad 0
    .long 0, 0
    .long 5, 6
    .quad 0
    .long 0, 0
    .long 30, 6
    .quad 0
    .long 0, 0
    .long 27, 6
    .quad 0
    .long 0, 0
    .long 4, 6
    .quad 0
    .long 0, 0
    .long 40, 6
    .quad 0
    .long 0, 0
    .long 26, 6
    .quad 0
    .long 0, 0
smem_partition_dest_9:
    .long 3, 6
    .quad 0
    .long 0, 0
    .long 6, 6
    .quad 0
    .long 0, 0
    .long 5, 6
    .quad 0
    .long 0, 0
    .long 30, 6
    .quad 0
    .long 0, 0
    .long 27, 6
    .quad 0
    .long 0, 0
    .long 4, 6
    .quad 0
    .long 0, 0
    .long 40, 6
    .quad 0
    .long 0, 0
    .long 26, 6
    .quad 0
    .long 0, 0
