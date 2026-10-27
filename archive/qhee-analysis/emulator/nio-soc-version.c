/* SPDX-License-Identifier: GPL-2.0-or-later
 * Diagnostic hardware-version input plus optional one-shot SEC selector replay.
 * The value is explicitly supplied by the caller. All writes fail.
 */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "hw/qdev-core.h"
#include "hw/qdev-properties.h"
#include "exec/address-spaces.h"
#include "exec/memory.h"

#define TYPE_NIO_SOC_VERSION "nio-soc-version"
OBJECT_DECLARE_SIMPLE_TYPE(NioSocVersion, NIO_SOC_VERSION)

struct NioSocVersion {
    DeviceState parent_obj;
    MemoryRegion reg;
    uint32_t value;
    uint32_t selector_value;
    bool selector_replay;
    bool version_read;
    bool selector_read;
};

static MemTxResult nio_read(void *opaque, hwaddr offset, uint64_t *value,
                            unsigned size, MemTxAttrs attrs)
{
    NioSocVersion *s = opaque;
    if (offset == 4 && size == 4 && s->selector_replay &&
        s->version_read && !s->selector_read) {
        s->selector_read = true;
        *value = s->selector_value;
        fprintf(stderr, "NIO_SEC_SELECTOR_READ address=0x01fc8004 value=0x%08x size=4\n",
                s->selector_value);
        return MEMTX_OK;
    }
    if (offset != 0 || size != 4) {
        return MEMTX_ERROR;
    }
    s->version_read = true;
    *value = s->value;
    fprintf(stderr, "NIO_MODEL_TCSR_READ address=0x01fc8000 value=0x%08x size=4\n", s->value);
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
    /* Deliver aligned 8-byte accesses intact so callbacks reject them,
     * rather than splitting a wide base read into two permitted words. */
    .valid = { .min_access_size = 4, .max_access_size = 8, .unaligned = false },
    .impl = { .min_access_size = 4, .max_access_size = 8 },
};

static void nio_realize(DeviceState *dev, Error **errp)
{
    NioSocVersion *s = NIO_SOC_VERSION(dev);
    memory_region_init_io(&s->reg, OBJECT(dev), &nio_ops, s,
                          TYPE_NIO_SOC_VERSION, s->selector_replay ? 8 : 4);
    memory_region_add_subregion(get_system_memory(), 0x01fc8000, &s->reg);
}

static Property nio_properties[] = {
    DEFINE_PROP_UINT32("value", NioSocVersion, value, 0),
    DEFINE_PROP_BOOL("selector-replay", NioSocVersion, selector_replay, false),
    DEFINE_PROP_UINT32("selector-value", NioSocVersion, selector_value, 0),
    DEFINE_PROP_END_OF_LIST(),
};

static void nio_class_init(ObjectClass *oc, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(oc);
    dc->desc = "Offline QHEE hardware-version register hypothesis";
    dc->realize = nio_realize;
    dc->hotpluggable = false;
    device_class_set_props(dc, nio_properties);
}

static const TypeInfo nio_info = {
    .name = TYPE_NIO_SOC_VERSION,
    .parent = TYPE_DEVICE,
    .instance_size = sizeof(NioSocVersion),
    .class_init = nio_class_init,
};

static void nio_register_types(void)
{
    type_register_static(&nio_info);
}
type_init(nio_register_types)
