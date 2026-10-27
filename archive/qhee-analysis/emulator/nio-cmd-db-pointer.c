/* SPDX-License-Identifier: GPL-2.0-or-later
 * Read-only replay of the single measured CMD_DB_POINTER word used by QHEE.
 * The value is explicitly supplied by the caller. All writes fail.
 */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "hw/qdev-core.h"
#include "hw/qdev-properties.h"
#include "exec/address-spaces.h"
#include "exec/memory.h"

#define TYPE_NIO_CMD_DB_POINTER "nio-cmd-db-pointer"
OBJECT_DECLARE_SIMPLE_TYPE(NioCmdDbPointer, NIO_CMD_DB_POINTER)

struct NioCmdDbPointer {
    DeviceState parent_obj;
    MemoryRegion reg;
    uint32_t value;
};

static MemTxResult nio_read(void *opaque, hwaddr offset, uint64_t *value,
                            unsigned size, MemTxAttrs attrs)
{
    NioCmdDbPointer *s = opaque;
    if (offset != 0xc || size != 4) {
        return MEMTX_ERROR;
    }
    *value = s->value;
    fprintf(stderr, "NIO_CMD_DB_POINTER_READ address=0x0c3f000c value=0x%08x size=4\n", s->value);
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
    NioCmdDbPointer *s = NIO_CMD_DB_POINTER(dev);
    memory_region_init_io(&s->reg, OBJECT(dev), &nio_ops, s,
                          TYPE_NIO_CMD_DB_POINTER, 0x1000);
    memory_region_add_subregion_overlap(get_system_memory(), 0x0c3f0000, &s->reg, 2);
}

static Property nio_properties[] = {
    DEFINE_PROP_UINT32("value", NioCmdDbPointer, value, 0),
    DEFINE_PROP_END_OF_LIST(),
};

static void nio_class_init(ObjectClass *oc, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(oc);
    dc->desc = "Bounded read-only command-database pointer replay";
    dc->realize = nio_realize;
    dc->hotpluggable = false;
    device_class_set_props(dc, nio_properties);
}

static const TypeInfo nio_info = {
    .name = TYPE_NIO_CMD_DB_POINTER,
    .parent = TYPE_DEVICE,
    .instance_size = sizeof(NioCmdDbPointer),
    .class_init = nio_class_init,
};

static void nio_register_types(void)
{
    type_register_static(&nio_info);
}
type_init(nio_register_types)
