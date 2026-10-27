/* SPDX-License-Identifier: GPL-2.0-or-later
 * Read-only replay of the single measured TZ_LOG_POINTER word used by QHEE.
 * The value is explicitly supplied by the caller. Optional exact one-shot
 * QHEE log publication is observed at firmware PC 0x80045954.
 * Separately opted-in SEC hold-flag replay permits one exact read only,
 * after both QHEE publications; postboot-to-entry equality is assumed.
 */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "hw/qdev-core.h"
#include "hw/qdev-properties.h"
#include "exec/address-spaces.h"
#include "exec/memory.h"

#define TYPE_NIO_TZ_LOG_POINTER "nio-tz-log-pointer"
OBJECT_DECLARE_SIMPLE_TYPE(NioTzLogPointer, NIO_TZ_LOG_POINTER)

struct NioTzLogPointer {
    DeviceState parent_obj;
    MemoryRegion reg;
    uint32_t value;
    bool publications;
    bool log_published;
    bool ready_publication;
    bool ready_published;
    bool sec_flag_replay;
    bool sec_flag_read;
    uint32_t sec_flag_value;
};

static MemTxResult nio_read(void *opaque, hwaddr offset, uint64_t *value,
                            unsigned size, MemTxAttrs attrs)
{
    NioTzLogPointer *s = opaque;
    if (s->sec_flag_replay && s->ready_published && !s->sec_flag_read &&
        offset == 0x944 && size == 4) {
        s->sec_flag_read = true;
        *value = s->sec_flag_value;
        fprintf(stderr, "NIO_SEC_FLAG_READ address=0x146bf944 value=0x%08x size=4\n", s->sec_flag_value);
        return MEMTX_OK;
    }
    if (offset != 0x720 || size != 4) {
        fprintf(stderr, "NIO_IMEM_DENIED read offset=0x%lx size=%u\n", (unsigned long)offset, size);
        return MEMTX_ERROR;
    }
    *value = s->value;
    fprintf(stderr, "NIO_TZ_LOG_POINTER_READ address=0x146bf720 value=0x%08x size=4\n", s->value);
    return MEMTX_OK;
}

static MemTxResult nio_write(void *opaque, hwaddr offset, uint64_t value,
                             unsigned size, MemTxAttrs attrs)
{
    NioTzLogPointer *s = opaque;
    if (s->publications && !s->log_published && offset == 0xb30 &&
        size == 8 && value == UINT64_C(0x200080209000)) {
        s->log_published = true;
        fprintf(stderr, "NIO_IMEM_HYP_LOG_PUBLISH address=0x146bfb30 value=0x200080209000 size=8\n");
        return MEMTX_OK;
    }
    if (s->ready_publication && s->log_published && !s->ready_published &&
        offset == 0xb20 && size == 8 && value == UINT64_C(0x800a5021)) {
        s->ready_published = true;
        fprintf(stderr, "NIO_IMEM_QHEE_READY_PUBLISH address=0x146bfb20 value=0x800a5021 size=8\n");
        return MEMTX_OK;
    }
    fprintf(stderr, "NIO_IMEM_DENIED write offset=0x%lx size=%u value=0x%lx\n", (unsigned long)offset, size, (unsigned long)value);
    return MEMTX_ERROR;
}

static const MemoryRegionOps nio_ops = {
    .read_with_attrs = nio_read,
    .write_with_attrs = nio_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 8, .unaligned = true },
    .impl = { .min_access_size = 4, .max_access_size = 8, .unaligned = true },
};

static void nio_realize(DeviceState *dev, Error **errp)
{
    NioTzLogPointer *s = NIO_TZ_LOG_POINTER(dev);
    memory_region_init_io(&s->reg, OBJECT(dev), &nio_ops, s,
                          TYPE_NIO_TZ_LOG_POINTER, 0x1000);
    memory_region_add_subregion_overlap(get_system_memory(), 0x146bf000, &s->reg, 2);
}

static Property nio_properties[] = {
    DEFINE_PROP_UINT32("value", NioTzLogPointer, value, 0),
    DEFINE_PROP_BOOL("publications", NioTzLogPointer, publications, false),
    DEFINE_PROP_BOOL("ready-publication", NioTzLogPointer, ready_publication, false),
    DEFINE_PROP_BOOL("sec-flag-replay", NioTzLogPointer, sec_flag_replay, false),
    DEFINE_PROP_UINT32("sec-flag-value", NioTzLogPointer, sec_flag_value, 0),
    DEFINE_PROP_END_OF_LIST(),
};

static void nio_class_init(ObjectClass *oc, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(oc);
    dc->desc = "Bounded read-only TZ-log pointer replay";
    dc->realize = nio_realize;
    dc->hotpluggable = false;
    device_class_set_props(dc, nio_properties);
}

static const TypeInfo nio_info = {
    .name = TYPE_NIO_TZ_LOG_POINTER,
    .parent = TYPE_DEVICE,
    .instance_size = sizeof(NioTzLogPointer),
    .class_init = nio_class_init,
};

static void nio_register_types(void)
{
    type_register_static(&nio_info);
}
type_init(nio_register_types)
