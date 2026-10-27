/* SPDX-License-Identifier: GPL-2.0-or-later
 * Captured nio v5 PMIC arbiter APID table only. No PMIC transactions.
 * Guard the DT core and firmware-observed secondary table pages; reject holes.
 */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "qemu/bswap.h"
#include "qapi/error.h"
#include "hw/qdev-core.h"
#include "hw/qdev-properties.h"
#include "exec/address-spaces.h"
#include "exec/memory.h"

#define TYPE_NIO_PMIC_ARB "nio-pmic-arb"
OBJECT_DECLARE_SIMPLE_TYPE(NioPmicArb, NIO_PMIC_ARB)

struct NioPmicArb {
    DeviceState parent_obj;
    MemoryRegion core;
    MemoryRegion config;
    char *snapshot;
    char *owners;
    char *secondary;
    uint8_t *blob;
    uint8_t *owner_blob;
    uint8_t *secondary_blob;
};

static MemTxResult nio_read(void *opaque, hwaddr offset, uint64_t *value,
                            unsigned size, MemTxAttrs attrs)
{
    NioPmicArb *s = opaque;
    if (size == 4 && !(offset & 3) && offset >= 0x900 && offset < 0x1100) {
        *value = ldl_le_p(s->blob + offset - 0x900);
        fprintf(stderr, "NIO_PMIC_APID_READ address=0x%08lx value=0x%08lx size=4\n",
                (unsigned long)(0xc440000 + offset), (unsigned long)*value);
        return MEMTX_OK;
    }
    if (s->secondary_blob && size == 4 && !(offset & 3) && offset >= 0x2300 && offset < 0x2700) {
        *value = ldl_le_p(s->secondary_blob + offset - 0x2300);
        fprintf(stderr, "NIO_PMIC_SECONDARY_READ address=0x%08lx value=0x%08lx size=4\n",
                (unsigned long)(0xc440000 + offset), (unsigned long)*value);
        return MEMTX_OK;
    }
    fprintf(stderr, "NIO_PMIC_DENIED read offset=0x%lx size=%u\n", (unsigned long)offset, size);
    return MEMTX_ERROR;
}

static MemTxResult owner_read(void *opaque, hwaddr offset, uint64_t *value,
                              unsigned size, MemTxAttrs attrs)
{
    NioPmicArb *s = opaque;
    if (s->owner_blob && size == 4 && !(offset & 3) && offset >= 0x700 && offset < 0xf00) {
        *value = ldl_le_p(s->owner_blob + offset - 0x700);
        fprintf(stderr, "NIO_PMIC_OWNER_READ address=0x%08lx value=0x%08lx size=4\n",
                (unsigned long)(0xc40a000 + offset), (unsigned long)*value);
        return MEMTX_OK;
    }
    fprintf(stderr, "NIO_PMIC_DENIED owner read offset=0x%lx size=%u\n", (unsigned long)offset, size);
    return MEMTX_ERROR;
}

static MemTxResult nio_write(void *opaque, hwaddr offset, uint64_t value,
                             unsigned size, MemTxAttrs attrs)
{
    fprintf(stderr, "NIO_PMIC_DENIED write offset=0x%lx size=%u value=0x%lx\n",
            (unsigned long)offset, size, (unsigned long)value);
    return MEMTX_ERROR;
}

static const MemoryRegionOps nio_ops = {
    .read_with_attrs = nio_read,
    .write_with_attrs = nio_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 8, .unaligned = true },
    .impl = { .min_access_size = 1, .max_access_size = 8, .unaligned = true },
};

static const MemoryRegionOps owner_ops = {
    .read_with_attrs = owner_read,
    .write_with_attrs = nio_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 8, .unaligned = true },
    .impl = { .min_access_size = 1, .max_access_size = 8, .unaligned = true },
};

static void nio_realize(DeviceState *dev, Error **errp)
{
    NioPmicArb *s = NIO_PMIC_ARB(dev);
    gsize len;
    GError *error = NULL;
    if (!s->snapshot || !g_file_get_contents(s->snapshot, (char **)&s->blob, &len, &error)) {
        error_setg(errp, "nio-pmic-arb: snapshot required: %s", error ? error->message : "missing property");
        g_clear_error(&error);
        return;
    }
    if (len != 512 * 4) {
        error_setg(errp, "nio-pmic-arb: snapshot must contain exactly 512 uint32 words");
        return;
    }
    if (s->owners) {
        if (!g_file_get_contents(s->owners, (char **)&s->owner_blob, &len, &error)) {
            error_setg(errp, "nio-pmic-arb: owner snapshot unreadable: %s", error->message);
            g_clear_error(&error);
            return;
        }
        if (len != 512 * 4) {
            error_setg(errp, "nio-pmic-arb: owner snapshot must contain exactly 512 uint32 words");
            return;
        }
    }
    if (s->secondary) {
        if (!s->owners) {
            error_setg(errp, "nio-pmic-arb: secondary replay requires owners");
            return;
        }
        if (!g_file_get_contents(s->secondary, (char **)&s->secondary_blob, &len, &error)) {
            error_setg(errp, "nio-pmic-arb: secondary snapshot unreadable: %s", error->message);
            g_clear_error(&error);
            return;
        }
        if (len != 256 * 4) {
            error_setg(errp, "nio-pmic-arb: secondary snapshot must contain exactly 256 uint32 words");
            return;
        }
    }
    memory_region_init_io(&s->config, OBJECT(dev), &owner_ops, s, TYPE_NIO_PMIC_ARB "-owners", 0x1000);
    memory_region_add_subregion_overlap(get_system_memory(), 0xc40a000, &s->config, 2);
    memory_region_init_io(&s->core, OBJECT(dev), &nio_ops, s, TYPE_NIO_PMIC_ARB, 0x3000);
    memory_region_add_subregion_overlap(get_system_memory(), 0xc440000, &s->core, 2);
}

static void nio_finalize(Object *obj)
{
    g_free(NIO_PMIC_ARB(obj)->blob);
    g_free(NIO_PMIC_ARB(obj)->owner_blob);
    g_free(NIO_PMIC_ARB(obj)->secondary_blob);
}

static Property nio_properties[] = {
    DEFINE_PROP_STRING("snapshot", NioPmicArb, snapshot),
    DEFINE_PROP_STRING("owners", NioPmicArb, owners),
    DEFINE_PROP_STRING("secondary", NioPmicArb, secondary),
    DEFINE_PROP_END_OF_LIST(),
};

static void nio_class_init(ObjectClass *oc, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(oc);
    dc->desc = "Bounded read-only nio PMIC arbiter APID capture";
    dc->realize = nio_realize;
    dc->hotpluggable = false;
    device_class_set_props(dc, nio_properties);
}

static const TypeInfo nio_info = {
    .name = TYPE_NIO_PMIC_ARB,
    .parent = TYPE_DEVICE,
    .instance_size = sizeof(NioPmicArb),
    .instance_finalize = nio_finalize,
    .class_init = nio_class_init,
};

static void nio_register_types(void)
{
    type_register_static(&nio_info);
}
type_init(nio_register_types)
