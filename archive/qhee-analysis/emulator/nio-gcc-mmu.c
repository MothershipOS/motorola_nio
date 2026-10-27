/* SPDX-License-Identifier: GPL-2.0-or-later
 * Minimal QHEE control-path model, not DMA translation or an SM8250 clock tree.
 * Register whitelist comes from this phone's backed-up QHEE descriptors.
 */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "qemu/timer.h"
#include "qemu/host-utils.h"
#include "hw/qdev-core.h"
#include "hw/qdev-properties.h"
#include "exec/address-spaces.h"
#include "exec/memory.h"

#define TYPE_NIO_GCC_MMU "nio-gcc-mmu"
OBJECT_DECLARE_SIMPLE_TYPE(NioGccMmu, NIO_GCC_MMU)
typedef struct NioMmuBank {
    MemoryRegion region;
    uint64_t base;
    bool ids_enabled;
    uint32_t ids[3];
    bool control_enabled;
    uint32_t control[0x2400/4];
    bool contexts_enabled;
    uint32_t contexts[96][0x80/4];
} NioMmuBank;

struct NioGccMmu {
    DeviceState parent_obj;
    MemoryRegion gcc, gpu, timer;
    NioMmuBank mmu[2];
    bool initially_enabled;
    uint32_t enable[28];
    uint32_t gpu_control[2];
    bool ids_enabled;
    uint32_t ids[6];
    bool timer_enabled;
    bool contexts_enabled;
    bool control_enabled;
};

/* 0x17c000 + offset; enable bit 0 used by helpers at 0x80063ad0/0x80063b08. */
static bool clock_valid(hwaddr off)
{
    return off >= 4 && off <= 0x30 && off != 0x28 && !(off & 3);
}

static bool power_valid(hwaddr off)
{
    return off >= 0x40 && off <= 0x6c && off != 0x64 && off != 0x68 && !(off & 3);
}

static uint32_t control_read(uint32_t control)
{
    /* Clock: bit31 means halted. GDSC: bit31 means powered, bit0 collapses. */
    return control | (!control ? 0x80000000U : 0);
}

static MemTxResult gcc_read(void *opaque, hwaddr off, uint64_t *value,
                           unsigned size, MemTxAttrs attrs)
{
    NioGccMmu *s = opaque;
    if (size != 4 || (!clock_valid(off) && !power_valid(off))) {
        fprintf(stderr, "NIO_GCC_DENIED read offset=0x%" HWADDR_PRIx " size=%u\n", off, size);
        return MEMTX_ERROR;
    }
    *value = control_read(s->enable[off/4]);
    fprintf(stderr, "NIO_GCC_READ address=0x%08" HWADDR_PRIx " value=0x%" PRIx64 "\n", 0x17c000+off, *value);
    return MEMTX_OK;
}

static MemTxResult gcc_write(void *opaque, hwaddr off, uint64_t value,
                            unsigned size, MemTxAttrs attrs)
{
    NioGccMmu *s = opaque;
    if (size != 4 || (!clock_valid(off) && !power_valid(off)) || (value & ~UINT64_C(0x80000001))) {
        fprintf(stderr, "NIO_GCC_DENIED write offset=0x%" HWADDR_PRIx " size=%u value=0x%" PRIx64 "\n", off, size, value);
        return MEMTX_ERROR;
    }
    s->enable[off/4] = value & 1;
    fprintf(stderr, "NIO_GCC_WRITE address=0x%08" HWADDR_PRIx " control=%u\n", 0x17c000+off, s->enable[off/4]);
    return MEMTX_OK;
}

static const MemoryRegionOps gcc_ops = {
    .read_with_attrs = gcc_read, .write_with_attrs = gcc_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    /* Keep wide/unaligned transactions intact so callbacks reject them. */
    .valid = { .min_access_size = 4, .max_access_size = 8, .unaligned = true },
    .impl = { .min_access_size = 4, .max_access_size = 8, .unaligned = true },
};

