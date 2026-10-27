/* SPDX-License-Identifier: MIT
 * RAM-only diagnostic helper for the nio bring-up initramfs.
 *   nio-diag kvm            report KVM API and VM creation
 *   nio-diag reboot [MODE]  sync and restart; MODE (e.g. bootloader) goes to reboot-mode
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/kvm.h>
#include <linux/reboot.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>

static int kvm_probe(void)
{
    int kvm = open("/dev/kvm", O_RDWR | O_CLOEXEC);
    if (kvm < 0) {
        printf("KVM_OPEN_FAILED errno=%d (%s)\n", errno, strerror(errno));
        return 1;
    }
    int version = ioctl(kvm, KVM_GET_API_VERSION, 0);
    printf("KVM_API_VERSION=%d expected=%d\n", version, KVM_API_VERSION);
    if (version != KVM_API_VERSION)
        return 1;
    int vm = ioctl(kvm, KVM_CREATE_VM, 0UL);
    if (vm < 0) {
        printf("KVM_CREATE_VM_FAILED errno=%d (%s)\n", errno, strerror(errno));
        return 1;
    }
    printf("KVM_CREATE_VM_OK; guest execution remains untested\n");
    close(vm);
    close(kvm);
    return 0;
}

static int restart(const char *mode)
{
    sync();
    if (mode)
        syscall(SYS_reboot, LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2,
                LINUX_REBOOT_CMD_RESTART2, mode);
    else
        syscall(SYS_reboot, LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2,
                LINUX_REBOOT_CMD_RESTART, NULL);
    printf("REBOOT_FAILED errno=%d (%s)\n", errno, strerror(errno));
    return 1;
}

int main(int argc, char **argv)
{
    if (argc >= 2 && !strcmp(argv[1], "kvm"))
        return kvm_probe();
    if (argc >= 2 && !strcmp(argv[1], "reboot"))
        return restart(argc >= 3 ? argv[2] : NULL);
    fprintf(stderr, "usage: nio-diag kvm | reboot [MODE]\n");
    return 2;
}
