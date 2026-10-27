#!/usr/bin/env python3
"""Original XBL stack frames, complete query args, SMC routing and QHEE forwarding."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
from qhee import ROOT,QheeImage
from test_entry import complete_args
from xbl_stack import contract,STOP,POINTS
from xbl_target import payload


class XblStackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'kernel-work/out/qhee-xbl-stack-tests';cls.out.mkdir(parents=True,exist_ok=True)
        cls.runner=Path(__file__).with_name('run_qemu.py');cls.tracer=Path(__file__).with_name('trace_bridge_handoff.py')
        cls.cases=[];cls.traces=[];cls.forwards=[]
        cls.backup=ROOT/'backups/nio-firmware-20260927T163534Z'
        cls.before={name:hashlib.sha256((cls.backup/name).read_bytes()).hexdigest() for name in ('hyp_a.img','xbl_a.img','tz_a.img','devcfg_a.img')}
        for profile in ('synthetic-masked','tz-frame-hcr-zero','tz-frame-hcr-rw'):
            for clock in (('off',) if profile=='synthetic-masked' else ('off','on')):
                for el2 in (False,True):
                    d=cls.out/(profile+'-'+clock+'-'+('el2' if el2 else 'stock'))
                    a=complete_args(clock,d);a[a.index('--payload-address')+1]='0x9fc00000'
                    a+=['--prepare-only','--xbl-workspace-sentinel','--entry-state-model',profile]
                    if el2:a+=['--handoff-experiment','el2-xbl-masked-mmu-off']
                    subprocess.run([sys.executable,str(cls.runner)]+a,check=True,stdout=subprocess.DEVNULL)
                    base=[sys.executable,str(cls.tracer),'--manifest',str(d/'manifest.json')]
                    subprocess.run(base+['--out',str(d/'trace'),'--xbl-stack-smc','--inspect-xbl-smc-route'],check=True,stdout=subprocess.DEVNULL)
                    case={'profile':profile,'clock':clock,'el2':el2,'manifest':str(d/'manifest.json'),'trace':str(d/'trace/manifest.json')}
                    cls.cases.append(case);cls.traces.append((case,json.loads(Path(case['trace']).read_text())))
                    if not el2:
                        subprocess.run(base+['--out',str(d/'forward'),'--xbl-stack-smc','--inspect-xbl-smc-route','--inspect-xbl-qhee-forward'],check=True,stdout=subprocess.DEVNULL)
                        case['forward_trace']=str(d/'forward/manifest.json');cls.forwards.append((case,json.loads(Path(case['forward_trace']).read_text())))
        (cls.out/'results.json').write_text(json.dumps(cls.cases,indent=2)+'\n')

    def test_pinned_original_contract(self):
        c=contract();b,m=payload();self.assertEqual(c['firmware_sha256'],m['firmware_sha256'])
        self.assertEqual(c['request_prefix'],['0x2000601','0x1','0x2000602'])
        for w in c['windows'].values():
            off=int(w['address'],16)-0x9fc00000;self.assertEqual(w['sha256'],hashlib.sha256(b[off:off+w['size']]).hexdigest())
        for off,expected in ((0x28568,'stack-source contract'),(STOP-0x9fc00000,'original stack-source SMC')):
            data=bytearray(b);data[off]^=1
            with patch('xbl_stack.payload',return_value=(bytes(data),m)):
                with self.assertRaisesRegex(ValueError,expected):contract()

    def test_original_empty_cache_and_selector_path(self):
        for case,t in self.traces:
            self.assertEqual(t['xbl_stack_contract'],contract());points=t['xbl_prefix_checkpoints']
            self.assertEqual([p['registers']['pc'] for p in points[-7:]],[hex(pc) for pc in POINTS])
            self.assertTrue(all(p['stack_globals']=={'0x9fc3d710':'0x0','0x9fc356c8':'0x0'} for p in points))
            by={p['name']:p['registers'] for p in points}
            self.assertEqual(by['stack-cache-read']['x8'],'0x0');d=by['stack-source-dispatch']
            self.assertEqual([d[n] for n in ('x0','x1','x2')],['0x0','0x9fc284b8','0x9fc284d0'])

    def test_original_stack_frames_and_write_bounds(self):
        for case,t in self.traces:
            by={p['name']:p for p in t['xbl_prefix_checkpoints']};last=by['stack-before-availability-smc']
            self.assertEqual(last['registers']['sp'],'0x9ffcffb0')
            expected=['0x9ffcffd0','0x9fc21ca4','0x0','0x40000','0x9ffcfff0','0x9fc21d00',by['sec-vectors-filled']['timestamp'],'0x0','0x0','0x9fc0cf2c']
            self.assertEqual(last['stack_words'],expected)
            self.assertEqual(last['untouched_bss_sha256'],hashlib.sha256(bytes(0x3ffb0)).hexdigest())
            for region in last['workspace_after']:
                self.assertEqual(region['guard_before_hex'],'a5'*16);self.assertEqual(region['guard_after_hex'],'a5'*16)
            vector=struct.pack('<Q',0xaa0403f314000000)*256
            self.assertEqual(last['workspace_after'][0]['sha256'],hashlib.sha256(vector).hexdigest())

    def test_complete_request_and_inherited_registers(self):
        for case,t in self.traces:
            last=t['xbl_prefix_checkpoints'][-1]
            self.assertEqual(last['registers']['pc'],hex(STOP))
            self.assertEqual(last['request'],['0x2000601','0x1','0x2000602','0x9ffd0000','0x0']+(['0x1','0x801cba78','0x0'] if case['el2'] else ['0x0','0x0','0x0']))
            self.assertEqual(last['request'],[last['registers']['x'+str(i)] for i in range(8)])

    def test_architectural_route_and_saved_context(self):
        for case,t in self.traces:
            before=t['xbl_prefix_checkpoints'][-1];route=t['xbl_smc_route'];r=route['after_instruction']
            self.assertEqual([r['x'+str(i)] for i in range(8)],before['request'])
            if case['el2']:
                self.assertEqual(route['destination'],'synthetic-el3-vector');self.assertEqual(r['pc'],'0x40200c00')
                self.assertEqual(int(r['cpsr'],16)&15,13);self.assertEqual(r['ESR_EL3'],'0x5e000000')
                self.assertEqual(r['ELR_EL3'],'0x9fc284e0');self.assertEqual(r['SPSR_EL3'],before['registers']['cpsr'])
            else:
                self.assertEqual(route['destination'],'original-qhee-el2-vector');self.assertEqual(r['pc'],'0x80093400')
                self.assertEqual(int(r['cpsr'],16)&15,9);self.assertEqual(r['ESR_EL2'],'0x5e000000')
                self.assertEqual(r['ELR_EL2'],'0x9fc284dc');self.assertEqual(r['SPSR_EL2'],before['registers']['cpsr'])

    def test_original_qhee_forwards_query_without_rewrite(self):
        self.assertEqual(len(self.forwards),5);image=QheeImage();base,code=image.code_bytes()
        for case,t in self.forwards:
            f=t['xbl_qhee_handler'];self.assertEqual(f['boundary'],'before-forwarded-smc')
            self.assertEqual(f['registers']['pc'],'0x80041cbc');self.assertEqual(f['registers']['sp'],'0x80208dc0')
            self.assertEqual(f['request'],t['xbl_prefix_checkpoints'][-1]['request']);self.assertEqual(f['calls'],[])
            self.assertEqual(f['registers']['SCTLR_EL2'],'0x8100f')
            self.assertEqual(len(f['bounded_smc_sites']),4)
            for address in f['bounded_smc_sites']:
                off=int(address,16)-base;self.assertEqual(code[off:off+4],bytes.fromhex('030000d4'))

    def test_cold_ledgers_evidence_and_firmware_unchanged(self):
        baseline=self.traces[0][1]
        for case,t in self.traces+self.forwards:
            self.assertEqual(t['calls'],baseline['calls']);self.assertEqual(t['pmic_map_ledger'],[6]*241)
            self.assertEqual(t['bridge_record_handle_before_eret'],'0x53484d0000000001')
            self.assertEqual(t['model_counts'],baseline['model_counts'])
            mpath=Path(case['manifest']);m=json.loads(mpath.read_text())
            self.assertEqual(t['input_manifest_sha256'],hashlib.sha256(mpath.read_bytes()).hexdigest())
            self.assertEqual(t['tool_sha256'],hashlib.sha256(self.tracer.read_bytes()).hexdigest())
            self.assertEqual(m['tool_sha256']['tools/hyp_re/xbl_stack.py'],contract()['source_sha256'])
            self.assertEqual(t['el3_sha256'],hashlib.sha256((mpath.parent/'el3.elf').read_bytes()).hexdigest())
        for name,h in self.before.items():self.assertEqual(hashlib.sha256((self.backup/name).read_bytes()).hexdigest(),h)

    def test_earlier_boundaries_still_stop(self):
        case=self.cases[-1];d=Path(case['manifest']).parent
        for flag,name,pc in (('--xbl-stack-smc','no-route',hex(STOP)),('--xbl-startup','startup','0x9fc0cf28')):
            subprocess.run([sys.executable,str(self.tracer),'--manifest',case['manifest'],'--out',str(d/name),flag],check=True,stdout=subprocess.DEVNULL)
            t=json.loads((d/name/'manifest.json').read_text());self.assertEqual(t['xbl_prefix_checkpoints'][-1]['registers']['pc'],pc)
            self.assertNotIn('xbl_smc_route',t);self.assertNotIn('xbl_qhee_handler',t)
            self.assertIn('monitor quit',(d/name/'trace.gdb').read_text());self.assertNotIn('\ndetach\n',(d/name/'trace.gdb').read_text())

    def test_cli_rejects_unbounded_or_wrong_level_followups(self):
        case=self.cases[-1]
        options=(['--inspect-xbl-smc-route'],['--inspect-xbl-qhee-forward'],
                 ['--xbl-startup','--xbl-stack-smc'],
                 ['--xbl-stack-smc','--inspect-xbl-smc-route','--inspect-xbl-qhee-forward'])
        for flags in options:
            r=subprocess.run([sys.executable,str(self.tracer),'--manifest',case['manifest'],'--out',str(self.out/'bad-cli')]+flags,capture_output=True,text=True)
            self.assertEqual(r.returncode,2);self.assertTrue('requires' in r.stderr or 'not allowed with' in r.stderr)


if __name__=='__main__':unittest.main()