static MemTxResult gpu_read(void *opaque, hwaddr off, uint64_t *value,
                           unsigned size, MemTxAttrs attrs)
{
    NioGccMmu *s = opaque;
    if (size != 4 || (off != 0 && off != 4)) {
        return MEMTX_ERROR;
    }
    *value = control_read(s->gpu_control[off/4]);
    fprintf(stderr, "NIO_GPU_MMU_READ offset=0x%" HWADDR_PRIx " value=0x%" PRIx64 "\n", off, *value);
    return MEMTX_OK;
}

static MemTxResult gpu_write(void *opaque, hwaddr off, uint64_t value,
                            unsigned size, MemTxAttrs attrs)
{
    NioGccMmu *s = opaque;
    if (size != 4 || (off != 0 && off != 4) || (value & ~UINT64_C(0x80000001))) {
        return MEMTX_ERROR;
    }
    s->gpu_control[off/4] = value & 1;
    fprintf(stderr, "NIO_GPU_MMU_WRITE offset=0x%" HWADDR_PRIx " value=0x%" PRIx64 "\n", off, value);
    return MEMTX_OK;
}

static const MemoryRegionOps gpu_ops = {
    .read_with_attrs = gpu_read, .write_with_attrs = gpu_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    /* Keep wide/unaligned transactions intact so callbacks reject them. */
    .valid = { .min_access_size = 4, .max_access_size = 8, .unaligned = true },
    .impl = { .min_access_size = 4, .max_access_size = 8, .unaligned = true },
};

static bool mmu_control_valid(NioMmuBank *b, hwaddr off)
{
    unsigned streams = b->ids[0] & 255;
    unsigned contexts = b->ids[1] & 255;
    if (off & 3) {
        return false;
    }
    /* Exact QHEE reset helpers plus architectural TLB maintenance registers. */
    switch (off) {
    case 0: case 4: case 8: case 0x10:
    case 0x400: case 0x404: case 0x408: case 0x410:
    case 0x48: case 0x4c: case 0x50: case 0x54: case 0x58:
    case 0x448: case 0x44c: case 0x450: case 0x454: case 0x458:
    case 0x64: case 0x68: case 0x6c: case 0x70: case 0x74:
        return true;
    }
    return (off >= 0x800 && off < 0x800+4*streams) ||
           (off >= 0xc00 && off < 0xc00+4*streams) ||
           (off >= 0x2000 && off < 0x2000+4*streams) ||
           (off >= 0x1000 && off < 0x1000+4*contexts) ||
           (off >= 0x1400 && off < 0x1400+4*contexts) ||
           (off >= 0x1800 && off < 0x1800+4*contexts);
}

/* CPU-visible configuration only. Never walks tables or translates DMA. */
static bool context_decode(NioMmuBank *b, hwaddr off, unsigned size,
                           unsigned *index, unsigned *reg)
{
    unsigned page_shift = (b->ids[1] & (1U << 31)) ? 16 : 12;
    unsigned pages = (b->ids[1] >> 28) & 7;
    hwaddr start = UINT64_C(1) << (page_shift + pages + 1);
    if (!b->contexts_enabled || size != 4 || off < start || (off & 3)) {
        return false;
    }
    *index = (off-start) >> page_shift;
    *reg = (off-start) & ((1U << page_shift)-1);
    if (*index >= (b->ids[1] & 255) || *index >= 96) {
        return false;
    }
    switch (*reg) {
    case 0: case 4: case 0x10:
    case 0x20: case 0x24: case 0x28: case 0x2c:
    case 0x30: case 0x34: case 0x38: case 0x3c: case 0x58: case 0x5c:
    case 0x610: case 0x7f0: case 0x7f4:
        return true;
    default:
        return false;
    }
}

