#!/usr/bin/env python3
"""Read-only original-QHEE bridge consumer checkpoints and execution across ERET."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
from qhee import DEFAULT_IMAGE, QheeImage
from handoff import loaded_code
from run_qemu import environment
from smmu_config import PINNED_HYP
from xbl_target import payload as xbl_payload
from tz_query import reply_model as query_reply_model
from tz_buffer import reply_model as buffer_reply_model
from xbl_cache import contract as cache_contract, POINTS as CACHE_POINTS, STOP as CACHE_STOP
from xbl_canary import contract as canary_contract, reply_model as canary_reply_model, POINTS as CANARY_POINTS, STOP as CANARY_STOP
from entry_state import model as entry_state_model
from xbl_selector import sample as selector_sample, contract as selector_contract, POINTS as SELECTOR_POINTS, STOP as SELECTOR_STOP
from xbl_counter import contract as counter_contract, POINTS as COUNTER_POINTS, STOP as COUNTER_STOP
from xbl_readiness import sample as readiness_sample, contract as readiness_contract, POINTS as READINESS_POINTS, STOP as READINESS_STOP
from xbl_stack import contract as stack_contract, POINTS as STACK_POINTS, STOP as STACK_STOP, buffer_contract, BUFFER_POINTS, BUFFER_STOP, return_contract, RETURN_POINTS, RETURN_STOP
from xbl_startup import contract as startup_contract, POINTS as STARTUP_POINTS, STOP as STARTUP_STOP, sentinel as workspace_sentinel, sentinel_metadata

POINTS={0x80054eec:'bridge-transport-return',0x80054f30:'bridge-handle-stored',
    0x800495a8:'bridge-bookkeeping-return',0x80040174:'bridge-helper-return',
    0x80040178:'canary-buffer-init-return',0x8004017c:'canary-refresh-return',
    0x800401bc:'payload-target-setup',0x80040328:'before-payload-eret'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--inspect-entry',action='store_true',help='read-only initial ERET/QHEE-entry inspection; automatic for TZ-frame controls')
    bounds=p.add_mutually_exclusive_group()
    bounds.add_argument('--xbl-prefix',action='store_true',help='continue read-only through original SEC VBAR setup, then stop before BSS/platform initialization')
    bounds.add_argument('--xbl-startup',action='store_true',help='original SEC through vector/BSS/temporary-stack setup; stop before 0x9fc0cf28 stack-sizing call')
    bounds.add_argument('--xbl-stack-smc',action='store_true',help='continue original SEC through stack-sizing dispatcher; stop before first availability SMC')
    bounds.add_argument('--xbl-stack-buffer',action='store_true',help='with exact query reply model, continue original XBL to its eight-byte buffer SMC')
    bounds.add_argument('--xbl-stack-return',action='store_true',help='with exact query and buffer fixture replies, trace original stack-sizing return and SP adjustment')
    bounds.add_argument('--xbl-cache-startup',action='store_true',help='original set/way and cache enabling through second canary buffer SMC; no second reply')
    bounds.add_argument('--xbl-canary-return',action='store_true',help='with exact second fixture reply, trace original canary store and SEC main through first readiness read boundary')
    bounds.add_argument('--xbl-readiness',action='store_true',help='one measured postboot hold-flag replay, original loop exit/platform prologue, stop before CNTVCT')
    bounds.add_argument('--xbl-counter',action='store_true',help='execute original CNTVCT and fixed-frequency conversion, stop before platform-selection MMIO')
    bounds.add_argument('--xbl-selector',action='store_true',help='one measured selector replay, original descriptor selection/table match, stop before selected MMIO read')
    p.add_argument('--inspect-xbl-next-step',action='store_true',help='at counter bound, take one normal MMIO instruction step; inspect result or exception without running handler')
    p.add_argument('--inspect-xbl-smc-route',action='store_true',help='at bounded query/buffer/canary boundary, take one normal SMC step and inspect exception entry without executing its handler')
    p.add_argument('--inspect-xbl-qhee-forward',action='store_true',help='with stock EL1 and SMC routing inspection, stop at original QHEE forwarding SMC or XBL query return; no response model')
    args=p.parse_args();m=json.loads(args.manifest.read_text());bounded_xbl=args.xbl_prefix or args.xbl_startup or args.xbl_stack_smc or args.xbl_stack_buffer or args.xbl_stack_return or args.xbl_cache_startup or args.xbl_canary_return or (args.xbl_readiness or (args.xbl_counter or args.xbl_selector))
    if args.inspect_xbl_next_step and not (args.xbl_counter or args.xbl_selector):p.error('--inspect-xbl-next-step requires --xbl-counter or --xbl-selector')
    if args.inspect_xbl_smc_route and not (args.xbl_stack_smc or args.xbl_stack_buffer or args.xbl_cache_startup):p.error('--inspect-xbl-smc-route requires --xbl-stack-smc or --xbl-stack-buffer or --xbl-cache-startup')
    if m['image_sha256']!=PINNED_HYP or hashlib.sha256(DEFAULT_IMAGE.read_bytes()).hexdigest()!=PINNED_HYP:
        p.error('Requires pinned original QHEE')
    if not m.get('shm_bridge_model') or not m.get('bridge_prng_model'):
        p.error('Requires explicit bridge and bridge PRNG models')
    code,expected_metadata=loaded_code(QheeImage(),(m.get('loaded_code') or {}).get('experiment'))
    if args.inspect_xbl_qhee_forward and not (args.inspect_xbl_smc_route and (args.xbl_stack_smc or args.xbl_stack_buffer or args.xbl_cache_startup) and expected_metadata['experiment'] is None):
        p.error('--inspect-xbl-qhee-forward requires stock EL1 --xbl-stack-smc or --xbl-stack-buffer or --xbl-cache-startup and --inspect-xbl-smc-route')
    forward_sites=[0x80040000+offset for offset in range(0,len(code)-3,4) if int.from_bytes(code[offset:offset+4],'little')&0xffe0001f==0xd4000003]
    loaded_path=args.manifest.resolve().parent/'hyp-code.bin'
    if m.get('loaded_code') is not None and m['loaded_code']!=expected_metadata:p.error('Loaded-code metadata mismatch')
    if loaded_path.read_bytes()!=code:p.error('Unexpected loaded QHEE code bytes')
    target=int(m.get('synthetic_payload',{}).get('address','0'),16)
    entry_metadata=m.get('entry_state_model')
    if entry_metadata:
        try:expected_entry=entry_state_model(entry_metadata['name'],target)
        except (ValueError,KeyError) as error:p.error('Invalid entry-state metadata: '+str(error))
        if entry_metadata!=expected_entry:p.error('Entry-state metadata mismatch')
    else:expected_entry=entry_state_model(target=target)
    inspect_entry=args.inspect_entry or expected_entry['name']!='synthetic-masked'
    if bounded_xbl:
        if target!=0x9fc00000:p.error('Bounded XBL trace requires original XBL payload')
        blob,xbl_metadata=xbl_payload()
        if m.get('xbl_payload')!=xbl_metadata:p.error('XBL payload metadata mismatch')
        if (args.manifest.resolve().parent/'xbl-fv.bin').read_bytes()!=blob:p.error('Unexpected loaded XBL bytes')
        directory=args.manifest.resolve().parent
        expected_loaders=(f'loader,file={directory / "xbl-fv.bin"},addr=0x9fc00000,force-raw=on',
            f'loader,file={directory / "hyp-code.bin"},addr=0x80040000,force-raw=on',f'loader,file={directory / "el3.elf"},cpu-num=0')
        if any(m['command'].count(loader)!=1 for loader in expected_loaders):p.error('Unexpected XBL prefix loader command')
    elif target==0x9fc00000:p.error('Original XBL payload requires bounded --xbl-prefix trace')
    workspace=m.get('xbl_workspace_sentinel')
    if workspace:
        if not bounded_xbl or workspace!=sentinel_metadata():p.error('XBL workspace sentinel metadata mismatch')
        for address,data,name in workspace_sentinel():
            path=args.manifest.resolve().parent/('xbl-workspace-'+name+'.bin')
            if path.read_bytes()!=data:p.error('Unexpected XBL workspace sentinel bytes')
            loader=f'loader,file={path},addr={address:#x},force-raw=on'
            if m['command'].count(loader)!=1:p.error('Unexpected XBL workspace sentinel loader')
    if not workspace and any('xbl-workspace-' in part for part in m['command']):
        p.error('Unreported XBL workspace sentinel loader')
    query=m.get('xbl_query_reply_model')
    if query and query!=query_reply_model():p.error('XBL query reply metadata mismatch')
    if args.xbl_stack_buffer and not query:p.error('--xbl-stack-buffer requires exact XBL query reply model')
    buffer_reply=m.get('xbl_buffer_reply_model')
    if buffer_reply and buffer_reply!=buffer_reply_model():p.error('XBL buffer reply metadata mismatch')
    if buffer_reply and not query:p.error('XBL buffer reply requires query metadata')
    if (args.xbl_stack_return or args.xbl_cache_startup or args.xbl_canary_return or (args.xbl_readiness or (args.xbl_counter or args.xbl_selector))) and not buffer_reply:p.error('--xbl-stack-return/--xbl-cache-startup requires exact XBL buffer reply model')
    canary_reply=m.get('xbl_canary_reply_model')
    if canary_reply and canary_reply!=canary_reply_model():p.error('XBL canary reply metadata mismatch')
    if canary_reply and not buffer_reply:p.error('XBL canary reply requires buffer metadata')
    if args.xbl_canary_return and not canary_reply:p.error('--xbl-canary-return requires exact second XBL canary reply model')
    readiness_metadata=m.get('xbl_readiness_sample')
    if readiness_metadata:
        try:_,expected_readiness=readiness_sample(Path(readiness_metadata['path']))
        except (ValueError,KeyError,OSError) as e:p.error('Invalid SEC flag sample: '+str(e))
        if readiness_metadata!=expected_readiness:p.error('SEC flag sample metadata mismatch')
        flag_props=f",sec-flag-replay=on,sec-flag-value={int(readiness_metadata['value'],16):#x}"
        devices=[v for v in m['command'] if v.startswith('nio-tz-log-pointer,')]
        if len(devices)!=1 or not devices[0].endswith(flag_props) or 'publications=on,ready-publication=on' not in devices[0]:p.error('SEC flag device command mismatch')
    elif any('sec-flag-' in v for v in m['command']):p.error('Unreported SEC flag device options')
    if (args.xbl_readiness or (args.xbl_counter or args.xbl_selector)) and not (canary_reply and readiness_metadata):p.error('--xbl-readiness requires exact canary reply and measured SEC flag sample')
    selector_metadata=m.get('xbl_selector_sample')
    if selector_metadata:
        try:selector_value,expected_selector=selector_sample(Path(selector_metadata['path']))
        except (ValueError,KeyError,OSError) as e:p.error('Invalid SEC selector sample: '+str(e))
        if selector_metadata!=expected_selector:p.error('SEC selector sample metadata mismatch')
        props=f",selector-replay=on,selector-value={selector_value:#x}"
        devices=[v for v in m['command'] if v.startswith('nio-soc-version,')]
        expected_device=f"nio-soc-version,value={int(m['soc_hw_version_model'],16):#x}"+props if m.get('soc_hw_version_model') else None
        if devices!=[expected_device]:p.error('SEC selector device command mismatch')
        if not (canary_reply and readiness_metadata):p.error('SEC selector requires earlier reply/readiness metadata')
    elif any('selector-replay' in v or 'selector-value' in v for v in m['command']):p.error('Unreported SEC selector device options')
    if args.xbl_selector and not selector_metadata:p.error('--xbl-selector requires exact measured selector sample')
    selector=selector_contract(selector_value) if args.xbl_selector else None
    readiness=readiness_contract() if (args.xbl_readiness or (args.xbl_counter or args.xbl_selector)) else None
    canary=canary_contract() if args.xbl_canary_return or (args.xbl_readiness or (args.xbl_counter or args.xbl_selector)) else None
    startup=startup_contract() if args.xbl_startup or args.xbl_stack_smc or args.xbl_stack_buffer or args.xbl_stack_return or args.xbl_cache_startup or args.xbl_canary_return or (args.xbl_readiness or (args.xbl_counter or args.xbl_selector)) else None
    stack=stack_contract() if args.xbl_stack_smc or args.xbl_stack_buffer or args.xbl_stack_return or args.xbl_cache_startup or args.xbl_canary_return or (args.xbl_readiness or (args.xbl_counter or args.xbl_selector)) else None
    buffer=buffer_contract() if args.xbl_stack_buffer or args.xbl_stack_return or args.xbl_cache_startup or args.xbl_canary_return or (args.xbl_readiness or (args.xbl_counter or args.xbl_selector)) else None
    stack_return=return_contract(int(buffer_reply['buffer_word'],16)) if args.xbl_stack_return or args.xbl_cache_startup or args.xbl_canary_return or (args.xbl_readiness or (args.xbl_counter or args.xbl_selector)) else None
    cache=cache_contract() if args.xbl_cache_startup or args.xbl_canary_return or (args.xbl_readiness or (args.xbl_counter or args.xbl_selector)) else None
    points=dict(POINTS)
    if expected_metadata['experiment'] in ('el2-diag-mmu-off','el2-xbl-mmu-off','el2-diag-masked-mmu-off','el2-xbl-masked-mmu-off'):
        del points[0x80040328]
        transition_points={0x800402b0:'diagnostic-transition-entry'}
        if expected_metadata['terminal_transition']['mask_daif_before_clean']:
            transition_points[0x800402b4]='after-daif-mask'
        transition_points.update({0x80040310:'before-sctlr-disable',0x80040314:'after-sctlr-disable',0x80040328:'before-payload-eret'})
        points.update(transition_points)
    initial_transition_state=int(expected_entry['controls']['SPSR_EL3'],16) if expected_metadata.get('terminal_transition',{}).get('mask_daif_before_clean') else 0x3c9
    clean_ranges=[tuple(int(v,16) for v in r) for r in expected_metadata.get('terminal_transition',{}).get('clean_ranges',[])]
    prefix_points={0x9fc0cd80:'sec-startup',0x9fc0cd98:'sec-after-mci-disable',0x9fc0cda4:'sec-current-el-read',
        0x9fc0ce7c:'sec-common-path',0x9fc0cea8:'sec-before-hcr-write',0x9fc0ceac:'sec-after-el2-branch',0x9fc0ceb4:'sec-after-vbar-setup'} if bounded_xbl else {}
    if bounded_xbl and expected_metadata['experiment'] is None:del prefix_points[0x9fc0cea8]
    if startup:prefix_points.update(STARTUP_POINTS)
    if stack:prefix_points.update(STACK_POINTS)
    if buffer:prefix_points.update(BUFFER_POINTS)
    if stack_return:prefix_points.update(RETURN_POINTS)
    if cache:prefix_points.update(CACHE_POINTS)
    counter=counter_contract() if (args.xbl_counter or args.xbl_selector) else None
    sec_stop=SELECTOR_STOP if selector else COUNTER_STOP if counter else READINESS_STOP if readiness else CANARY_STOP if canary else CACHE_STOP if cache else (RETURN_STOP if stack_return else (BUFFER_STOP if buffer else (STACK_STOP if stack else (STARTUP_STOP if startup else 0x9fc0ceb4))))
    el3=args.manifest.resolve().parent/'el3.elf'
    symbols={n:int(a,16) for a,n in re.findall(r'^([0-9a-f]+) . (\w+)$',subprocess.check_output(
        ['aarch64-linux-gnu-nm',str(el3)],text=True),re.M)}
    initial_eret=symbols.get('qhee_initial_eret')
    if inspect_entry and initial_eret is None:p.error('Missing initial entry inspection symbol')
    names=('shm_bridge_ledger','bridge_prng_count','pmic_region_map_count','pmic_region_map_ledger','handoff_prng_count','pil_empty_regions_count')
    if any(n not in symbols for n in names):p.error('Missing required model symbols')
    if query:
        if 'xbl_query_count' not in symbols:p.error('Missing exact XBL query model symbol')
        names+=('xbl_query_count',)
    if buffer_reply:
        if 'xbl_buffer_count' not in symbols:p.error('Missing exact XBL buffer model symbol')
        names+=('xbl_buffer_count',)
    if canary_reply:
        if 'xbl_canary_count' not in symbols:p.error('Missing exact XBL canary model symbol')
        names+=('xbl_canary_count',)
    symbols={n:symbols[n] for n in names};command=m['command'][:]
    for flag in ('-d','-D'):
        if flag in command:i=command.index(flag);del command[i:i+2]
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    script='''set architecture aarch64
set pagination off
set confirm off
set remotetimeout 5
target remote 127.0.0.1:PORT
python
import gdb,json,re,struct,hashlib
from pathlib import Path
points=POINTS;symbols=SYMBOLS;checkpoints=[];calls=[];transition_mappings=[];prefix_points=PREFIX_POINTS;prefix=[];startup=STARTUP_CONTRACT;workspace=WORKSPACE_SENTINEL;workspace_before=None;stack=STACK_CONTRACT;call_phase='cold';forward_calls=[];buffer=BUFFER_CONTRACT;stack_return=RETURN_CONTRACT;buffer_reply=BUFFER_REPLY_MODEL;cache=CACHE_CONTRACT;cache_geometry=[];cache_ready=False;canary=CANARY_CONTRACT;canary_reply=CANARY_REPLY_MODEL;canary_points=CANARY_POINTS;second_request_seen=False;readiness=READINESS_CONTRACT;readiness_meta=READINESS_META;readiness_points=READINESS_POINTS;counter=COUNTER_CONTRACT;counter_points=COUNTER_POINTS;selector=SELECTOR_CONTRACT;selector_meta=SELECTOR_META;selector_points=SELECTOR_POINTS
def reg(n):
    # GDB exposes CPSR as signed 32-bit when N=1; preserve architectural width.
    try:return int(gdb.parse_and_eval('$'+n))&((1<<(32 if n=='cpsr' else 64))-1)
    except Exception as e:raise RuntimeError('Cannot read register '+n) from e
def snapshot():return {n:hex(reg(n)) for n in [f'x{i}' for i in range(31)]+['pc','sp','cpsr','SCTLR_EL2','TCR_EL2','TTBR0_EL2','MAIR_EL2','CTR_EL0','HCR_EL2','VTCR_EL2','VTTBR_EL2','SPSR_EL2','ELR_EL2','SCTLR','ESR_EL2','FAR_EL2','HPFAR_EL2','VBAR_EL2']}
def bounded_word(a):
    if a&7 or not 0x80040000<=a<=0x8028aff8:raise RuntimeError('Unexpected handle output pointer')
    return struct.unpack('<Q',bytes(gdb.selected_inferior().read_memory(a,8)))[0]
def phys(a):
    text=gdb.execute('monitor xp /1gx '+hex(a),to_string=True)
    match=re.search(r'[0-9a-fA-F]+:\\s+(0x[0-9a-fA-F]+)',text)
    if not match:raise RuntimeError('Cannot read physical ledger')
    return int(match[1],16)
def transition_mapping_check():
    if reg('TCR_EL2')!=0x8081351c:raise RuntimeError('Unexpected transition translation regime')
    cache={};result=[]
    for start,end in CLEAN_RANGES:
        pages=[]
        for va in range(start,end,4096):
            base=reg('TTBR0_EL2')&0x0000fffffffff000
            for level,shift in ((1,30),(2,21),(3,12)):
                a=base+8*((va>>shift)&511)
                if a not in cache:cache[a]=phys(a)
                pte=cache[a]
                if not pte&1:raise RuntimeError('Invalid transition mapping')
                if pte&3!=3 or level==3:break
                base=pte&0x0000fffffffff000
            if (level==3 and pte&3!=3) or (level<3 and pte&3!=1):raise RuntimeError('Invalid transition leaf')
            pa=(pte&0x0000ffffffffffff&~((1<<shift)-1))|(va&((1<<shift)-1))
            attr=(reg('MAIR_EL2')>>(8*((pte>>2)&7)))&255
            normal=bool(attr>>4 and attr&15)
            executable=not bool(pte&(1<<54)) and not bool(reg('SCTLR_EL2')&(1<<19) and not pte&(1<<7))
            if pa!=va or not normal:raise RuntimeError('Transition needs identity Normal-memory mapping')
            if va==0x80040000 and not executable:raise RuntimeError('Terminal transition is not executable')
            pages.append({'va':hex(va),'pa':hex(pa),'level':level,'pte':hex(pte),'mair_attribute':hex(attr),'executable':executable})
        result.append({'start':hex(start),'end_exclusive':hex(end),'pages':pages})
    return result
class Calls(gdb.Breakpoint):
    def stop(self):
        call={'args':[hex(reg(f'x{i}')) for i in range(8)]}
        if reg('x0')==0xc2000c19:
            if reg('x5')!=0x801cc390:raise RuntimeError('Unexpected PMIC extended pointer')
            call['extended']=list(struct.unpack('<2Q',bytes(gdb.selected_inferior().read_memory(0x801cc390,16))))
        (calls if call_phase=='cold' else forward_calls).append(call);return False
class Point(gdb.Breakpoint):
    def stop(self):
        pc=reg('pc');r={'name':points[pc],'registers':snapshot()}
        if pc==0x80054eec:r['service_and_handle']=[hex(bounded_word(reg('sp')+offset)) for offset in (0x40,0x48)]
        if pc==0x80054f30:r['stored_handle']=hex(bounded_word(reg('x19')))
        if pc==0x800495a8:r['stored_handle']=hex(bounded_word(reg('x29')-16))
        if pc==0x80040174:
            r['bridge_bookkeeping_root_first32_hex']=bytes(gdb.selected_inferior().read_memory(0x801e4eb8,32)).hex()
            node=bounded_word(0x801e4eb8)
            if not 0x80040000<=node<=0x8028afb8:raise RuntimeError('Unexpected bridge bookkeeping node')
            r['bridge_bookkeeping_node_address']=hex(node)
            r['bridge_bookkeeping_node_hex']=bytes(gdb.selected_inferior().read_memory(node,72)).hex()
        if pc in (0x80040178,0x8004017c):r['stack_canary']=hex(bounded_word(0x80095a48))
        if pc==0x800402b0:
            if reg('cpsr')&0x3cf!=TRANSITION_ENTRY_STATE or reg('SPSR_EL2')!=0x3c9 or reg('ELR_EL2')!=PAYLOAD_TARGET:
                raise RuntimeError('Unexpected diagnostic CPU0/AArch64/masked entry state')
            transition_mappings.extend(transition_mapping_check())
        if pc==0x800402b4 and reg('cpsr')&0x3cf!=0x3c9:
            raise RuntimeError('Terminal DAIF mask not established before cache maintenance')
        checkpoints.append(r);self.enabled=False
        return pc==0x80040328
Calls('*0x80041aa0')
for pc in points:Point('*'+hex(pc))
def workspace_read():
    result=[]
    for region in startup['ranges']:
        a=int(region['address'],16);n=region['size']
        data=bytes(gdb.selected_inferior().read_memory(a-16,n+32))
        result.append({'name':region['name'],'address':hex(a),'size':n,
                       'sha256':hashlib.sha256(data[16:-16]).hexdigest(),
                       'first16_hex':data[16:32].hex(),'last16_hex':data[-32:-16].hex(),
                       'guard_before_hex':data[:16].hex(),'guard_after_hex':data[-16:].hex()})
        if workspace and (data[:16]!=bytes([0xa5])*16 or data[-16:]!=bytes([0xa5])*16):
            raise RuntimeError('SEC workspace guard overwritten')
    return result
class SecException(gdb.Breakpoint):
    def stop(self):
        raise RuntimeError('Unexpected SEC exception-vector entry at '+hex(reg('pc'))+' ESR_EL2='+hex(reg('ESR_EL2')))
if startup:
    for offset in range(0,0x800,0x80):SecException('*'+hex(0x9ff8c000+offset))
class Prefix(gdb.Breakpoint):
    def stop(self):
        global workspace_before
        global cache_ready
        pc=reg('pc');r={'name':prefix_points[pc],'registers':snapshot()}
        if startup:
            r['registers'].update({n:hex(reg(n)) for n in ('CPTR_EL2','CPACR')})
            if reg('cpsr')&15 not in (5,9):raise RuntimeError('SEC left expected exception levels')
            if pc==0x9fc0ceb4:
                workspace_before=workspace_read()
                if workspace:
                    for region in startup['ranges']:
                        data=bytes(gdb.selected_inferior().read_memory(int(region['address'],16),region['size']))
                        if data!=bytes([0xa5])*len(data):raise RuntimeError('Workspace sentinel changed before original SEC stores')
            if pc==0x9fc0ceb8 and reg('x4')&0xff00:raise RuntimeError('SEC fixture requires CPU0 startup branch')
            if pc==0x9fc0cee4:
                data=bytes(gdb.selected_inferior().read_memory(0x9ff8c000,0x800))
                if data!=struct.pack('<Q',int(startup['vector_word'],16))*256:raise RuntimeError('SEC vector fill mismatch')
                r['vectors_sha256']=hashlib.sha256(data).hexdigest()
                r['timestamp']=hex(phys(0x9fc0cd60))
                if int(r['timestamp'],16)!=reg('x19'):raise RuntimeError('SEC timestamp store mismatch')
            if pc==0x9fc0cf20:
                data=bytes(gdb.selected_inferior().read_memory(0x9ff90000,0x40000))
                if any(data):raise RuntimeError('SEC BSS clear mismatch')
                r['bss_sha256']=hashlib.sha256(data).hexdigest()
            if pc==0x9fc0cf28:
                if reg('sp')!=0x9ffd0000 or reg('x0')!=0x40000:raise RuntimeError('SEC temporary stack/size mismatch')
                r['workspace_after']=workspace_read()
        if stack:
            r['stack_globals']={a:hex(phys(int(a,16))) for a in stack['globals']}
            expected_globals=dict(stack['globals'])
            if buffer and pc in (0x9fc28444,0x9fc28458,0x9fc28468,0x9fc2846c,0x9fc28484,0x9fc28494,0x9fc21ca4,0x9fc21cc0,0x9fc21ce0,0x9fc21d00,0x9fc21d08,0x9fc0cf2c,0x9fc0cf38)+CACHE_PC_LIST:expected_globals['0x9fc356c8']='0x10'
            if stack_return and pc==0x9fc21cc0:expected_globals['0x9fc3d710']=stack_return['fixture_word']
            if stack_return and pc in (0x9fc21ce0,0x9fc21d00,0x9fc21d08,0x9fc0cf2c,0x9fc0cf38)+CACHE_PC_LIST:expected_globals['0x9fc3d710']=stack_return['shifted_cache']
            if r['stack_globals']!=expected_globals:raise RuntimeError('Unexpected stack-source globals')
            if pc==0x9fc21c84 and reg('x8')!=0:raise RuntimeError('Expected original empty stack nibble cache')
            if pc==0x9fc284b4 and (reg('x0')!=0 or reg('x1')!=0x9fc284b8 or reg('x2')!=0x9fc284d0):
                raise RuntimeError('Unexpected original stack-source dispatch')
            if pc==0x9fc284dc:
                if [hex(reg('x'+str(i))) for i in range(3)]!=stack['request_prefix']:raise RuntimeError('Unexpected XBL availability request')
                if reg('sp')!=0x9ffcffb0:raise RuntimeError('Unexpected XBL stack depth before SMC')
                r['request']=[hex(reg('x'+str(i))) for i in range(8)]
                r['stack_words']=[hex(phys(reg('sp')+8*i)) for i in range(10)]
                data=bytes(gdb.selected_inferior().read_memory(0x9ff90000,0x3ffb0))
                if any(data):raise RuntimeError('Unexpected BSS write outside original 80-byte stack frame')
                r['untouched_bss_sha256']=hashlib.sha256(data).hexdigest()
                r['workspace_after']=workspace_read()
        if buffer:
            if pc==0x9fc284e0 and any(reg('x'+str(i)) for i in range(4)):raise RuntimeError('Original-slice query reply not restored to XBL')
            if pc==0x9fc28468:
                r['request']=[hex(reg('x'+str(i))) for i in range(8)]
                if r['request'][:4]!=buffer['request_prefix']:raise RuntimeError('Unexpected original XBL buffer request')
                r['buffer_hex']=bytes(gdb.selected_inferior().read_memory(0x9fc356c0,8)).hex()
                if r['buffer_hex']!='00'*8:raise RuntimeError('Original XBL did not zero its buffer')
                r['query_reply_count']=phys(symbols['xbl_query_count'])
                if r['query_reply_count']!=1:raise RuntimeError('Exact one-shot query reply not consumed')
                r['workspace_after']=workspace_read()
        if stack_return and pc in RETURN_PC_LIST:
            r['buffer_hex']=bytes(gdb.selected_inferior().read_memory(0x9fc356c0,8)).hex()
            r['query_reply_count']=phys(symbols['xbl_query_count']);r['buffer_reply_count']=phys(symbols['xbl_buffer_count'])
            if r['buffer_hex']!=buffer_reply['buffer_hex'] or r['query_reply_count']!=1 or r['buffer_reply_count']!=1:
                raise RuntimeError('Exact fixture buffer/one-shot reply mismatch')
            r['workspace_after']=workspace_read()
            if pc==0x9fc2846c and [hex(reg('x'+str(i))) for i in range(4)]!=buffer_reply['reply_x0_x3']:
                raise RuntimeError('Original-slice buffer status/count not returned to XBL')
            if pc in (0x9fc28494,0x9fc21ca4) and reg('x0')!=int(stack_return['fixture_word'],16):
                raise RuntimeError('Original XBL did not read fixture source')
            if pc in (0x9fc21ce0,0x9fc21d00) and reg('x0')!=int(stack_return['consumed_nibble'],16):
                raise RuntimeError('Original XBL consumed wrong stack nibble')
            if pc in (0x9fc21d08,0x9fc0cf2c) and reg('x0')!=int(stack_return['stack_size'],16):
                raise RuntimeError('Original stack-sizing result mismatch')
            if pc==0x9fc0cf2c and reg('sp')!=0x9ffd0000:raise RuntimeError('Original stack frames not unwound')
            if pc==0x9fc0cf38 and (reg('sp')!=int(stack_return['adjusted_sp'],16) or reg('x19')!=int(stack_return['stack_size'],16)):
                raise RuntimeError('Original SEC stack adjustment mismatch')
        if cache and pc in CACHE_PC_LIST:
            r['workspace_after']=workspace_read();r['canary_word']=hex(phys(0x9fc350a8))
            if r['canary_word']!=cache['initial_canary_word']:raise RuntimeError('Canary written before second source request')
            base=next(v['registers'] for v in prefix if v['name']=='sec-adjusted-stack-before-next-call')
            bank='SCTLR_EL2' if int(base['cpsr'],16)&15==9 else 'SCTLR'
            expected_sctlr=int(base[bank],16)
            if pc in (0x9fc0cf40,0x9fc0cf44,0x9fc0cd44,0x9fc1aa88):expected_sctlr|=0x1000
            if pc in (0x9fc0cf44,0x9fc0cd44,0x9fc1aa88):expected_sctlr|=4
            if reg(bank)!=expected_sctlr or reg(bank)&1:raise RuntimeError('Original cache enable/control mismatch')
            if pc in (0x9fc0cf3c,0x9fc0cf40,0x9fc0cf44) and (reg('sp')!=int(stack_return['adjusted_sp'],16) or reg('cpsr')&0x3c0!=int(base['cpsr'],16)&0x3c0):
                raise RuntimeError('Cache helper changed SP or interrupt masks')
            if pc==0x9fc0cf44:cache_ready=True
        prefix.append(r);self.enabled=False
        return not cache and pc==SEC_STOP
for pc in prefix_points:Prefix('*'+hex(pc))
if cache:
    class Geometry(gdb.Breakpoint):
        def stop(self):
            if reg('x1')!=int(cache['setway_callback'],16) or reg('x10')&1:raise RuntimeError('Unexpected original set/way callback/selector')
            raw=reg('x12');ways=((raw>>3)&0x3ff)+1;sets=((raw>>13)&0x7fff)+1
            cache_geometry.append({'selector':hex(reg('x10')),'raw_ccsidr':hex(raw),'clidr':hex(reg('x6')),
              'line_bytes':1<<((raw&7)+4),'ways':ways,'sets':sets,'setway_operations':ways*sets,'registers':snapshot()})
            return False
    Geometry('*0x9fc18240')
    class Canary(gdb.Breakpoint):
        def stop(self):
            global second_request_seen
            if not cache_ready:return False
            r={'name':'sec-canary-before-buffer-smc','registers':snapshot(),
               'request':[hex(reg('x'+str(i))) for i in range(8)],'workspace_after':workspace_read(),
               'buffer_hex':bytes(gdb.selected_inferior().read_memory(0x9fc356c0,8)).hex(),
               'canary_word':hex(phys(0x9fc350a8)),
               'stack_globals':{a:hex(phys(int(a,16))) for a in stack['globals']},
               'query_reply_count':phys(symbols['xbl_query_count']),'buffer_reply_count':phys(symbols['xbl_buffer_count'])}
            if r['request'][:4]!=buffer['request_prefix'] or r['registers']['sp']!=cache['expected_second_sp']:
                raise RuntimeError('Unexpected second buffer request/stack')
            if r['buffer_hex']!='00'*8 or r['canary_word']!=cache['initial_canary_word'] or r['query_reply_count']!=1 or r['buffer_reply_count']!=1:
                raise RuntimeError('Second source boundary/reply counters mismatch')
            if r['stack_globals']!={'0x9fc3d710':stack_return['shifted_cache'],'0x9fc356c8':'0x10'}:raise RuntimeError('Canary source changed selector/cache')
            if canary_reply:r['canary_reply_count']=phys(symbols['xbl_canary_count'])
            if canary and r['canary_reply_count']!=0:raise RuntimeError('Second reply consumed before second SMC')
            prefix.append(r);second_request_seen=True;self.enabled=False;return not canary
    Canary('*'+hex(CACHE_SMC_STOP))
if canary:
    class CanaryReturn(gdb.Breakpoint):
        def stop(self):
            if not second_request_seen:return False
            pc=reg('pc');r={'name':canary_points[pc],'registers':snapshot(),
              'buffer_hex':bytes(gdb.selected_inferior().read_memory(0x9fc356c0,8)).hex(),
              'canary_word':hex(phys(0x9fc350a8)),'query_reply_count':phys(symbols['xbl_query_count']),
              'buffer_reply_count':phys(symbols['xbl_buffer_count']),'canary_reply_count':phys(symbols['xbl_canary_count']),
              'stack_globals':{a:hex(phys(int(a,16))) for a in stack['globals']},'workspace_after':workspace_read()}
            if r['buffer_hex']!=canary_reply['buffer_hex'] or (r['query_reply_count'],r['buffer_reply_count'],r['canary_reply_count'])!=(1,1,1):
                raise RuntimeError('Second fixture/reply ledgers mismatch')
            if r['stack_globals']!={'0x9fc3d710':stack_return['shifted_cache'],'0x9fc356c8':'0x10'}:raise RuntimeError('Second buffer changed nibble cache/selector')
            r['canary_guard_before_hex']=bytes(gdb.selected_inferior().read_memory(0x9fc350a0,8)).hex()
            r['canary_guard_after_hex']=bytes(gdb.selected_inferior().read_memory(0x9fc350b0,8)).hex()
            if any(r[n]!=canary[n] for n in ('canary_guard_before_hex','canary_guard_after_hex')):raise RuntimeError('Canary store changed adjacent words')
            after_store=list(canary_points).index(pc)>=list(canary_points).index(0x9fc0cd58)
            if r['canary_word']!=(canary_reply['buffer_word'] if after_store else canary['initial_canary_word']):raise RuntimeError('Original canary store mismatch')
            if pc==0x9fc2846c and [hex(reg('x'+str(i))) for i in range(4)]!=canary_reply['reply_x0_x3']:raise RuntimeError('Second buffer return registers mismatch')
            if pc in (0x9fc28494,0x9fc0cd50) and reg('x0')!=int(canary_reply['buffer_word'],16):raise RuntimeError('Original second source read mismatch')
            base=next(v['registers'] for v in prefix if v['name']=='sec-dcache-enabled')
            for bank in ('SCTLR','SCTLR_EL2','HCR_EL2'):
                if r['registers'][bank]!=base[bank]:raise RuntimeError('Canary/main changed cache/hypervisor controls')
            if reg('cpsr')&0x3cf!=int(base['cpsr'],16)&0x3cf:raise RuntimeError('Canary/main changed level or interrupt masks')
            if pc in (0x9fc0cf48,0x9fc0cf50,0x9fc0e308) and reg('sp')!=int(stack_return['adjusted_sp'],16):raise RuntimeError('Canary stack did not unwind')
            if pc in (0x9fc0cf50,0x9fc0e308) and (reg('x0')!=int(stack_return['stack_base'],16) or reg('x1')!=int(stack_return['stack_size'],16)):
                raise RuntimeError('SEC main received unexpected workspace arguments')
            if pc==CANARY_READ_STOP:
                r['pending_read']={'address':hex(reg('x8')),'size':canary['readiness_width'],'wait_while_value':hex(struct.unpack('<I',bytes(gdb.selected_inferior().read_memory(reg('sp')+0x1c,4)))[0]),'executed':False}
                if r['pending_read']['address']!=canary['readiness_address'] or r['pending_read']['wait_while_value']!=canary['wait_while_value']:
                    raise RuntimeError('Unexpected first SEC readiness read')
            prefix.append(r);self.enabled=False;return pc==SEC_STOP
    for pc in canary_points:CanaryReturn('*'+hex(pc))
if readiness:
    class Readiness(gdb.Breakpoint):
        def stop(self):
            pc=reg('pc');r={'name':readiness_points[pc],'registers':snapshot(),
              'canary_word':hex(phys(0x9fc350a8)),'query_reply_count':phys(symbols['xbl_query_count']),
              'buffer_reply_count':phys(symbols['xbl_buffer_count']),'canary_reply_count':phys(symbols['xbl_canary_count']),
              'workspace_after':workspace_read()}
            if r['canary_word']!=canary_reply['buffer_word'] or (r['query_reply_count'],r['buffer_reply_count'],r['canary_reply_count'])!=(1,1,1):raise RuntimeError('Readiness changed canary/reply ledgers')
            base=next(v['registers'] for v in prefix if v['name']=='sec-dcache-enabled')
            for bank in ('SCTLR','SCTLR_EL2','HCR_EL2'):
                if r['registers'][bank]!=base[bank]:raise RuntimeError('Readiness changed cache/hypervisor controls')
            if reg('cpsr')&0x3cf!=int(base['cpsr'],16)&0x3cf:raise RuntimeError('Readiness changed EL or interrupt masks')
            if pc in (0x9fc0e380,0x9fc0e388):
                r['observed_flag']=hex(reg('x9')&0xffffffff)
                if r['observed_flag']!=readiness_meta['value']:raise RuntimeError('Original flag load differs from capture')
            if pc==0x9fc0e388 and reg('cpsr')&(1<<30):raise RuntimeError('Captured flag does not exit hold loop')
            if pc==0x9fc0e320 and reg('sp')!=0x9ffcfce0:raise RuntimeError('Hold helper did not unwind SP')
            if pc==0x9fc0d1e4 and (reg('sp')!=0x9ffcfce0 or reg('x0')!=0x9ff90000 or reg('x1')!=0x3fd00):raise RuntimeError('Platform main arguments/stack mismatch')
            if pc in (0x9fc0d244,0x9fc19b5c,0x9fc27fdc,READINESS_COUNTER_STOP):
                if reg('sp')!=0x9ffcfbc0:raise RuntimeError('Platform prologue SP mismatch')
                r['platform_frame_canary']=hex(phys(reg('sp')+0x58))
                if r['platform_frame_canary']!=canary_reply['buffer_word']:raise RuntimeError('Original platform frame did not copy canary')
            if pc==READINESS_COUNTER_STOP:r['pending_counter']={'register':readiness['counter'],'executed':False}
            prefix.append(r);self.enabled=False;return pc==SEC_STOP
    for pc in readiness_points:Readiness('*'+hex(pc))
if counter:
    class Counter(gdb.Breakpoint):
        def stop(self):
            pc=reg('pc');r={'name':counter_points[pc],'registers':snapshot(),
              'timer_controls':{n:hex(reg(n)) for n in ('CNTFRQ_EL0','CNTVOFF_EL2','CNTHCTL_EL2','CPACR','CPTR_EL2')},
              'canary_word':hex(phys(0x9fc350a8)),'query_reply_count':phys(symbols['xbl_query_count']),
              'buffer_reply_count':phys(symbols['xbl_buffer_count']),'canary_reply_count':phys(symbols['xbl_canary_count']),
              'workspace_after':workspace_read()}
            base=next(v['registers'] for v in prefix if v['name']=='sec-dcache-enabled')
            for bank in ('SCTLR','SCTLR_EL2','HCR_EL2'):
                if r['registers'][bank]!=base[bank]:raise RuntimeError('Counter/init changed cache/hypervisor controls')
            if reg('cpsr')&0x3cf!=int(base['cpsr'],16)&0x3cf:raise RuntimeError('Counter/init changed EL or interrupt masks')
            if r['canary_word']!=canary_reply['buffer_word'] or (r['query_reply_count'],r['buffer_reply_count'],r['canary_reply_count'])!=(1,1,1):raise RuntimeError('Counter/init changed canary/reply ledgers')
            prior=next((v['timer_controls'] for v in prefix if 'timer_controls' in v),r['timer_controls'])
            if r['timer_controls']!=prior:raise RuntimeError('Counter/init changed timer or SIMD controls')
            r['frequency_mismatch']=int(r['timer_controls']['CNTFRQ_EL0'],16)!=counter['frequency']
            if pc==0x9fc2bb4c:r['counter_ticks']=hex(reg('x0'))
            ticks=next((int(v['counter_ticks'],16) for v in prefix if 'counter_ticks' in v),reg('x0'))
            if pc in (0x9fc0d248,0x9fc19b78) and reg('x0')!=ticks:raise RuntimeError('Counter wrapper changed ticks')
            if pc in (0x9fc19bf0,0x9fc19b90):
                r['frequency']=reg('x0')
                if r['frequency']!=counter['frequency']:raise RuntimeError('Original fixed frequency mismatch')
            expected=(ticks//counter['frequency']*1000000000+ticks%counter['frequency']*1000000000//counter['frequency'])&((1<<64)-1)
            if pc==0x9fc0d24c:
                r['converted_value']=hex(reg('x0'));r['expected_value']=hex(expected)
                if reg('x0')!=expected:raise RuntimeError('Original counter conversion mismatch')
            if list(counter_points).index(pc)>=list(counter_points).index(0x9fc0d254):
                r['stored_value']=hex(phys(int(counter['result_address'],16)))
                if int(r['stored_value'],16)!=expected:raise RuntimeError('Original counter result store mismatch')
            if list(counter_points).index(pc)>=list(counter_points).index(0x9fc22084):
                a=int(counter['descriptor_copy']['address'],16);n=counter['descriptor_copy']['size']
                r['descriptor_copy_hex']=bytes(gdb.selected_inferior().read_memory(a,n)).hex()
                if r['descriptor_copy_hex']!=counter['descriptor_copy']['expected_hex']:raise RuntimeError('Original descriptor RAM copy mismatch')
            if pc==COUNTER_BOUND:
                r['pending_access']={**counter['next_access'],'executed':False}
                if reg('x8')!=int(r['pending_access']['address'],16):raise RuntimeError('Next MMIO pointer mismatch')
            prefix.append(r);self.enabled=False;return pc==SEC_STOP
    for pc in counter_points:Counter('*'+hex(pc))
if selector:
    class Selector(gdb.Breakpoint):
        def stop(self):
            pc=reg('pc');r={'name':selector_points[pc],'registers':snapshot(),
              'canary_word':hex(phys(0x9fc350a8)),'query_reply_count':phys(symbols['xbl_query_count']),
              'buffer_reply_count':phys(symbols['xbl_buffer_count']),'canary_reply_count':phys(symbols['xbl_canary_count']),
              'workspace_after':workspace_read(),
              'timer_controls':{n:hex(reg(n)) for n in ('CNTFRQ_EL0','CNTVOFF_EL2','CNTHCTL_EL2','CPACR','CPTR_EL2')}}
            base=next(v['registers'] for v in prefix if v['name']=='sec-dcache-enabled')
            for bank in ('SCTLR','SCTLR_EL2','HCR_EL2'):
                if r['registers'][bank]!=base[bank]:raise RuntimeError('Selector changed cache/hypervisor controls')
            if reg('cpsr')&0x3cf!=int(base['cpsr'],16)&0x3cf:raise RuntimeError('Selector changed EL or interrupt masks')
            prior=next(v['timer_controls'] for v in prefix if 'timer_controls' in v)
            if r['timer_controls']!=prior:raise RuntimeError('Selector changed timer/SIMD controls')
            if r['canary_word']!=canary_reply['buffer_word'] or (r['query_reply_count'],r['buffer_reply_count'],r['canary_reply_count'])!=(1,1,1):raise RuntimeError('Selector changed canary/reply ledgers')
            if pc==0x9fc2a154:
                r['observed_selector']=hex(reg('x8')&0xffffffff)
                if r['observed_selector']!=selector_meta['value']:raise RuntimeError('Original selector load differs from capture')
            if pc==0x9fc2a164:
                r['low_bits']=reg('x8');r['equal_one']=bool(reg('cpsr')&(1<<30))
                if r['low_bits']!=selector['low_bits'] or r['equal_one']!=(selector['low_bits']==1):raise RuntimeError('Original selector compare mismatch')
            if pc in (0x9fc2a168,0x9fc22c10):
                r['selected_descriptor']=hex(reg('x0'))
                if r['selected_descriptor']!=selector['selected_descriptor']:raise RuntimeError('Original descriptor choice mismatch')
            if list(selector_points).index(pc)>=list(selector_points).index(0x9fc22c1c):
                r['stored_pointer']=hex(phys(int(selector['stored_pointer_address'],16)))
                if r['stored_pointer']!=selector['selected_descriptor']:raise RuntimeError('Original descriptor pointer store mismatch')
                a=int(selector['selected_descriptor'],16);r['descriptor_hex']=bytes(gdb.selected_inferior().read_memory(a,0x48)).hex()
                if r['descriptor_hex']!=selector['descriptor_hex']:raise RuntimeError('Selected original descriptor changed')
            if pc==0x9fc220dc:
                r['table_match']={'key':hex(reg('x10')),'copied_id':hex(reg('x9')),'record':hex(reg('x8')-12)}
                if r['table_match']!={'key':selector['copied_descriptor_id'],'copied_id':selector['copied_descriptor_id'],'record':selector['table_scan'][-1]['address']}:raise RuntimeError('Original table lookup mismatch')
            if pc==0x9fc22bf0:
                r['hook_argument']=hex(reg('x1'))
                if r['hook_argument']!=selector['matched_argument']:raise RuntimeError('Original descriptor hook argument mismatch')
            if pc==0x9fc220e8 and reg('x0')!=0:raise RuntimeError('Original no-op hook did not return zero')
            r['stored_counter']=hex(phys(int(counter['result_address'],16)))
            expected=next(v['converted_value'] for v in prefix if 'converted_value' in v)
            if r['stored_counter']!=expected:raise RuntimeError('Selector changed stored counter result')
            if pc==SELECTOR_BOUND:
                r['pending_access']={**selector['next_access'],'executed':False}
                if reg('x8')!=int(r['pending_access']['address'],16):raise RuntimeError('Next selected MMIO pointer mismatch')
            prefix.append(r);self.enabled=False;return pc==SEC_STOP
    for pc in selector_points:Selector('*'+hex(pc))
ENTRY_BREAKPOINT
end
ENTRY_CONTINUE
continue
python
node=int(checkpoints[3]['bridge_bookkeeping_node_address'],16)
walks=[]
for ipa in (0x40400000,0x90000000):
    base=reg('VTTBR_EL2')&0x0000fffffffff000
    walk={'ipa':hex(ipa),'entries':[]}
    # Pinned observed VTCR_EL2: 4 KiB granule, L1 start, 36-bit IPA.
    if reg('VTCR_EL2')!=0x8001355c:raise RuntimeError('Unexpected stage-2 regime')
    for level,shift in ((1,30),(2,21),(3,12)):
        a=base+8*((ipa>>shift)&511);pte=phys(a)
        walk['entries'].append({'level':level,'address':hex(a),'pte':hex(pte)})
        if pte&3!=3 or level==3:break
        base=pte&0x0000fffffffff000
    walks.append(walk)
stage1=[]
if reg('TCR_EL2')!=0x8081351c:raise RuntimeError('Unexpected EL2 stage-1 regime')
for va in (0x80040000,0x90000000):
    base=reg('TTBR0_EL2')&0x0000fffffffff000
    walk={'va':hex(va),'entries':[]}
    for level,shift in ((1,30),(2,21),(3,12)):
        a=base+8*((va>>shift)&511);pte=phys(a)
        walk['entries'].append({'level':level,'address':hex(a),'pte':hex(pte)})
        if pte&3!=3 or level==3:break
        base=pte&0x0000fffffffff000
    stage1.append(walk)
result={'checkpoints':checkpoints,'calls':calls,'stage2_walks':walks,'el2_stage1_walks':stage1,
 'transition_mapping_checks':transition_mappings,
 ENTRY_RESULT
 'bridge_record_handle_before_eret':hex(bounded_word(node+0x38)),
 'shm_bridge_ledger':[phys(symbols['shm_bridge_ledger']+8*i) for i in range(6)],
 'model_counts':{n:phys(a) for n,a in symbols.items() if n.endswith('_count')},
 'pmic_map_ledger':[phys(symbols['pmic_region_map_ledger']+8*i) for i in range(241)]}
end
stepi
python
result['after_eret']=snapshot()
call_phase='xbl-payload'
end
stepi
python
result['after_first_fetch']=snapshot()
end
XBL_CONTINUE
python
if prefix_points:
    result['xbl_prefix_checkpoints']=prefix
    result['xbl_forward_calls']=forward_calls
    if cache:result['xbl_cache_geometry']=cache_geometry
    if startup:
        result['xbl_workspace_before']=workspace_before
        if reg('pc')!=SEC_STOP:raise RuntimeError('SEC startup boundary not reached')
    if [int(c['registers']['pc'],16) for c in prefix]!=list(prefix_points)+([CACHE_SMC_STOP]+list(canary_points)+list(readiness_points)+list(counter_points)+list(selector_points) if canary else ([SEC_STOP] if cache else [])):raise RuntimeError('Unexpected SEC prefix checkpoint sequence')
end
NEXT_ACCESS_STEP
SMC_ROUTE_STEP
python
Path(OUTPUT).write_text(json.dumps(result,indent=2)+'\\n')
end
FINALIZE
quit
'''.replace('SELECTOR_CONTRACT',repr(selector)).replace('SELECTOR_META',repr(selector_metadata)).replace('SELECTOR_POINTS',repr(SELECTOR_POINTS if selector else {})).replace('SELECTOR_BOUND',str(SELECTOR_STOP)).replace('COUNTER_CONTRACT',repr(counter)).replace('COUNTER_POINTS',repr(COUNTER_POINTS if counter else {})).replace('COUNTER_BOUND',str(COUNTER_STOP)).replace('READINESS_COUNTER_STOP',str(READINESS_STOP)).replace('READINESS_CONTRACT',repr(readiness)).replace('READINESS_META',repr(readiness_metadata)).replace('READINESS_POINTS',repr(READINESS_POINTS if readiness else {})).replace('CANARY_READ_STOP',str(CANARY_STOP)).replace('CANARY_CONTRACT',repr(canary)).replace('CANARY_REPLY_MODEL',repr(canary_reply)).replace('CANARY_POINTS',repr(CANARY_POINTS if canary else {})).replace('CACHE_SMC_STOP',str(CACHE_STOP)).replace('CACHE_PC_LIST',repr(tuple(CACHE_POINTS))).replace('CACHE_CONTRACT',repr(cache)).replace('RETURN_PC_LIST',repr(tuple(RETURN_POINTS))).replace('RETURN_CONTRACT',repr(stack_return)).replace('BUFFER_REPLY_MODEL',repr(buffer_reply)).replace('BUFFER_CONTRACT',repr(buffer)).replace('STACK_CONTRACT',repr(stack)).replace('STARTUP_CONTRACT',repr(startup)).replace('WORKSPACE_SENTINEL',repr(workspace)).replace('SEC_STOP',str(sec_stop)).replace('PREFIX_POINTS',repr(prefix_points)).replace('POINTS',repr(points)).replace('PORT',str(port)).replace('SYMBOLS',repr(symbols)).replace('OUTPUT',repr(str(out/'inspection.json'))).replace('CLEAN_RANGES',repr(clean_ranges)).replace('PAYLOAD_TARGET',repr(target)).replace('TRANSITION_ENTRY_STATE',repr(initial_transition_state)).replace('XBL_CONTINUE','continue' if bounded_xbl else '').replace('FINALIZE','python\ntry:gdb.execute("monitor quit",to_string=True)\nexcept gdb.error:pass\nend' if bounded_xbl else 'detach')
    next_access_step='''stepi
python
r=snapshot();r.update({n:hex(reg(n)) for n in ('ESR_EL1','ELR_EL1','FAR_EL1','VBAR','CPACR','CPTR_EL2')})
before=prefix[-1]['registers'];level=int(before['cpsr'],16)&15
if reg('pc')==COUNTER_NEXT:
    destination='completed-mmio-read';syndrome=None
else:
    bank='EL2' if reg('cpsr')&15==9 else 'EL1'
    vector=reg('VBAR_EL2') if bank=='EL2' else reg('VBAR')
    if reg('pc')!=vector+0x200 or reg('ELR_'+bank)!=COUNTER_BEFORE or reg('ESR_'+bank)>>26!=0x25 or reg('FAR_'+bank)!=NEXT_ACCESS_ADDRESS or reg('ESR_'+bank)&0x3f!=0x10:raise RuntimeError('Unexpected next MMIO exception')
    destination='mmio-data-abort-'+bank.lower();syndrome=hex(reg('ESR_'+bank))
    if reg('cpsr')&15!=level:raise RuntimeError('Unexpected MMIO exception level change')
result['xbl_next_access_step']={'before':before,'after':r,'destination':destination,'syndrome':syndrome,'handler_executed':False,'instruction_executed':destination=='completed-mmio-read'}
end
'''.replace('COUNTER_NEXT',str(sec_stop+4)).replace('COUNTER_BEFORE',str(sec_stop)).replace('NEXT_ACCESS_ADDRESS',str(int((selector or counter)['next_access']['address'],16)) if (selector or counter) else '0')
    script=script.replace('NEXT_ACCESS_STEP',next_access_step if args.inspect_xbl_next_step else '')
    route_step='''stepi
python
route=snapshot()
route.update({n:hex(reg(n)) for n in ('SCR_EL3','SPSR_EL3','ELR_EL3','ESR_EL3','VBAR_EL3')})
before=prefix[-1]['registers'];level=int(before['cpsr'],16)&15
if level==9:
    if reg('cpsr')&15!=13 or reg('pc')!=reg('VBAR_EL3')+0x400 or reg('ESR_EL3')!=0x5e000000 or reg('ELR_EL3')!=SMC_AFTER:
        raise RuntimeError('Unexpected XBL EL2-to-EL3 SMC routing')
    destination='synthetic-el3-vector';saved='SPSR_EL3'
else:
    if not int(before['HCR_EL2'],16)&(1<<19) or reg('cpsr')&15!=9 or reg('pc')!=reg('VBAR_EL2')+0x400 or reg('ESR_EL2')!=0x5e000000 or reg('ELR_EL2')!=SMC_BEFORE:
        raise RuntimeError('Unexpected XBL EL1-to-QHEE SMC trap routing')
    destination='original-qhee-el2-vector';saved='SPSR_EL2'
if reg(saved)!=int(before['cpsr'],16):raise RuntimeError('SMC routing saved caller PSTATE mismatch: saved='+hex(reg(saved))+' caller='+before['cpsr'])
if [hex(reg('x'+str(i))) for i in range(8)]!=prefix[-1]['request']:raise RuntimeError('SMC exception entry changed arguments')
result['xbl_smc_route']={'after_instruction':route,'destination':destination,
    'scope':'One normal original SMC instruction only; paused before vector instruction/handler, no response, forwarding or service acceptance demonstrated.'}
end
QHEE_FORWARD_STEP
''' if args.inspect_xbl_smc_route else ''
    forward_step='''python
call_phase='xbl-qhee-handler';handler_calls_start=len(forward_calls)
class ForwardBoundary(gdb.Breakpoint):
    def stop(self):self.enabled=False;return True
for site in FORWARD_SITES:ForwardBoundary('*'+hex(site))
ForwardBoundary('*'+hex(SMC_AFTER))
end
continue
python
pc=reg('pc')
if pc not in FORWARD_SITES+[SMC_AFTER]:raise RuntimeError('QHEE query forwarding/return boundary not reached')
result['xbl_qhee_handler']={'boundary':'before-forwarded-smc' if pc in FORWARD_SITES else 'returned-to-xbl',
    'registers':snapshot(),'request':[hex(reg('x'+str(i))) for i in range(8)],
    'calls':forward_calls[handler_calls_start:],'bounded_smc_sites':[hex(site) for site in FORWARD_SITES],
    'scope':'Original QHEE EL1 SMC trap handler through its first forwarding SMC or query return. Paused before any forwarding SMC; no new EL3 reply model or service acceptance.'}
end
''' if args.inspect_xbl_qhee_forward else ''
    forward_step=forward_step.replace('FORWARD_SITES',repr(forward_sites))
    route_step=route_step.replace('QHEE_FORWARD_STEP',forward_step)
    route_step=route_step.replace('SMC_BEFORE',str(sec_stop)).replace('SMC_AFTER',str(sec_stop+4))
    script=script.replace('SMC_ROUTE_STEP',route_step)
    entry_breakpoint="entry=None\nclass Entry(gdb.Breakpoint):\n    def stop(self):self.enabled=False;return True\nEntry('*'+hex("+str(initial_eret)+"))"
    entry_continue='''continue
python
entry={'before_initial_eret':snapshot()}
entry['before_initial_eret'].update({n:hex(reg(n)) for n in ('SCR_EL3','SPSR_EL3','ELR_EL3')})
if reg('pc')!=INITIAL_ERET:raise RuntimeError('Initial entry checkpoint not reached')
end
stepi
python
entry['initial_qhee_entry']=snapshot()
entry['initial_qhee_entry'].update({n:hex(reg(n)) for n in ('SCR_EL3','SPSR_EL3','ELR_EL3')})
expected=EXPECTED_ENTRY
for name,value in expected['controls'].items():
    wanted=int(value,16)|(0x30 if name=='SCR_EL3' else 0)
    if reg(name)!=wanted:raise RuntimeError('Unexpected seeded entry control '+name)
if reg('pc')!=0x80040000 or reg('cpsr')&0x3cf!=int(expected['controls']['SPSR_EL3'],16):raise RuntimeError('Unexpected QHEE initial entry')
if any(reg(name)!=int(value,16) for name,value in expected['arguments'].items()):raise RuntimeError('Unexpected QHEE initial arguments')
end
'''.replace('INITIAL_ERET',str(initial_eret)).replace('EXPECTED_ENTRY',repr(expected_entry))
    script=script.replace('ENTRY_BREAKPOINT',entry_breakpoint if inspect_entry else '').replace('ENTRY_CONTINUE',entry_continue if inspect_entry else '').replace('ENTRY_RESULT',"'entry_state_inspection':entry," if inspect_entry else '')
    (out/'trace.gdb').write_text(script);(out/'inspection.json').unlink(missing_ok=True)
    with (out/'stdout.txt').open('w') as stdout,(out/'stderr.txt').open('w') as stderr:
        q=subprocess.Popen(command+['-S','-gdb',f'tcp:127.0.0.1:{port}'],stdout=stdout,stderr=stderr,env=environment()[1])
        try:
            run=subprocess.run(['gdb-multiarch','-q','-nx','-batch','-x',str(out/'trace.gdb')],capture_output=True,text=True,timeout=30)
            (out/'gdb.txt').write_text(run.stdout+run.stderr)
            if run.returncode or not (out/'inspection.json').exists():raise SystemExit('Bridge trace failed; see '+str(out/'gdb.txt'))
        finally:
            q.terminate()
            try:q.wait(timeout=5)
            except subprocess.TimeoutExpired:q.kill();q.wait()
    r=json.loads((out/'inspection.json').read_text())
    r.update({'input_manifest':str(args.manifest.resolve()),'input_manifest_sha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        'image_sha256':PINNED_HYP,'loaded_code':expected_metadata,'tool_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'entry_state_model':expected_entry,'el3_sha256':hashlib.sha256(el3.read_bytes()).hexdigest(),
        'scope':'Pinned QHEE execution (loaded-code experiment separately reported) and read-only inspection, including two normal instruction steps across ERET. Calls are recorded at the specific SMC instruction 0x80041aa0. No debugger edits to guest registers or memory; explicit model assumptions, no phone access.'})
    if bounded_xbl:
        r['xbl_payload']=xbl_metadata
        r['xbl_prefix_scope']='Original FV branch, SEC zero-x0 path, cache/TLBI/current-EL branch and VBAR setup through 0x9fc0ceb4 only. QEMU terminated while paused there, before vector-table stores, BSS, stack and platform setup. No complete UEFI/ABL/Linux boot; no debugger edits.'
    if startup:
        r['xbl_startup_contract']=startup
        r['xbl_workspace_sentinel']=workspace
        r['xbl_prefix_scope']=startup['scope']+' QEMU terminated while paused at the call, with no debugger edits.'
    if stack:
        r['xbl_stack_contract']=stack
        r['xbl_prefix_scope']=stack['scope']+' QEMU terminated while paused; no debugger edits.'
    if query:r['xbl_query_reply_model']=query
    if buffer:
        r['xbl_buffer_contract']=buffer
        r['xbl_prefix_scope']=buffer['scope']+' QEMU terminated while paused; no debugger edits.'
    if buffer_reply:r['xbl_buffer_reply_model']=buffer_reply
    if stack_return:
        r['xbl_stack_return_contract']=stack_return
        r['xbl_prefix_scope']=stack_return['scope']+' QEMU terminated while paused; no debugger edits.'
    if cache:
        r['xbl_cache_contract']=cache
        r['xbl_prefix_scope']=cache['scope']+' QEMU terminated while paused; no debugger edits.'
    if canary_reply:r['xbl_canary_reply_model']=canary_reply
    if canary:
        r['xbl_canary_contract']=canary
        r['xbl_prefix_scope']=canary['scope']+' QEMU terminated while paused; no debugger edits.'
    if readiness_metadata:r['xbl_readiness_sample']=readiness_metadata
    if readiness:
        r['xbl_readiness_contract']=readiness
        r['xbl_prefix_scope']=readiness['scope']+' Measured postboot-to-entry value equality is an assumption; no debugger edits.'
    if counter:
        r['xbl_counter_contract']=counter
        r['xbl_prefix_scope']=counter['scope']+' No debugger edits; next instruction optionally stepped once without running an exception handler.'
    if selector_metadata:r['xbl_selector_sample']=selector_metadata
    if selector:
        r['xbl_selector_contract']=selector
        r['xbl_prefix_scope']=selector['scope']+' Measured postboot-to-entry equality assumed; no debugger edits. Next original MMIO instruction optionally attempted once, paused before handler.'
    (out/'manifest.json').write_text(json.dumps(r,indent=2)+'\n')
    for c in r['checkpoints']:print(c['name'],c['registers']['pc'])
    print('after_eret',r['after_eret']['pc'],r['after_eret']['cpsr']);print('after_first_fetch',r['after_first_fetch']['pc'],r['after_first_fetch']['ESR_EL2'])
    if [int(c['registers']['pc'],16) for c in r['checkpoints']]!=list(points):raise SystemExit('Unexpected bridge checkpoint sequence')


if __name__=='__main__':main()
