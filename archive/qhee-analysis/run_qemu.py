#!/usr/bin/env python3
"""Run original QHEE on a synthetic QEMU virt/EL3 platform. Never accesses USB.

Unmodeled SoC/TZ behavior is a stopping point, not silently patched out.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qhee import QheeImage, ROOT, DEFAULT_IMAGE
from smem import snapshot as smem_snapshot
from pmic import sample as pmic_sample, owner_sample as pmic_owner_sample, secondary_sample as pmic_secondary_sample
from smmu_config import firmware_counts, PINNED_HYP
from pmic_regions import inventory as pmic_region_inventory
from handoff import loaded_code
from xbl_target import payload as xbl_payload
from tz_query import reply_model as xbl_query_reply_model
from tz_buffer import reply_model as xbl_buffer_reply_model
from xbl_canary import reply_model as xbl_canary_reply_model
from xbl_selector import sample as xbl_selector_sample
from xbl_readiness import sample as xbl_readiness_sample
from xbl_startup import sentinel as xbl_sentinel, sentinel_metadata as xbl_sentinel_metadata
from entry_state import NAMES as ENTRY_STATE_NAMES, model as entry_state_model, defines as entry_state_defines


def environment(qemu_override=None):
    root = ROOT / 'kernel-work/emulation/root'
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = str(root / 'usr/lib/x86_64-linux-gnu')
    return Path(qemu_override).resolve() if qemu_override else root / 'usr/bin/qemu-system-aarch64', env


def compile_elf(source, address, output, defines=()):
    subprocess.run(['aarch64-linux-gnu-gcc', '-nostdlib', '-static', '-no-pie',
        '-Wl,--build-id=none', '-Wl,-Ttext=' + hex(address), '-Wl,-e,_start',
        '-o', str(output), str(source)] + list(defines), check=True)


def decode_stop(stdout):
    text = stdout.decode(errors='replace')
    match = re.search(r'EL3_STOP ESR ELR FAR SPSR X0 X1 X2 X3:\n((?:[0-9a-f]{16}\n){8})', text)
    if not match:
        return None
    registers = dict(zip(('esr', 'elr', 'far', 'spsr', 'x0', 'x1', 'x2', 'x3'),
                         (int(v, 16) for v in match.group(1).splitlines())))
    result = {'registers': {k: hex(v) for k, v in registers.items()}}
    if registers['esr'] >> 26 == 0x17 and registers['x0'] == 0xc2000108:
        result['service'] = 'TZ_SECURE_WDOG_TRIGGER_ID'
        result['terminal'] = True
    elif registers['esr'] >> 26 == 0x17 and registers['x0'] == 0x42000604:
        result['service'] = 'TZ_INFO_GET_SECURE_STATE'
        result['terminal'] = False
    elif registers['esr'] >> 26 == 0x17 and registers['x0'] == 0x84000000:
        result['service'] = 'PSCI_VERSION'
        result['terminal'] = False
    elif registers['esr'] >> 26 == 0x17 and registers['x0'] == 0xc2000a02:
        result['service'] = 'QHEE_PRNG_GET_DATA'
        result['terminal'] = False
    fault = re.search(r'Faulting Address: (0x[0-9a-f]+)\s+Address of Last Instruction Executed: (0x[0-9a-f]+)', text)
    if fault:
        result['qhee_fault'] = {'address': fault.group(1), 'pc': fault.group(2)}
    return result


def classify_output(stdout, rc, status, probe_output=b''):
    lines = (stdout+probe_output).decode(errors='replace').splitlines()
    stop = decode_stop(stdout)
    if stop and stop.get('service') == 'TZ_SECURE_WDOG_TRIGGER_ID':
        return 'qhee_fatal_watchdog_request'
    if any(line.startswith('EL3_STOP') for line in lines):
        return 'blocked_at_unmodeled_el3_exception'
    if status == 'timeout':
        return 'timeout_without_handoff'
    if rc == 0 and status == 'exited' and any(line in ('EL1', 'EL2') for line in lines):
        return 'synthetic_probe_reached'
    return 'unexpected_exit'


def provenance(qemu, sources):
    paths = [qemu, Path(__file__), Path(__file__).with_name('qhee.py'), Path(__file__).with_name('smem.py'), Path(__file__).with_name('smmu_config.py'),
             sources / 'start.S', sources / 'smem_assign.S', sources / 'smem_partitions.S', sources / 'tz_channel_assign.S', sources / 'tz_channel_21_42_assign.S', sources / 'cmd_db_assign.S', sources / 'hyp_log_share.S', sources / 'pil_empty_regions.S', sources / 'shm_bridge.S', sources / 'bridge_prng.S', sources / 'pmic_region_map.S', sources / 'pmic_region_map_table.S', Path(__file__).with_name('pmic_regions.py'), Path(__file__).with_name('handoff.py'), Path(__file__).with_name('hyp_patch.py'), sources / 'probe.S', sources / 'handoff_probe.S', Path(__file__).with_name('pmic.py')] + sorted(sources.glob('nio-*.c'))
    paths += [Path(__file__).with_name(n) for n in ('transition.py','xbl_target.py','xbl_startup.py','xbl_stack.py','xbl_cache.py','xbl_canary.py','xbl_readiness.py','xbl_counter.py','xbl_selector.py','tz_query.py','tz_buffer.py','bootchain.py','entry_state.py','tz_handoff.py')] + [sources / 'el2_diag_transition.S', sources / 'xbl_query.S', sources / 'xbl_buffer.S', sources / 'xbl_canary.S']
    return {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths}


def secure_state_sample(path):
    data = path.read_bytes()
    report = json.loads(data)
    result = report['secure_state']
    if result['service'] != '0x42000604' or result['status'] != 0:
        raise ValueError('sample must record a successful INFO/GET_SECURE_STATE query')
    values = [int(result[k], 0) for k in ('r1', 'r2', 'r3')]
    if any(v < 0 or v > 0xffffffffffffffff for v in values):
        raise ValueError('sample register value does not fit in 64 bits')
    return values, {'path':str(path.resolve()), 'sha256':hashlib.sha256(data).hexdigest(),
                    'response':result, 'transport':report.get('transport'),
                    'caveat':'Replaying EL1-visible data for an EL2 caller; equality is a model assumption'}


def smmu_ids_sample(path):
    data = path.read_bytes()
    report = json.loads(data)
    if report.get('status') != 'captured':
        raise ValueError('SMMU ID capture must have succeeded')
    properties = {}
    for name,base in [('apps',0x15000000),('gpu',0x3da0000)]:
        for index,offset in enumerate((0x20,0x24,0x28)):
            value = int(report['registers'][hex(base+offset)],0)
            if not 0 <= value <= 0xffffffff:
                raise ValueError('ID register out of range')
            properties[f'{name}-id{index}'] = value
        if not properties[f'{name}-id0'] & (1<<30) or not properties[f'{name}-id1'] & 255:
            raise ValueError('SMMU IDs lack expected stage-1 capability/context banks; device may be powered off')
    return properties, {'path':str(path.resolve()),'sha256':hashlib.sha256(data).hexdigest(),
        'registers':report['registers'],'caveat':report.get('caveat'),
        'view':'EL1-visible; QHEE filters ID0 features/stream count and ID1 context count; not raw EL2 IDs'}


def qfprom_sample(path):
    data = path.read_bytes()
    report = json.loads(data)
    try:
        check = report['checks']['qfprom_784218']
        if check['command'] != 'devmem 0x00784218 32' or check['status'] != 0:
            raise ValueError('QFPROM capture must be the successful exact 32-bit read')
        lines = [line.strip() for line in check['stdout'].splitlines()
                 if line.strip() and line.strip() != '~ #']
        if len(lines) != 1 or not re.fullmatch(r'0x[0-9a-fA-F]{8}', lines[0]):
            raise ValueError('QFPROM capture must contain exactly one uint32 result')
        value = int(lines[0], 16)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('Incomplete QFPROM capture') from error
    return value, {'path':str(path.resolve()), 'sha256':hashlib.sha256(data).hexdigest(),
        'address':'0x784218', 'value':hex(value), 'capture_time':report.get('timestamp'),
        'caveat':'EL1-visible postboot word replayed for EL2; equality is an assumption; no fuse writes'}

def cmd_db_sample(path):
    data = path.read_bytes()
    report = json.loads(data)
    try:
        check = report['checks']['cmd_db_pointer']
        if check['command'] != 'devmem 0x0c3f000c 32' or check['status'] != 0:
            raise ValueError('Command-database pointer capture must be the successful exact 32-bit read')
        lines = [line.strip() for line in check['stdout'].splitlines()
                 if line.strip() and line.strip() != '~ #']
        if len(lines) != 1 or not re.fullmatch(r'0x[0-9a-fA-F]{8}', lines[0]):
            raise ValueError('Command-database pointer capture must contain exactly one uint32 result')
        value = int(lines[0], 16)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('Incomplete Command-database pointer capture') from error
    return value, {'path':str(path.resolve()), 'sha256':hashlib.sha256(data).hexdigest(),
        'address':'0xc3f000c', 'value':hex(value), 'capture_time':report.get('timestamp'),
        'caveat':'EL1-visible postboot word replayed for EL2; equality is an assumption; no SRAM writes'}


def tz_log_sample(path):
    data = path.read_bytes()
    report = json.loads(data)
    try:
        check = report['checks']['tz_log_pointer']
        if check['command'] != 'devmem 0x146bf720 32' or check['status'] != 0:
            raise ValueError('TZ-log pointer capture must be the successful exact 32-bit read')
        lines = [line.strip() for line in check['stdout'].splitlines()
                 if line.strip() and line.strip() != '~ #']
        if len(lines) != 1 or not re.fullmatch(r'0x[0-9a-fA-F]{8}', lines[0]):
            raise ValueError('TZ-log pointer capture must contain exactly one uint32 result')
        value = int(lines[0], 16)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('Incomplete TZ-log pointer capture') from error
    return value, {'path':str(path.resolve()), 'sha256':hashlib.sha256(data).hexdigest(),
        'address':'0x146bf720', 'value':hex(value), 'capture_time':report.get('timestamp'),
        'caveat':'EL1-visible postboot word replayed for EL2; equality is an assumption; no IMEM writes'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, default=DEFAULT_IMAGE)
    parser.add_argument('--seconds', type=int, default=3)
    parser.add_argument('--qemu', type=Path, help='explicit QEMU binary override')
    parser.add_argument('--out', type=Path, default=ROOT / 'kernel-work/out/qhee-emulation')
    parser.add_argument('--soc-hw-version', type=lambda x: int(x, 0),
                        help='explicit synthetic register value; requires QEMU nio-soc-version device')
    parser.add_argument('--qfprom-sample', type=Path, help='replay only the measured 32-bit QFPROM word at 0x784218; all writes and other offsets fail')
    parser.add_argument('--cmd-db-sample', type=Path, help='replay only the captured 32-bit SRAM command-database pointer; no SRAM writes')
    parser.add_argument('--tz-log-sample', type=Path, help='replay only the measured 32-bit IMEM TZ-log pointer; guard all other IMEM accesses')
    parser.add_argument('--pmic-secondary-sample', type=Path, help='replay exactly 256 captured secondary PMIC map words; requires --pmic-owner-sample')
    parser.add_argument('--pmic-owner-sample', type=Path, help='replay exactly 512 captured PMIC APID owner words; requires --pmic-arb-sample')
    parser.add_argument('--pmic-arb-sample', type=Path, help='replay exactly 512 captured read-only PMIC APID words; no PMIC transactions')
    parser.add_argument('--trace', action='store_true', help='save translated instruction blocks')
    parser.add_argument('--gcc-mmu-clocks', choices=['off','on'],
                        help='model identified MMU clock enable bits, initially off or on')
    parser.add_argument('--smmu-ids', type=Path, help='replay fixed SMMU ID0/1/2 measurements; other SMMU registers stop')
    parser.add_argument('--smmu-firmware-counts', action='store_true', help='derive minimal context/stream count hypothesis from pinned firmware and visible IDs; not raw hardware identity')
    parser.add_argument('--qcom-timer', action='store_true', help='19.2 MHz MMIO counter driven by QEMU virtual time')
    parser.add_argument('--smmu-contexts', action='store_true', help='bounded context-bank configuration registers; no DMA translation')
    parser.add_argument('--smmu-control', action='store_true', help='model whitelisted SMMU reset/configuration registers; no DMA translation')
    parser.add_argument('--smem-sample', type=Path, help='validated nio metadata capture; uncaptured bytes and writes abort')
    parser.add_argument('--smem-version-write', action='store_true',
                        help='allow modeled 32-bit writes only to SMEM header.version[0]')
    parser.add_argument('--smem-rlock-zero', action='store_true',
                        help='explicit single-CPU model: zero-initialized writable item 404 (RLOCK) only')
    parser.add_argument('--smem-mutex', action='store_true',
                        help='model only TCSR mutex 9, initially free; no remote lock contenders')
    parser.add_argument('--smem-ram-table-write', action='store_true',
                        help='allow writes to a private copy of captured item 402 (RAM partition table)')
    parser.add_argument('--devcfg', type=Path, help='load only the QHEE segment at 0x805fd000 from this device configuration ELF')
    parser.add_argument('--secure-state-sample', type=Path,
                        help='explicitly replay a successful captured EL1-visible response for the EL2 caller')
    parser.add_argument('--psci-version', type=lambda x: int(x, 0),
                        help='explicit version-query model, e.g. 0x10001 for PSCI 1.1; no other PSCI services')
    parser.add_argument('--prng-word', type=lambda x: int(x,0),
                        help='fixed synthetic PRNG bytes for three observed heap-init buffers only; not cryptographic entropy')
    parser.add_argument('--nonsecure-query-unsupported', action='store_true',
                        help='explicit failure-path experiment: return -1 for only IsDeviceNonSecure (0xc2000310), not a captured TZ reply')
    parser.add_argument('--smem-toc-assign', action='store_true', help='exact one-page ownership-ledger transition; assumes VMID 3 initially owns the SMEM TOC and TZ accepts the request; offline only')
    parser.add_argument('--smem-partition-assign', action='store_true', help='extend the ownership model to exact pinned SMEM partitions and destination sets; requires --smem-toc-assign')
    parser.add_argument('--tz-channel-assign', action='store_true', help='exact 4 KiB TZ-subsystem channel ownership transition from VMID 3 to 21/22; no channel contents or access enforcement')
    parser.add_argument('--tz-channel-21-42-assign', action='store_true', help='exact 8 KiB TZ-subsystem channel transition from VMID 3 to 21/42; requires --tz-channel-assign')
    parser.add_argument('--cmd-db-assign', action='store_true', help='exact 128 KiB command-database ownership transition to eight readers; no contents or access enforcement')
    parser.add_argument('--hyp-log-share', action='store_true', help='exact QHEE log ownership transition from VMID 4 to 3 R/4 RW; no TrustZone enforcement')
    parser.add_argument('--imem-publications', action='store_true', help='allow exact observed one-shot QHEE log pointer/size publication; requires --tz-log-sample')
    parser.add_argument('--pil-empty-region-list', action='store_true', help='explicit unmeasured experiment: first PIL region query returns an empty list, no memory clearing modeled')
    parser.add_argument('--pmic-region-map', action='store_true', help='assume TZ accepts exactly the pinned 241 VMID2 RW PMIC channel mappings; ledger only')
    parser.add_argument('--imem-ready-publication', action='store_true', help='allow exact final QHEE publication 0x800a5021 at 0x146bfb20; requires prior publications and PIL experiment')
    parser.add_argument('--handoff-prng', action='store_true', help='three exact late PRNG writes at 0x80095a60/0x801ccaa8/0x801ccaaa, fixed non-entropy word; requires --prng-word')
    parser.add_argument('--shm-bridge-handle', type=lambda x:int(x,0), help='exact one-shot SHM bridge success experiment with a nonzero synthetic 64-bit handle; requires --handoff-prng')
    parser.add_argument('--bridge-prng-word', type=lambda x:int(x,0), help='one exact 8-byte allocator PRNG write after SHM bridge creation; fixed non-entropy uint64')
    parser.add_argument('--payload-address',type=lambda x:int(x,0),choices=(0x40400000,0x90000000,0x9fc00000),default=0x40400000,help='synthetic incoming x0; 0x9fc00000 loads pinned original XBL FV, not a captured target')
    parser.add_argument('--handoff-experiment',choices=('spsr-el2h','el2-diag-mmu-off','el2-xbl-mmu-off','el2-diag-masked-mmu-off','el2-xbl-masked-mmu-off'),help='offline-only loaded-code EL2 experiment; bounded cache maintenance, no physical handoff proof')
    parser.add_argument('--entry-state-model',choices=ENTRY_STATE_NAMES,default='synthetic-masked',help='explicit QHEE entry controls; TZ-frame controls come from constructed-record monitor fixtures, not a phone capture')
    parser.add_argument('--prepare-only',action='store_true',help='XBL prefix fixture only: prepare loaders; execute later with the bounded read-only tracer')
    parser.add_argument('--xbl-workspace-sentinel',action='store_true',help='prepare-only original XBL: initialize two bounded workspace RAM ranges to 0xa5, with 16-byte guards')
    parser.add_argument('--xbl-query-reply',action='store_true',help='one exact XBL query reply derived from original TZ slices; policy/context switching remain assumed')
    parser.add_argument('--xbl-buffer-reply',action='store_true',help='one exact eight-byte XBL reply using original TZ slices and synthetic FIFO fixtures; requires query reply')
    parser.add_argument('--xbl-canary-reply',action='store_true',help='one exact second buffer fixture reply for SEC canary; requires first buffer reply, not entropy')
    parser.add_argument('--xbl-readiness-sample',type=Path,help='one measured postboot SEC flag read; explicit entry-state assumption, requires canary replay and exact IMEM publications')
    parser.add_argument('--xbl-selector-sample',type=Path,help='one measured SEC selector uint32 read; requires measured readiness, prepared original XBL and SoC version model')
    args = parser.parse_args()
    if args.xbl_selector_sample and not (args.xbl_readiness_sample and args.soc_hw_version is not None and args.prepare_only and args.payload_address==0x9fc00000):
        parser.error('--xbl-selector-sample requires --xbl-readiness-sample, --soc-hw-version and prepared original XBL')
    if args.xbl_readiness_sample and not (args.xbl_canary_reply and args.imem_ready_publication and args.tz_log_sample):
        parser.error('--xbl-readiness-sample requires --xbl-canary-reply, --imem-ready-publication and --tz-log-sample')
    if args.xbl_canary_reply and not args.xbl_buffer_reply:
        parser.error('--xbl-canary-reply requires --xbl-buffer-reply')
    if args.xbl_buffer_reply and not args.xbl_query_reply:
        parser.error('--xbl-buffer-reply requires --xbl-query-reply')
    if args.xbl_query_reply and not (args.prepare_only and args.payload_address==0x9fc00000 and args.bridge_prng_word is not None and args.handoff_experiment in (None,'el2-xbl-masked-mmu-off')):
        parser.error('--xbl-query-reply requires prepared original XBL, bridge PRNG and stock or masked EL2 handoff')
    if args.xbl_workspace_sentinel and not (args.prepare_only and args.payload_address==0x9fc00000):
        parser.error('--xbl-workspace-sentinel requires original XBL target and --prepare-only')
    if args.entry_state_model!='synthetic-masked' and not (args.bridge_prng_word is not None and args.payload_address in (0x90000000,0x9fc00000)):
        parser.error('--entry-state-model TZ variants require --bridge-prng-word and --payload-address 0x90000000 or 0x9fc00000')
    if (args.payload_address==0x9fc00000)!=args.prepare_only:
        parser.error('Original XBL target requires --prepare-only; --prepare-only is only for XBL prefix fixtures')
    if args.entry_state_model!='synthetic-masked' and args.handoff_experiment in ('el2-diag-mmu-off','el2-xbl-mmu-off'):
        parser.error('TZ-frame entry requires a terminal variant that masks DAIF before MMU/cache teardown')
    if args.handoff_experiment in ('el2-xbl-mmu-off','el2-xbl-masked-mmu-off'):
        if not (args.bridge_prng_word is not None and args.payload_address==0x9fc00000):
            parser.error('--handoff-experiment '+args.handoff_experiment+' requires --bridge-prng-word and --payload-address 0x9fc00000')
    elif args.handoff_experiment and not (args.bridge_prng_word is not None and args.payload_address==0x90000000):
        parser.error('--handoff-experiment requires --bridge-prng-word and --payload-address 0x90000000')
    if args.bridge_prng_word is not None:
        if not 0 <= args.bridge_prng_word <= 0xffffffffffffffff:
            parser.error('--bridge-prng-word must be a uint64')
        if args.shm_bridge_handle is None:
            parser.error('--bridge-prng-word requires --shm-bridge-handle')
    if args.shm_bridge_handle is not None:
        if not 1 <= args.shm_bridge_handle <= 0xffffffffffffffff:
            parser.error('--shm-bridge-handle must be a nonzero uint64')
        if not args.handoff_prng:
            parser.error('--shm-bridge-handle requires --handoff-prng')
    if args.handoff_prng and args.prng_word is None:
        parser.error('--handoff-prng requires --prng-word')
    if args.imem_ready_publication and not (args.imem_publications and args.pil_empty_region_list):
        parser.error('--imem-ready-publication requires --imem-publications and --pil-empty-region-list')
    if args.pmic_secondary_sample and not args.pmic_owner_sample:
        parser.error('--pmic-secondary-sample requires --pmic-owner-sample')
    if args.pmic_owner_sample and not args.pmic_arb_sample:
        parser.error('--pmic-owner-sample requires --pmic-arb-sample')
    if args.imem_publications and not args.tz_log_sample:
        parser.error('--imem-publications requires --tz-log-sample')
    if (args.smmu_ids or args.qcom_timer) and not args.gcc_mmu_clocks:
        parser.error('SMMU IDs/timer require --gcc-mmu-clocks')
    if args.smmu_contexts and not args.smmu_control:
        parser.error('--smmu-contexts requires --smmu-control')
    if args.smmu_firmware_counts and not args.smmu_ids:
        parser.error('--smmu-firmware-counts requires --smmu-ids')
    if args.smmu_control and not args.smmu_ids:
        parser.error('--smmu-control requires captured --smmu-ids')
    if (args.smem_version_write or args.smem_rlock_zero or args.smem_mutex or args.smem_ram_table_write) and not args.smem_sample:
        parser.error('SMEM write models require --smem-sample')
    if not 1 <= args.seconds <= 30:
        parser.error('--seconds must be 1..30')
    if args.soc_hw_version is not None and not 0 <= args.soc_hw_version <= 0xffffffff:
        parser.error('--soc-hw-version must fit in 32 bits')
    if args.psci_version is not None and not 0 <= args.psci_version <= 0x7fffffff:
        parser.error('--psci-version must fit in a nonnegative PSCI version word')
    if args.prng_word is not None and not 0 <= args.prng_word <= 0xffffffff:
        parser.error('--prng-word must fit in 32 bits')
    if args.pil_empty_region_list and not args.pmic_region_map:
        parser.error('--pil-empty-region-list requires --pmic-region-map')
    if args.hyp_log_share and not args.cmd_db_assign:
        parser.error('--hyp-log-share requires --cmd-db-assign')
    if args.cmd_db_assign:
        if not args.tz_channel_21_42_assign or not args.cmd_db_sample:
            parser.error('--cmd-db-assign requires --tz-channel-21-42-assign and --cmd-db-sample')
        if cmd_db_sample(args.cmd_db_sample)[0] != 0x80860000:
            parser.error('--cmd-db-assign requires the measured 0x80860000 pointer')
    if args.tz_channel_21_42_assign and not args.tz_channel_assign:
        parser.error('--tz-channel-21-42-assign requires --tz-channel-assign')
    if args.tz_channel_assign and not args.smem_toc_assign:
        parser.error('--tz-channel-assign requires --smem-toc-assign for the pinned SCM contract')
    if args.smem_partition_assign:
        if not args.smem_toc_assign or not args.smem_sample:
            parser.error('--smem-partition-assign requires --smem-toc-assign and --smem-sample')
        if hashlib.sha256(args.smem_sample.read_bytes()).hexdigest() != '220fa0e0619409f2bdf31c7ea79c99a777f2d6a9a5f5d9e77081b4426412dc12':
            parser.error('Partition ownership table requires the pinned nio SMEM capture')
    image = QheeImage(args.image)
    if args.smem_toc_assign and hashlib.sha256(image.data).hexdigest() != PINNED_HYP:
        parser.error('--smem-toc-assign requires the pinned nio QHEE image')
    if args.shm_bridge_handle is not None and hashlib.sha256(image.data).hexdigest() != PINNED_HYP:
        parser.error('--shm-bridge-handle requires the pinned nio QHEE image')
    pmic_region_metadata = None
    if args.pmic_region_map:
        if not args.pmic_secondary_sample or not args.hyp_log_share:
            parser.error('--pmic-region-map requires --pmic-secondary-sample and --hyp-log-share')
        try:
            requests, pmic_region_metadata = pmic_region_inventory(image,args.pmic_arb_sample,args.pmic_owner_sample,args.pmic_secondary_sample)
        except ValueError as error:
            parser.error(str(error))
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = Path(__file__).resolve().parent / 'emulator'
    try:
        entry_metadata=entry_state_model(args.entry_state_model,args.payload_address)
    except ValueError as error:
        parser.error(str(error))
    defines = ['-DDUMP_QHEE_LOG']+entry_state_defines(entry_metadata)
    replay_metadata = None
    if args.secure_state_sample:
        values, replay_metadata = secure_state_sample(args.secure_state_sample)
        defines += [f'-DSECURE_STATE_R{n}={value:#x}' for n,value in enumerate(values, 1)]
    if args.psci_version is not None:
        defines += [f'-DPSCI_MODEL_VERSION={args.psci_version:#x}']
    if args.prng_word is not None:
        defines += [f'-DPRNG_MODEL_WORD={args.prng_word:#x}']
    if args.nonsecure_query_unsupported:
        defines += ['-DNONSECURE_QUERY_UNSUPPORTED']
    if args.smem_toc_assign:
        defines += ['-DSMEM_TOC_ASSIGN_MODEL']
    if args.smem_partition_assign:
        defines += ['-DSMEM_PARTITION_ASSIGN_MODEL']
    if args.tz_channel_assign:
        defines += ['-DTZ_CHANNEL_ASSIGN_MODEL']
    if args.tz_channel_21_42_assign:
        defines += ['-DTZ_CHANNEL_21_42_ASSIGN_MODEL']
    if args.cmd_db_assign:
        defines += ['-DCMD_DB_ASSIGN_MODEL']
    if args.hyp_log_share:
        defines += ['-DHYP_LOG_SHARE_MODEL']
    if args.bridge_prng_word is not None:
        defines += [f'-DBRIDGE_PRNG_MODEL_WORD={args.bridge_prng_word:#x}']
    if args.shm_bridge_handle is not None:
        defines += [f'-DSHM_BRIDGE_MODEL_HANDLE={args.shm_bridge_handle:#x}']
    if args.handoff_prng:
        defines += ['-DHANDOFF_PRNG_MODEL']
    if args.pil_empty_region_list:
        defines += ['-DPIL_EMPTY_REGIONS_MODEL']
    if args.pmic_region_map:
        defines += ['-DPMIC_REGION_MAP_MODEL']
    if args.xbl_query_reply:defines += ['-DXBL_QUERY_REPLY_MODEL']
    buffer_reply=xbl_buffer_reply_model() if args.xbl_buffer_reply else None
    if buffer_reply:defines += ['-DXBL_BUFFER_REPLY_MODEL',f"-DXBL_BUFFER_FIXTURE_WORD={buffer_reply['buffer_word']}"]
    canary_reply=xbl_canary_reply_model() if args.xbl_canary_reply else None
    if canary_reply:defines += ['-DXBL_CANARY_REPLY_MODEL',f"-DXBL_CANARY_FIXTURE_WORD={canary_reply['buffer_word']}",f"-DXBL_CANARY_FIRST_SHIFTED_CACHE={canary_reply['first_shifted_cache']}"]
    defines += [f'-DSYNTHETIC_PAYLOAD_ADDRESS={args.payload_address:#x}']
    compile_elf(sources / 'start.S', 0x40200000, out / 'el3.elf', defines)
    xbl_metadata=None
    if args.payload_address==0x9fc00000:
        blob,xbl_metadata=xbl_payload();payload_path=out/'xbl-fv.bin';payload_path.write_bytes(blob)
        payload_loader=f'loader,file={payload_path},addr=0x9fc00000,force-raw=on'
    else:
        probe_source = sources / ('handoff_probe.S' if args.payload_address==0x90000000 else 'probe.S')
        compile_elf(probe_source, args.payload_address, out / 'probe.elf')
        payload_loader=f'loader,file={out / "probe.elf"}'
    segment = out / 'hyp-code.bin'
    try:
        code,loaded_code_metadata=loaded_code(image,args.handoff_experiment)
    except ValueError as error:
        parser.error(str(error))
    segment.write_bytes(code)
    qemu, env = environment(args.qemu)
    cmd = [str(qemu), '-M', 'virt,secure=on,virtualization=on,gic-version=3',
        '-cpu', 'cortex-a76', '-m', '2G', '-smp', '1', '-accel', 'tcg',
        '-display', 'none', '-serial', 'stdio', '-monitor', 'none', '-nic', 'none',
        '-semihosting-config', 'enable=on,target=native', '-no-reboot',
        '-device', f'loader,file={out / "el3.elf"},cpu-num=0',
        '-device', payload_loader,
        '-device', f'loader,file={segment},addr={image.code.vaddr:#x},force-raw=on']
    if args.xbl_workspace_sentinel:
        for address,data,name in xbl_sentinel():
            path=out/('xbl-workspace-'+name+'.bin');path.write_bytes(data)
            cmd += ['-device', f'loader,file={path},addr={address:#x},force-raw=on']
    selector_metadata=None;selector_props=''
    if args.xbl_selector_sample:
        try:selector_value,selector_metadata=xbl_selector_sample(args.xbl_selector_sample)
        except (ValueError,OSError) as e:parser.error(str(e))
        selector_props=f',selector-replay=on,selector-value={selector_value:#x}'
    if args.soc_hw_version is not None:
        cmd += ['-device', f'nio-soc-version,value={args.soc_hw_version:#x}{selector_props}']
    qfprom_metadata = None
    if args.qfprom_sample:
        value, qfprom_metadata = qfprom_sample(args.qfprom_sample)
        cmd += ['-device', f'nio-qfprom,value={value:#x}']
    cmd_db_metadata = None
    if args.cmd_db_sample:
        value, cmd_db_metadata = cmd_db_sample(args.cmd_db_sample)
        cmd += ['-device', f'nio-cmd-db-pointer,value={value:#x}']
    tz_log_metadata = None
    readiness_metadata=None;readiness_props=''
    if args.xbl_readiness_sample:
        try:flag,readiness_metadata=xbl_readiness_sample(args.xbl_readiness_sample)
        except ValueError as e:parser.error(str(e))
        readiness_props=f',sec-flag-replay=on,sec-flag-value={flag:#x}'
    if args.tz_log_sample:
        value, tz_log_metadata = tz_log_sample(args.tz_log_sample)
        cmd += ['-device', f'nio-tz-log-pointer,value={value:#x},publications={"on" if args.imem_publications else "off"},ready-publication={"on" if args.imem_ready_publication else "off"}{readiness_props}']
    pmic_metadata = pmic_owner_metadata = pmic_secondary_metadata = None
    if args.pmic_arb_sample:
        blob, pmic_metadata = pmic_sample(args.pmic_arb_sample)
        snapshot_path = out / 'pmic-apid.bin'
        snapshot_path.write_bytes(blob)
        options = f'nio-pmic-arb,snapshot={snapshot_path}'
        if args.pmic_owner_sample:
            owner_blob, pmic_owner_metadata = pmic_owner_sample(args.pmic_owner_sample)
            owner_path = out / 'pmic-owners.bin'
            owner_path.write_bytes(owner_blob)
            options += f',owners={owner_path}'
        if args.pmic_secondary_sample:
            secondary_blob, pmic_secondary_metadata = pmic_secondary_sample(args.pmic_secondary_sample)
            secondary_path = out / 'pmic-secondary.bin'
            secondary_path.write_bytes(secondary_blob)
            options += f',secondary={secondary_path}'
        cmd += ['-device', options]
    mmu_metadata = None
    if args.gcc_mmu_clocks:
        options = f'nio-gcc-mmu,initially-enabled={args.gcc_mmu_clocks}'
        if args.qcom_timer:
            options += ',timer=on'
        if args.smmu_control:
            options += ',control=on'
        if args.smmu_contexts:
            options += ',contexts=on'
        if args.smmu_ids:
            properties,mmu_metadata = smmu_ids_sample(args.smmu_ids)
            if args.smmu_firmware_counts:
                properties, derived = firmware_counts(properties, image)
                mmu_metadata['firmware_count_hypothesis'] = derived
            options += ',ids-enabled=on'+''.join(f',{k}={v:#x}' for k,v in properties.items())
        cmd += ['-device', options]
    smem_metadata = None
    if args.smem_sample:
        snapshot_path = out / 'smem-snapshot.bin'
        smem_metadata = smem_snapshot(args.smem_sample, snapshot_path)
        smem_metadata['version_write_model'] = args.smem_version_write
        smem_metadata['rlock_zero_model'] = args.smem_rlock_zero
        smem_metadata['mutex9_model'] = args.smem_mutex
        smem_metadata['ram_table_write_model'] = args.smem_ram_table_write
        if args.smem_version_write:
            smem_metadata['policy'] = 'Captured bytes readable; only 32-bit header.version[0] writes modeled; all other accesses abort'
        if args.smem_rlock_zero:
            smem_metadata['rlock_assumption'] = 'Item 404 has private zero-initialized read/write backing; no remote CPUs or measured lock state'
            smem_metadata['policy'] += '; item 404 explicitly replaced with zero-initialized read/write memory'
        if args.smem_mutex:
            smem_metadata['mutex_assumption'] = 'TCSR mutex 9 initially free; claim/read-owner/release; no remote contenders'
        if args.smem_ram_table_write:
            smem_metadata['policy'] += '; writes to the private copy of captured item 402 enabled'
        properties = {'version-write':args.smem_version_write, 'rlock-zero':args.smem_rlock_zero,
                      'mutex-model':args.smem_mutex, 'ram-table-write':args.smem_ram_table_write}
        cmd += ['-device', f'nio-smem,snapshot={snapshot_path}'+''.join(f',{k}={"on" if v else "off"}' for k,v in properties.items())]
    devcfg_metadata = None
    if args.devcfg:
        devcfg = QheeImage(args.devcfg)
        matches = [s for s in devcfg.segments if s.vaddr == 0x805fd000]
        if len(matches) != 1 or matches[0].memsz > 0x3000:
            parser.error('--devcfg must contain a single bounded QHEE segment at 0x805fd000')
        s = matches[0]
        data = devcfg.data[s.file_off:s.file_off+s.filesz] + bytes(s.memsz-s.filesz)
        path = out / 'devcfg-hyp.bin'
        path.write_bytes(data)
        cmd += ['-device', f'loader,file={path},addr={s.vaddr:#x},force-raw=on']
        devcfg_metadata = {'image_sha256':hashlib.sha256(devcfg.data).hexdigest(),
            'segment_sha256':hashlib.sha256(data).hexdigest(), 'address':hex(s.vaddr),
            'file_offset':hex(s.file_off), 'filesz':s.filesz, 'memsz':s.memsz,
            'scope':'QHEE segment only; TZ segment is not loaded or executed'}
    if args.trace:
        cmd += ['-d', 'in_asm', '-D', str(out / 'trace.txt')]
    if args.prepare_only:
        stdout,stderr,status,rc=b'',b'','prepared',None
    else:
        try:
            result = subprocess.run(cmd, capture_output=True, env=env, timeout=args.seconds)
            stdout, stderr, status = result.stdout, result.stderr, 'exited'
            rc = result.returncode
        except subprocess.TimeoutExpired as error:
            stdout, stderr, status, rc = error.stdout or b'', error.stderr or b'', 'timeout', None
    (out / 'stdout.txt').write_bytes(stdout)
    (out / 'stderr.txt').write_bytes(stderr)
    metadata = {'image_sha256':hashlib.sha256(image.data).hexdigest(),
        'qemu':subprocess.check_output([str(qemu), '--version'], env=env, text=True).splitlines()[0],
        'command':cmd, 'status':status, 'exit':rc,
        'outcome':'prepared_not_executed' if args.prepare_only else classify_output(stdout, rc, status, stderr if args.payload_address==0x90000000 else b''),
        'stop':decode_stop(stdout),
        'soc_hw_version_model':hex(args.soc_hw_version) if args.soc_hw_version is not None else None,
        'devcfg':devcfg_metadata,
        'cmd_db_pointer_replay':cmd_db_metadata,
        'tz_log_pointer_replay':tz_log_metadata,
        'pmic_apid_replay':pmic_metadata,
        'pmic_owner_replay':pmic_owner_metadata,
        'pmic_secondary_replay':pmic_secondary_metadata,
        'bridge_prng_model':({'word':hex(args.bridge_prng_word), 'accepted_requests':stdout.count(b'MODEL_BRIDGE_PRNG_FIXED_WORD_NOT_ENTROPY\n'), 'scope':'One exact 8-byte PRNG request inside the created synthetic bridge; fixed non-entropy input'} if args.bridge_prng_word is not None else None),
        'loaded_code':loaded_code_metadata,
        'entry_state_model':entry_metadata,
        'xbl_payload':xbl_metadata,
        'xbl_query_reply_model':xbl_query_reply_model() if args.xbl_query_reply else None,
        'xbl_buffer_reply_model':buffer_reply,
        'xbl_canary_reply_model':canary_reply,
        'xbl_readiness_sample':readiness_metadata,
        'xbl_selector_sample':selector_metadata,
        'xbl_workspace_sentinel':xbl_sentinel_metadata() if args.xbl_workspace_sentinel else None,
        'synthetic_payload':{'address':hex(args.payload_address),'transport':'original-XBL-prefix' if xbl_metadata else ('semihosting' if args.payload_address==0x90000000 else 'UART'),'scope':'Synthetic incoming x0; original XBL FV at configured candidate when selected, otherwise a diagnostic probe; not a captured phone boot-chain target'},
        'shm_bridge_model':({'handle':hex(args.shm_bridge_handle), 'accepted_creates':stdout.count(b'MODEL_SHM_BRIDGE_CREATE_ASSUMED_SUCCESS\n'), 'scope':'Exact one-shot scalar bridge create reply; transport/service success assumed, synthetic opaque handle, no TZ memory access enforcement or generic bridge APIs'} if args.shm_bridge_handle is not None else None),
        'handoff_prng_model':({'accepted_requests':stdout.count(b'MODEL_HANDOFF_PRNG_FIXED_WORD_NOT_ENTROPY\n'),'scope':'Three exact sequential PRNG buffers at 0x80095a60 (4B), 0x801ccaa8/aaa (2B each); deterministic non-entropy input, no physical TZ reply'} if args.handoff_prng else None),
        'pil_empty_region_list_model':({'accepted_queries':stdout.count(b'MODEL_PIL_EMPTY_REGION_LIST_ASSUMPTION\n'), 'scope':'Unmeasured empty-region-list experiment for exact PIL query 0x4200020e; no protected-memory clearing or physical TZ evidence'} if args.pil_empty_region_list else None),
        'pmic_region_map_model':({**pmic_region_metadata, 'accepted_requests':stdout.count(b'MODEL_PMIC_REGION_MAP_VMID2_RW\n')} if args.pmic_region_map else None),
        'imem_publications_model':({'scope':'Exact one-shot log publication at 0x146bfb30 and optional ready pointer at 0x146bfb20, requiring prior log publication; no general IMEM storage',
            'log_publications':stderr.count(b'NIO_IMEM_HYP_LOG_PUBLISH'),
            'ready_publication_enabled':args.imem_ready_publication, 'ready_publications':stderr.count(b'NIO_IMEM_QHEE_READY_PUBLISH')} if args.imem_publications else None),
        'qfprom_replay':qfprom_metadata,
        'gcc_mmu_clocks_model':args.gcc_mmu_clocks,
        'smmu_ids':mmu_metadata,
        'qcom_timer_model':args.qcom_timer,
        'smmu_contexts_model':args.smmu_contexts,
        'smmu_control_model':({'scope':'Whitelist of reset/configuration registers, initial zero state; TLB completes with no DMA clients',
                               'dma_translation':False} if args.smmu_control else None),
        'smem':smem_metadata,
        'secure_state_replay':replay_metadata,
        'smem_partition_assign_model':({'accepted_transitions':stdout.count(b'MODEL_SMEM_PARTITION_ASSIGN_EXACT\n'),
            'scope':'Exact ten captured partition boundaries and original-QHEE destination records; each initial owner assumed VMID 3; per-owner read/write masks; no access enforcement'} if args.smem_partition_assign else None),
        'hyp_log_share_model':({'region':{'start':'0x80209000','size':'0x2000'},
            'initial_owners':[4],'destination_permissions':{'3':4,'4':6},
            'accepted_transitions':stdout.count(b'MODEL_HYP_LOG_SHARE\n'),
            'scope':'Exact QHEE log ownership ledger; initial ownership and successful TZ acceptance assumed; no access enforcement'} if args.hyp_log_share else None),
        'cmd_db_assign_model':({'region':{'start':'0x80860000','size':'0x20000'},
            'initial_owners':[3],'destination_owners':[1,2,5,3,6,26,30,22],'permission':4,
            'accepted_transitions':stdout.count(b'MODEL_CMD_DB_ASSIGN_READ_ONLY\n'),
            'scope':'Exact command-database ownership ledger; initial ownership and successful TZ acceptance assumed; no contents or access enforcement'} if args.cmd_db_assign else None),
        'tz_channel_21_42_assign_model':({'region':{'start':'0x80ddc000','size':'0x2000'},
            'descriptor':'0x800a2ca8','initial_owners':[3],'destination_owners':[21,42],'permission':6,
            'accepted_transitions':stdout.count(b'MODEL_TZ_CHANNEL_VMID21_42_ASSIGN\n'),
            'scope':'Exact second TZ-subsystem channel ledger; ownership and successful TZ acceptance assumed; no channel contents or access enforcement'} if args.tz_channel_21_42_assign else None),
        'tz_channel_assign_model':({'region':{'start':'0x80dc1000','size':'0x1000'},
            'descriptor':'0x800a2c70','initial_owners':[3],'destination_owners':[21,22],'permission':6,
            'accepted_transitions':stdout.count(b'MODEL_TZ_CHANNEL_VMID21_22_ASSIGN\n'),
            'scope':'Exact TZ-subsystem channel ownership ledger; initial ownership and successful TZ acceptance assumed; no secure-channel contents or access enforcement'} if args.tz_channel_assign else None),
        'smem_toc_assign_model':({'region':{'start':'0x80aff000','size':'0x1000'},
            'initial_owners':[3], 'initial_permissions':'unknown',
            'destination_owners':[3,6,5,30,27,4,40,26], 'destination_permission':4,
            'accepted_transitions':stdout.count(b'MODEL_SMEM_TOC_ASSIGN_READ_ONLY_8_OWNERS\n'),
            'scope':'Exact pinned caller and buffers, one transition; synthetic ledger only; no access enforcement or guest memory writes',
            'assumptions':['Initial owner VMID 3 inferred from request, not captured TZ state',
                           'Successful TZ transport/service result is an explicit experiment']}
            if args.smem_toc_assign else None),
        'nonsecure_query_model':('Explicit unsupported (-1) failure-path assumption; not a device-security state' if args.nonsecure_query_unsupported else None),
        'psci_version_model':hex(args.psci_version) if args.psci_version is not None else None,
        'prng_model':({'word':hex(args.prng_word),'buffers':{'0x80095a28':4,'0x801cc5d0':2,'0x801cc5d2':2},
                       'scope':'Deterministic heap-init test input; not cryptographic entropy; other requests stop'}
                      if args.prng_word is not None else None),
        'tool_sha256':provenance(qemu, sources),
        'stdout':stdout.decode(errors='replace'), 'stderr':stderr.decode(errors='replace'),
        'scope':'Pinned QHEE on QEMU virt with synthetic EL3, RAM and HLOS probe; any loaded-code experiment is separately reported. Not SM8250 emulation.',
        'limitations':['No actual Qualcomm secure monitor; optional recorded response replay only', 'Only one modeled CPU',
            'SoC register CLI value requires separate hardware provenance; this run is an emulation',
            'EL3 arguments/SCR are assumptions, not captured TZ state', 'No inference of phone patch safety']}
    (out / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