static MemTxResult mmu_read(void *opaque, hwaddr off, uint64_t *value,
                           unsigned size, MemTxAttrs attrs)
{
    NioMmuBank *b = opaque;
    unsigned index, reg;
    if (context_decode(b, off, size, &index, &reg) && reg != 0x5c) {
        *value = reg >= 0x80 ? 0 : b->contexts[index][reg/4];
        fprintf(stderr, "NIO_MMU_CONTEXT_READ address=0x%08" PRIx64 " value=0x%08" PRIx64 "\n", b->base+off, *value);
        return MEMTX_OK;
    }
    if (b->ids_enabled && size == 4 && off >= 0x20 && off <= 0x28 && !(off & 3)) {
        *value = b->ids[(off-0x20)/4];
        fprintf(stderr, "NIO_MMU_ID address=0x%08" PRIx64 " value=0x%08" PRIx64 "\n", b->base+off, *value);
        return MEMTX_OK;
    }
    if (b->control_enabled && size == 4 && mmu_control_valid(b,off)) {
        *value = off == 0x74 ? 0 : b->control[off/4];
        fprintf(stderr, "NIO_MMU_READ address=0x%08" PRIx64 " value=0x%08" PRIx64 "\n", b->base+off, *value);
        return MEMTX_OK;
    }
    fprintf(stderr, "NIO_MMU_DENIED read address=0x%08" PRIx64 " size=%u\n", b->base+off, size);
    return MEMTX_ERROR;
}

static MemTxResult mmu_write(void *opaque, hwaddr off, uint64_t value,
                            unsigned size, MemTxAttrs attrs)
{
    NioMmuBank *b = opaque;
    unsigned index, reg;
    if (context_decode(b, off, size, &index, &reg) && reg != 0x7f4) {
        if (reg == 0x5c) {
            if (value != 0) { return MEMTX_ERROR; }
            b->contexts[index][0x58/4] = 0;
        } else if (reg == 0x58) {
            b->contexts[index][reg/4] &= ~value;
        } else if (reg < 0x80) {
            b->contexts[index][reg/4] = value;
        } /* TLB commands complete with no cached translations or DMA. */
        fprintf(stderr, "NIO_MMU_CONTEXT_WRITE address=0x%08" PRIx64 " value=0x%08" PRIx64 "\n", b->base+off, value);
        return MEMTX_OK;
    }
    if (b->control_enabled && size == 4 && off != 0x74 && mmu_control_valid(b,off)) {
        if (off == 0x48 || off == 0x448) {
            b->control[off/4] &= ~value;
        } else if (off >= 0x64 && off <= 0x70) {
            /* No DMA clients or cached translations exist in this model. */
        } else {
            b->control[off/4] = value;
        }
        fprintf(stderr, "NIO_MMU_WRITE address=0x%08" PRIx64 " value=0x%08" PRIx64 "\n", b->base+off, value);
        return MEMTX_OK;
    }
    fprintf(stderr, "NIO_MMU_DENIED write address=0x%08" PRIx64 " size=%u value=0x%" PRIx64 "\n", b->base+off, size, value);
    return MEMTX_ERROR;
}

static const MemoryRegionOps mmu_ops = {
    .read_with_attrs = mmu_read, .write_with_attrs = mmu_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 8, .unaligned = true },
    .impl = { .min_access_size = 4, .max_access_size = 8, .unaligned = true },
};

static MemTxResult timer_read(void *opaque, hwaddr off, uint64_t *value,
                             unsigned size, MemTxAttrs attrs)
{
    uint64_t ticks;
    if (!((size == 4 && (off == 0 || off == 4)) || (size == 8 && off == 0))) {
        return MEMTX_ERROR;
    }
    ticks = muldiv64(qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL), 19200000, 1000000000);
    *value = size == 8 ? ticks : (uint32_t)(ticks >> (off*8));
    return MEMTX_OK;
}

static MemTxResult timer_write(void *opaque, hwaddr off, uint64_t value,
                              unsigned size, MemTxAttrs attrs)
{
    return MEMTX_ERROR;
}

static const MemoryRegionOps timer_ops = {
    .read_with_attrs = timer_read, .write_with_attrs = timer_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 8, .unaligned = true },
    .impl = { .min_access_size = 4, .max_access_size = 8, .unaligned = true },
};

