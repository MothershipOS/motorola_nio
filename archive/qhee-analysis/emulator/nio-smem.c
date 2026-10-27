/* SPDX-License-Identifier: GPL-2.0-or-later
 * Sparse snapshot of nio SMEM metadata. Uncaptured bytes and writes abort
 * unless explicitly covered by the version/RLOCK/mutex model properties.
 * The entire reserved region overlays virt RAM so holes cannot read as zero.
 */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "qapi/error.h"
#include "hw/qdev-core.h"
#include "hw/qdev-properties.h"
#include "exec/address-spaces.h"
#include "exec/memory.h"

#define TYPE_NIO_SMEM "nio-smem"
#define SMEM_BASE UINT64_C(0x80900000)
#define SMEM_SIZE 0x200000
OBJECT_DECLARE_SIMPLE_TYPE(NioSmem, NIO_SMEM)

struct NioSmem {
    DeviceState parent_obj;
    MemoryRegion regs, memory, mutex;
    char *snapshot;
    uint8_t *blob, *data, *valid;
    uint64_t pointer;
    bool version_write;
    bool rlock_zero;
    bool mutex_model;
    bool ram_table_write;
    uint32_t mutex_owner;
};

static MemTxResult pointer_read(void *opaque, hwaddr off, uint64_t *value,
                               unsigned size, MemTxAttrs attrs)
{
    NioSmem *s = opaque;
    if (size != 4 || (off != 0 && off != 4)) {
        return MEMTX_ERROR;
    }
    *value = (s->pointer >> (off * 8)) & 0xffffffff;
    fprintf(stderr, "NIO_SMEM_POINTER address=0x%08" HWADDR_PRIx " value=0x%08" PRIx64 "\n",
            0x1fd4000 + off, *value);
    return MEMTX_OK;
}

static MemTxResult pointer_write(void *opaque, hwaddr off, uint64_t value,
                                unsigned size, MemTxAttrs attrs)
{
    fprintf(stderr, "NIO_SMEM_DENIED pointer-write offset=0x%" HWADDR_PRIx " size=%u\n", off, size);
    return MEMTX_ERROR;
}

static MemTxResult smem_read(void *opaque, hwaddr off, uint64_t *value,
                            unsigned size, MemTxAttrs attrs)
{
    NioSmem *s = opaque;
    unsigned i;
    if (off >= SMEM_SIZE || size > SMEM_SIZE - off) {
        return MEMTX_ERROR;
    }
    for (i = 0; i < size; i++) {
        if (!s->valid[off+i]) {
            fprintf(stderr, "NIO_SMEM_DENIED read address=0x%08" PRIx64 " size=%u\n",
                    SMEM_BASE + off, size);
            return MEMTX_ERROR;
        }
    }
    *value = 0;
    for (i = 0; i < size; i++) {
        *value |= (uint64_t)s->data[off+i] << (8*i);
    }
    return MEMTX_OK;
}

static MemTxResult smem_write(void *opaque, hwaddr off, uint64_t value,
                             unsigned size, MemTxAttrs attrs)
{
    NioSmem *s = opaque;
    /* Observed QHEE initialization publishes its version in header.version[0]. */
    if (s->version_write && off == 0x40 && size == 4 &&
        s->valid[0x40] && s->valid[0x41] && s->valid[0x42] && s->valid[0x43]) {
        stl_le_p(s->data+off, value);
        fprintf(stderr, "NIO_SMEM_VERSION_WRITE value=0x%08" PRIx64 "\n", value);
        return MEMTX_OK;
    }
    if (s->rlock_zero && off >= 0x51b0 && off < 0x71b0 && size <= 0x71b0-off) {
        for (unsigned i = 0; i < size; i++) {
            s->data[off+i] = value >> (8*i);
        }
        return MEMTX_OK;
    }
    if (s->ram_table_write && off >= 0x11a88 && off < 0x123a0 && size <= 0x123a0-off) {
        for (unsigned i = 0; i < size; i++) {
            s->data[off+i] = value >> (8*i);
        }
        fprintf(stderr, "NIO_SMEM_RAM_TABLE_WRITE address=0x%08" PRIx64 " size=%u value=0x%" PRIx64 "\n",
                SMEM_BASE+off, size, value);
        return MEMTX_OK;
    }
    fprintf(stderr, "NIO_SMEM_DENIED write address=0x%08" PRIx64 " size=%u value=0x%" PRIx64 "\n",
            SMEM_BASE + off, size, value);
    return MEMTX_ERROR;
}

static const MemoryRegionOps pointer_ops = {
    .read_with_attrs = pointer_read, .write_with_attrs = pointer_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4, .unaligned = false },
    .impl = { .min_access_size = 4, .max_access_size = 4 },
};

static const MemoryRegionOps smem_ops = {
    .read_with_attrs = smem_read, .write_with_attrs = smem_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 8, .unaligned = true },
    .impl = { .min_access_size = 1, .max_access_size = 8, .unaligned = true },
};

static MemTxResult mutex_read(void *opaque, hwaddr off, uint64_t *value,
                             unsigned size, MemTxAttrs attrs)
{
    NioSmem *s = opaque;
    if (off || size != 4) {
        return MEMTX_ERROR;
    }
    *value = s->mutex_owner;
    return MEMTX_OK;
}

