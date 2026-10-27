#!/usr/bin/env python3
"""Bounded clock, SMMU, timer and original-firmware path checks; no DMA claim."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from qhee import ROOT
from run_qemu import compile_elf, environment, smmu_ids_sample


def main():
    out = ROOT/'kernel-work/out/qhee-gcc-mmu-tests'
    out.mkdir(parents=True, exist_ok=True)
    qemu, env = environment(ROOT/'kernel-work/emulation/qemu-build/qemu-system-aarch64')
    sources = Path(__file__).resolve().parent/'emulator'
    sample = ROOT/'reports/nio-mmu-ids-active-20260928/manifest.json'
    properties, metadata = smmu_ids_sample(sample)
    ids = ',ids-enabled=on,'+','.join(f'{k}={v}' for k,v in properties.items())
    results = []
    # name, address, operation, options, expected value (None => external abort)
    cases = []
    def case(name, address, operation, options, expected):
        cases.append((name,address,operation,options,expected))
    read = 'ldr w19, [x8]'
    write_read = 'ldr w19, =VALUE\nstr w19, [x8]\nldr w19, [x8]'
    for name, address in [('tcu',0x17c02c),('gpu-clock',0x3d92000)]:
        case(name+'-off',address,read,'',0x80000000)
        case(name+'-on',address,read,',initially-enabled=on',1)
        case(name+'-enable-ro-status',address,write_read.replace('VALUE','0x80000001'),'',1)
        case(name+'-disable',address,write_read.replace('VALUE','0'),',initially-enabled=on',0x80000000)
        case(name+'-unknown-bits',address,write_read.replace('VALUE','2'),'',None)
    for name,address in [('apps-power',0x17c040),('gpu-power',0x3d92004)]:
        case(name+'-collapsed',address,read,'',1)
        case(name+'-powered',address,read,',initially-enabled=on',0x80000000)
        case(name+'-power-on',address,write_read.replace('VALUE','0'),'',0x80000000)
        case(name+'-collapse',address,write_read.replace('VALUE','1'),',initially-enabled=on',1)
    for name,address,op in [('clock-hole',0x17c028,read),('power-hole',0x17c064,read),
        ('clock-byte',0x17c02c,'ldrb w19, [x8]'),('clock-wide',0x17c020,'ldr x19, [x8]'),
        ('gpu-clock-wide',0x3d92000,'ldr x19, [x8]')]:
        case(name,address,op,'',None)
    # TCG decomposes an unaligned 64-bit CPU load into two legal 32-bit
    # device transactions before dispatch. This is not a native 64-bit register.
    case('clock-unaligned-load-split',0x17c02c,'ldr x19, [x8]','',0x8000000080000000)
    for bank,base,streams,contexts in [('apps',0x15000000,87,74),('gpu',0x3da0000,6,5)]:
        for i in range(3):
            case(bank+f'-id{i}',base+0x20+4*i,read,ids,properties[f'{bank}-id{i}'])
        case(bank+'-id-disabled',base+0x24,read,'',None)
        case(bank+'-id-readonly',base+0x20,'str wzr, [x8]',ids+',control=on',None)
        case(bank+'-control-disabled',base+0x10,read,ids,None)
        case(bank+'-reset-readback',base+0x10,write_read.replace('VALUE','0x12340000'),ids+',control=on',0x12340000)
        case(bank+'-fault-w1c',base+0x48,write_read.replace('VALUE','0xffffffff'),ids+',control=on',0)
        case(bank+'-tlb-sync',base+0x70,write_read.replace('VALUE','0xffffffff'),ids+',control=on',0)
        case(bank+'-tlb-idle',base+0x74,read,ids+',control=on',0)
        case(bank+'-tlb-status-ro',base+0x74,'str wzr, [x8]',ids+',control=on',None)
        for label,start,count in [('smr',0x800,streams),('s2cr',0xc00,streams),
                                   ('ext',0x2000,streams),('cbar',0x1000,contexts),
                                   ('cbfr',0x1400,contexts),('cba2r',0x1800,contexts)]:
            case(bank+'-'+label+'-last',base+start+4*(count-1),write_read.replace('VALUE','0x12340000'),ids+',control=on',0x12340000)
            case(bank+'-'+label+'-past-end',base+start+4*count,read,ids+',control=on',None)
        case(bank+'-context-unmodeled',base+0x8000,read,ids+',control=on',None)
        case(bank+'-end-unmodeled',base+(0xffffc if bank=='apps' else 0xfffc),read,ids+',control=on',None)
        case(bank+'-id-wide',base+0x20,'ldr x19, [x8]',ids,None)
    case('timer-advances',0x17c25000,
         'ldr x9, [x8]\nmov w10, #0xffff\n1: subs w10, w10, #1\nb.ne 1b\nldr x19, [x8]\ncmp x19, x9\ncset x19, hi',',timer=on',1)
    case('timer-readonly',0x17c25000,'str wzr, [x8]',',timer=on',None)
    case('timer-byte',0x17c25000,'ldrb w19, [x8]',',timer=on',None)
    template = (sources/'register_probe.S').read_text()
    before, rest = template.split('#if ACCESS == 0',1)
    _, after = rest.split('#endif',1)
    for name,address,operation,options,expected in cases:
        source = out/(name+'.S')
        source.write_text(before+operation+'\n'+after)
        elf = out/(name+'.elf')
        compile_elf(source,0x40200000,elf,[f'-DADDRESS={address:#x}'])
        command = [str(qemu),'-M','virt,secure=on,virtualization=on,gic-version=3',
            '-cpu','cortex-a76','-m','2G','-accel','tcg','-smp','1',
            '-display','none','-serial','stdio','-monitor','none','-nic','none',
            '-semihosting-config','enable=on,target=native','-no-reboot',
            '-device',f'loader,file={elf},cpu-num=0','-device','nio-gcc-mmu'+options]
        run = subprocess.run(command,capture_output=True,text=True,env=env,timeout=5)
        lines = run.stdout.splitlines()
        if expected is None:
            passed = (len(lines)==3 and lines[0]=='ABORT' and int(lines[1],16)>>26==0x25
                      and int(lines[1],16)&0x3f==0x10 and int(lines[2],16)==address)
        else:
            passed = lines == ['READ',f'{expected:016x}']
        results.append({'case':name,'passed':passed and run.returncode==0,
                        'stdout':run.stdout,'stderr':run.stderr})
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        path = Path(tmp)/'manifest.json'
        for name in ('incomplete','overflow','negative','no-contexts','powered-off'):
            report = json.loads(sample.read_text())
            if name=='incomplete': report['status']='incomplete'
            if name=='overflow': report['registers']['0x15000020']='0x100000000'
            if name=='negative': report['registers']['0x15000020']='-1'
            if name=='no-contexts': report['registers']['0x15000024']='0'
            if name=='powered-off': report['registers']['0x3da0020']='6'
            path.write_text(json.dumps(report))
            try: smmu_ids_sample(path)
            except ValueError: passed=True
            else: passed=False
            results.append({'case':name,'passed':passed})
    for enabled in ('off','on'):
        for failure in (False,True):
            name=f'qhee-{enabled}-'+('query-failure' if failure else 'query-stop')
            dest=out/name
            command=[sys.executable,str(Path(__file__).with_name('run_qemu.py')),
                '--qemu',str(qemu),'--out',str(dest),'--soc-hw-version','0x60080201',
                '--devcfg',str(ROOT/'backups/nio-firmware-20260927T163534Z/devcfg_a.img'),
                '--secure-state-sample',str(ROOT/'reports/nio-scm-live-20260928-direct/manifest.json'),
                '--psci-version','0x10001','--smem-sample',str(ROOT/'reports/nio-smem-layout-20260928-v7/manifest.json'),
                '--smem-version-write','--smem-rlock-zero','--smem-mutex','--smem-ram-table-write',
                '--prng-word','0x736d656d','--gcc-mmu-clocks',enabled,'--smmu-ids',str(sample),
                '--qcom-timer','--smmu-control']
            if failure: command+=['--nonsecure-query-unsupported']
            subprocess.run(command,stdout=subprocess.DEVNULL,check=True)
            report=json.loads((dest/'manifest.json').read_text())
            stop=report['stop'] or {}
            if failure:
                passed=(stop.get('qhee_fault')=={'address':'0x784218','pc':'0x8006a908'}
                        and report['stdout'].count('MODEL_NONSECURE_QUERY_UNSUPPORTED')==1
                        and 'IsDeviceNonSecure failed' in report['stdout'])
            else:
                passed=(not stop.get('qhee_fault') and stop.get('registers',{}).get('x0')=='0xc2000310'
                        and stop['registers'].get('x1')=='0x0')
            passed=passed and not any(tag in report['stderr'] for tag in ('NIO_GCC_DENIED','NIO_MMU_DENIED','NIO_SMEM_DENIED'))
            results.append({'case':name,'passed':passed,'manifest':str(dest/'manifest.json')})
    report={'results':results,'smmu_ids':metadata,
            'qemu_sha256':hashlib.sha256(qemu.read_bytes()).hexdigest(),
            'source_sha256':hashlib.sha256((sources/'nio-gcc-mmu.c').read_bytes()).hexdigest(),
            'scope':'Single CPU control-path model, no DMA or phone EL2 handoff claim'}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for result in results: print(result['case'],'PASS' if result['passed'] else 'FAIL')
    if not all(r['passed'] for r in results): raise SystemExit('GCC/MMU regression failed')


if __name__=='__main__': main()