static void nio_realize(DeviceState *dev, Error **errp)
{
    NioGccMmu *s = NIO_GCC_MMU(dev);
    for (unsigned i = 0; i < ARRAY_SIZE(s->enable); i++) {
        s->enable[i] = power_valid(i*4) ? !s->initially_enabled : s->initially_enabled;
    }
    memory_region_init_io(&s->gcc, OBJECT(dev), &gcc_ops, s, "nio-mmu-clocks", 0x100);
    memory_region_add_subregion(get_system_memory(), 0x17c000, &s->gcc);
    s->gpu_control[0] = s->initially_enabled;
    s->gpu_control[1] = !s->initially_enabled;
    memory_region_init_io(&s->gpu, OBJECT(dev), &gpu_ops, s, "nio-gpu-mmu-clock", 8);
    memory_region_add_subregion(get_system_memory(), 0x3d92000, &s->gpu);
    for (unsigned i = 0; i < 2; i++) {
        s->mmu[i].base = i ? 0x3da0000 : 0x15000000;
        s->mmu[i].ids_enabled = s->ids_enabled;
        s->mmu[i].contexts_enabled = s->contexts_enabled && s->ids_enabled && s->control_enabled;
        s->mmu[i].control_enabled = s->control_enabled && s->ids_enabled;
        memcpy(s->mmu[i].ids, s->ids+3*i, sizeof(s->mmu[i].ids));
        memory_region_init_io(&s->mmu[i].region, OBJECT(dev), &mmu_ops, &s->mmu[i],
                              i ? "nio-gpu-mmu" : "nio-apps-mmu", i ? 0x10000 : 0x100000);
        memory_region_add_subregion_overlap(get_system_memory(), s->mmu[i].base, &s->mmu[i].region, 2);
    }
    if (s->timer_enabled) {
        memory_region_init_io(&s->timer, OBJECT(dev), &timer_ops, s, "nio-qtimer-counter", 8);
        memory_region_add_subregion_overlap(get_system_memory(), 0x17c25000, &s->timer, 2);
        fprintf(stderr, "NIO_QTIMER_INIT 19.2MHz virtual-time counter model\n");
    }
    fprintf(stderr, "NIO_GCC_INIT enabled=%u control-path-only model assumption\n", s->initially_enabled);
}

static Property nio_properties[] = {
    DEFINE_PROP_BOOL("initially-enabled", NioGccMmu, initially_enabled, false),
    DEFINE_PROP_BOOL("ids-enabled", NioGccMmu, ids_enabled, false),
    DEFINE_PROP_BOOL("timer", NioGccMmu, timer_enabled, false),
    DEFINE_PROP_BOOL("contexts", NioGccMmu, contexts_enabled, false),
    DEFINE_PROP_BOOL("control", NioGccMmu, control_enabled, false),
    DEFINE_PROP_UINT32("apps-id0", NioGccMmu, ids[0], 0),
    DEFINE_PROP_UINT32("apps-id1", NioGccMmu, ids[1], 0),
    DEFINE_PROP_UINT32("apps-id2", NioGccMmu, ids[2], 0),
    DEFINE_PROP_UINT32("gpu-id0", NioGccMmu, ids[3], 0),
    DEFINE_PROP_UINT32("gpu-id1", NioGccMmu, ids[4], 0),
    DEFINE_PROP_UINT32("gpu-id2", NioGccMmu, ids[5], 0),
    DEFINE_PROP_END_OF_LIST(),
};

static void nio_class_init(ObjectClass *oc, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(oc);
    dc->desc = "Bounded nio GCC/MMU initialization control-path model";
    dc->realize = nio_realize;
    dc->hotpluggable = false;
    device_class_set_props(dc, nio_properties);
}

static const TypeInfo nio_info = {
    .name = TYPE_NIO_GCC_MMU, .parent = TYPE_DEVICE,
    .instance_size = sizeof(NioGccMmu), .class_init = nio_class_init,
};

static void nio_register_types(void)
{
    type_register_static(&nio_info);
}
type_init(nio_register_types)