static MemTxResult mutex_write(void *opaque, hwaddr off, uint64_t value,
                              unsigned size, MemTxAttrs attrs)
{
    NioSmem *s = opaque;
    if (off || size != 4 || value > 255) {
        return MEMTX_ERROR;
    }
    if (!value || !s->mutex_owner) {
        s->mutex_owner = value;
    }
    fprintf(stderr, "NIO_SMEM_MUTEX write=%" PRIu64 " owner=%u\n", value, s->mutex_owner);
    return MEMTX_OK;
}

static const MemoryRegionOps mutex_ops = {
    .read_with_attrs = mutex_read, .write_with_attrs = mutex_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4, .unaligned = false },
    .impl = { .min_access_size = 4, .max_access_size = 4 },
};

static void nio_realize(DeviceState *dev, Error **errp)
{
    NioSmem *s = NIO_SMEM(dev);
    gsize len;
    GError *error = NULL;
    if (!s->snapshot || !g_file_get_contents(s->snapshot, (char **)&s->blob, &len, &error)) {
        error_setg(errp, "nio-smem: snapshot required: %s", error ? error->message : "missing property");
        g_clear_error(&error);
        return;
    }
    if (len != 24 + 2*SMEM_SIZE || memcmp(s->blob, "NIOSMEM1", 8) ||
        (uint32_t)ldl_le_p(s->blob+16) != SMEM_BASE || ldl_le_p(s->blob+20) != SMEM_SIZE) {
        error_setg(errp, "nio-smem: invalid snapshot header/length");
        return;
    }
    s->pointer = ldq_le_p(s->blob+8);
    if (s->pointer < SMEM_BASE || s->pointer > SMEM_BASE+SMEM_SIZE-24) {
        error_setg(errp, "nio-smem: target pointer outside reservation");
        return;
    }
    s->data = s->blob + 24;
    s->valid = s->data + SMEM_SIZE;
    for (unsigned i = 0; i < SMEM_SIZE; i++) {
        if (s->valid[i] > 1) {
            error_setg(errp, "nio-smem: invalid capture mask");
            return;
        }
    }
    if (s->rlock_zero) {
        for (unsigned i = 0x51a0; i < 0x51b0; i++) {
            if (!s->valid[i]) {
                error_setg(errp, "nio-smem: RLOCK requires captured item 404 header");
                return;
            }
        }
        if (lduw_le_p(s->data+0x51a0) != 0xa5a5 || lduw_le_p(s->data+0x51a2) != 404 ||
            ldl_le_p(s->data+0x51a4) != 0x2000) {
            error_setg(errp, "nio-smem: RLOCK header mismatch");
            return;
        }
        memset(s->data+0x51b0, 0, 0x2000);
        memset(s->valid+0x51b0, 1, 0x2000);
        fprintf(stderr, "NIO_SMEM_RLOCK_ZERO address=0x809051b0 size=0x2000 single-CPU model assumption\n");
    }
    if (s->ram_table_write) {
        for (unsigned i = 0x11a78; i < 0x123a0; i++) {
            if (!s->valid[i]) {
                error_setg(errp, "nio-smem: RAM table writes require captured item 402 and its header");
                return;
            }
        }
        if (lduw_le_p(s->data+0x11a78) != 0xa5a5 || lduw_le_p(s->data+0x11a7a) != 402 ||
            ldl_le_p(s->data+0x11a7c) != 0x918) {
            error_setg(errp, "nio-smem: RAM table header mismatch");
            return;
        }
    }
    memory_region_init_io(&s->regs, OBJECT(dev), &pointer_ops, s, "nio-smem-pointer", 8);
    memory_region_add_subregion(get_system_memory(), 0x1fd4000, &s->regs);
    memory_region_init_io(&s->memory, OBJECT(dev), &smem_ops, s, "nio-smem-snapshot", SMEM_SIZE);
    memory_region_add_subregion_overlap(get_system_memory(), SMEM_BASE, &s->memory, 1);
    if (s->mutex_model) {
        memory_region_init_io(&s->mutex, OBJECT(dev), &mutex_ops, s, "nio-smem-mutex9", 4);
        memory_region_add_subregion(get_system_memory(), 0x1f49000, &s->mutex);
        fprintf(stderr, "NIO_SMEM_MUTEX_INIT index=9 owner=0 model assumption\n");
    }
}

static void nio_finalize(Object *obj)
{
    g_free(NIO_SMEM(obj)->blob);
}

static Property nio_properties[] = {
    DEFINE_PROP_STRING("snapshot", NioSmem, snapshot),
    DEFINE_PROP_BOOL("version-write", NioSmem, version_write, false),
    DEFINE_PROP_BOOL("rlock-zero", NioSmem, rlock_zero, false),
    DEFINE_PROP_BOOL("mutex-model", NioSmem, mutex_model, false),
    DEFINE_PROP_BOOL("ram-table-write", NioSmem, ram_table_write, false),
    DEFINE_PROP_END_OF_LIST(),
};

static void nio_class_init(ObjectClass *oc, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(oc);
    dc->desc = "Nio SMEM metadata snapshot with holes that abort";
    dc->realize = nio_realize;
    dc->hotpluggable = false;
    device_class_set_props(dc, nio_properties);
}

static const TypeInfo nio_info = {
    .name = TYPE_NIO_SMEM, .parent = TYPE_DEVICE,
    .instance_size = sizeof(NioSmem), .class_init = nio_class_init,
    .instance_finalize = nio_finalize,
};

static void nio_register_types(void)
{
    type_register_static(&nio_info);
}
type_init(nio_register_types)
