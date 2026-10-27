/* SPDX-License-Identifier: GPL-2.0-or-later
 * Read-only replay of the single measured QFPROM word used by QHEE.
 * The value is explicitly supplied by the caller. All writes fail.
 */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "hw/qdev-core.h"
#include "hw/qdev-properties.h"
#include "exec/address-spaces.h"
#include "exec/memory.h"

#define TYPE_NIO_QFPROM "nio-qfprom"
OBJECT_DECLARE_SIMPLE_TYPE(NioQfprom, NIO_QFPROM)

struct NioQfprom {
    DeviceState parent_obj;
    MemoryRegion reg;
    uint32_t value;
};

static MemTxResult nio_read(void *opaque, hwaddr offset, uint64_t *value,
                            unsigned size, MemTxAttrs attrs)
{
    NioQfprom *s = opaque;
    if (offset != 0x218 || size != 4) {
        return MEMTX_ERROR;
    }
    *value = s->value;
    fprintf(stderr, "NIO_QFPROM_READ address=0x00784218 value=0x%08x size=4\n", s->value);
    return MEMTX_OK;
}

static MemTxResult nio_write(void *opaque, hwaddr offset, uint64_t value,
                             unsigned size, MemTxAttrs attrs)
{
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
    NioQfprom *s = NIO_QFPROM(dev);
    memory_region_init_io(&s->reg, OBJECT(dev), &nio_ops, s,
                          TYPE_NIO_QFPROM, 0x1000);
    memory_region_add_subregion_overlap(get_system_memory(), 0x00784000, &s->reg, 2);
}

static Property nio_properties[] = {
    DEFINE_PROP_UINT32("value", NioQfprom, value, 0),
    DEFINE_PROP_END_OF_LIST(),
};

static void nio_class_init(ObjectClass *oc, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(oc);
    dc->desc = "Bounded read-only QFPROM word replay; no programming interface";
    dc->realize = nio_realize;
    dc->hotpluggable = false;
    device_class_set_props(dc, nio_properties);
}

static const TypeInfo nio_info = {
    .name = TYPE_NIO_QFPROM,
    .parent = TYPE_DEVICE,
    .instance_size = sizeof(NioQfprom),
    .class_init = nio_class_init,
};

static void nio_register_types(void)
{
    type_register_static(&nio_info);
}
type_init(nio_register_types)
