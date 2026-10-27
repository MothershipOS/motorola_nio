/* SPDX-License-Identifier: GPL-2.0-or-later
 * Optional RAM backing for isolated original TZ monitor fixtures.
 * No SoC or secure-service semantics; never enabled by the QHEE runner.
 */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "hw/qdev-core.h"
#include "exec/address-spaces.h"
#include "exec/memory.h"

#define TYPE_NIO_TZ_FIXTURE_RAM "nio-tz-fixture-ram"
OBJECT_DECLARE_SIMPLE_TYPE(NioTzFixtureRam, NIO_TZ_FIXTURE_RAM)
struct NioTzFixtureRam {
    DeviceState parent_obj;
    MemoryRegion early, monitor;
};
static void fixture_realize(DeviceState *dev, Error **errp)
{
    NioTzFixtureRam *s = NIO_TZ_FIXTURE_RAM(dev);
    memory_region_init_ram(&s->early, OBJECT(dev), "nio-tz-fixture-early",
                           0x10000, errp);
    if (*errp) {
        return;
    }
    memory_region_init_ram(&s->monitor, OBJECT(dev), "nio-tz-fixture-monitor",
                           0x18000, errp);
    if (*errp) {
        return;
    }
    memory_region_add_subregion(get_system_memory(), 0x14680000, &s->early);
    memory_region_add_subregion(get_system_memory(), 0x1c018000, &s->monitor);
}
static void fixture_class_init(ObjectClass *oc, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(oc);
    dc->desc = "RAM backing for bounded original TZ monitor fixtures";
    dc->realize = fixture_realize;
    dc->hotpluggable = false;
}
static const TypeInfo fixture_info = {
    .name = TYPE_NIO_TZ_FIXTURE_RAM,
    .parent = TYPE_DEVICE,
    .instance_size = sizeof(NioTzFixtureRam),
    .class_init = fixture_class_init,
};
static void fixture_register_types(void)
{
    type_register_static(&fixture_info);
}
type_init(fixture_register_types)
