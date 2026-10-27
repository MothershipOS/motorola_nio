#!/usr/bin/env python3
"""PC-side unattended 30-minute power queue; archive/report before advancing."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import statistics
import subprocess
import sys
import tarfile
import threading
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SSH = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
       '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
       '-o', 'UserKnownHostsFile=/tmp/mothership-backup-audit-known-hosts', 'root@10.42.0.2']
SCP = ['scp', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
       '-o', 'UserKnownHostsFile=/tmp/mothership-backup-audit-known-hosts']
REMOTE_SCRIPT = '/usr/local/sbin/mship-power-test'
VM = '/var/lib/mothership/vms/pixelos'
VM_UNIT = 'mship-power-sweep-android'


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def command(argv, timeout=30, check=True):
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip() or f'Command exited {r.returncode}')
    return r


def phone(*argv, timeout=30, check=True):
    return command(SSH + [shlex.join(str(v) for v in argv)], timeout=timeout, check=check)


def python_phone(code, *args, timeout=30):
    return phone('python3', '-c', code, *args, timeout=timeout).stdout


def save(path, value):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    tmp.replace(path)


class Queue:
    def __init__(self, output, archive_target=None):
        self.archive_target = archive_target
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.manifest = json.loads((HERE / 'sweep.json').read_text())
        save(self.output / 'manifest.json', self.manifest)
        self.state = json.loads((self.output / 'status.json').read_text()) if (self.output / 'status.json').exists() else {
            'state': 'starting', 'started_utc': stamp(), 'completed': {}, 'failed': {}, 'vm_started': False}
        self.serial = None
        self.traffic = None
        self.bundle_installed = False

    def update(self, state, **values):
        self.state.update(state=state, updated_utc=stamp(), **values)
        save(self.output / 'status.json', self.state)
        print(stamp(), state, values, flush=True)
        self.report()
        if state in ('condition_recorded', 'condition_incomplete', 'condition_unavailable',
                     'complete', 'stopped_and_restored', 'cleanup_needs_attention'):
            self.sync_archive()

    def sync_archive(self):
        if self.archive_target:
            command(['rsync', '-a', '--partial', '--exclude=bundle.tar',
                     str(self.output) + '/', self.archive_target.rstrip('/') + '/'], timeout=180)

    def remote_output(self, phase):
        return self.manifest['phone_output'] + '/' + phase['id']

    def info(self, phase):
        code = '''import json,sys
from pathlib import Path
p=Path(sys.argv[1]); out={}
for name in ('status','summary','restoration'):
 f=p/(name+'.json')
 if f.exists(): out[name]=json.loads(f.read_text())
if (p/'original.json').exists(): out['original_mtime']=(p/'original.json').stat().st_mtime
f=p/'samples.jsonl';out['sample_bytes']=f.stat().st_size if f.exists() else 0
out['capacity']=int(Path('/sys/class/power_supply/battery/capacity').read_text())
out['temperature_C']=int(Path('/sys/class/power_supply/battery/temp').read_text())/10
print(json.dumps(out))'''
        return json.loads(python_phone(code, self.remote_output(phase)))

    def report(self):
        done = self.state['completed']
        failed = self.state['failed']
        rows = []
        results = []
        for c in self.manifest['comparisons']:
            ids = c['reference_ids'] + [c['option_id']]
            failure = next((failed[i] for i in ids if i in failed), None)
            if failure:
                row = [c['entry'], c['label'], 'Incomplete', '—', '—', '—']
            elif all(i in done for i in ids):
                ref = statistics.mean(done[i]['mean_mW'] for i in c['reference_ids'])
                opt = done[c['option_id']]['mean_mW']
                saving = ref - opt
                percent = 100 * saving / ref
                row = [c['entry'], c['label'], 'Measured', f'{ref:.1f}', f'{opt:.1f}', f'{saving:+.1f} ({percent:+.1f}%)']
                temps = [done[i]['mean_temperature_C'] for i in ids]
                result = dict(c, reference_mW=ref, option_mW=opt, saving_mW=saving,
                              saving_percent=percent, temperature_range_C=[min(temps), max(temps)])
                if max(temps) - min(temps) > 2:
                    result['caution'] = 'Mean temperature differs by more than 2 C; thermal drift limits attribution.'
                    row[2] = 'Measured; temperature drift'
                results.append(result)
            else:
                row = [c['entry'], c['label'], 'Pending', '—', '—', '—']
            rows.append('| ' + ' | '.join(row) + ' |')
        save(self.output / 'comparisons.json', results)
        active = self.state.get('phase', '—')
        lines = ['# Standby power measurements', '',
                 f"Queue: **{self.state['state']}**. Current condition: `{active}`. Updated: {self.state.get('updated_utc', stamp())}.", '',
                 f"Completed {len(done)}/{len(self.manifest['phases'])} conditions; {len(failed)} incomplete.", '',
                 'Each accepted condition samples for 30 minutes after five minutes of settling. Every condition is restored before the next.',
                 'USB power input is suspended; the cable remains attached. Logs use RAM. Settings and CPU idle counters are checked with the device awake.',
                 'Positive savings mean lower draw with the option. Matched control runs are used; these are estimates from one sweep, not independently calibrated power readings.', '',
                 '| Entry | Tested option | Status | Control mW | Option mW | Saving mW (%) |',
                 '|---|---|---|---:|---:|---:|', *rows, '', '## Completed conditions', '',
                 '| Condition | Minutes | Mean mA | Mean mW | Mean °C |', '|---|---:|---:|---:|---:|']
        for phase in self.manifest['phases']:
            if phase['id'] in done:
                s = done[phase['id']]
                lines.append(f"| {phase['label']} | {s['seconds']/60:.2f} | {s['mean_mA']:.1f} | {s['mean_mW']:.1f} | {s['mean_temperature_C']:.1f} |")
        lines += ['', '## Remaining coverage and dependencies', '']
        lines += ['- **' + k + ':** ' + v for k, v in self.manifest['remaining'].items()]
        if failed:
            lines += ['', '## Incomplete conditions', '']
            lines += ['- `' + k + '`: ' + str(v).replace('\n', ' ')[:1200] for k, v in failed.items()]
        lines += ['', 'Raw results and saved settings: `reports/standby/20261013-power-sweep/cases/` (untracked).',
                  'The queue pauses for recharging/cooling when necessary. No new sleep or VM-voting policy is enabled.',
                  f"Full queue: {len(self.manifest['phases'])} conditions, about {len(self.manifest['phases'])*35/60:.1f} hours plus recharge/cooldown time.", '']
        text = '\n'.join(lines)
        (self.output / 'results.md').write_text(text)
        doc = REPO / 'motorola_nio/docs/standby-measurements.md'
        tmp = doc.with_suffix('.md.tmp')
        try:
            tmp.write_text(text)
            tmp.replace(doc)
        except OSError as e:
            if e.errno != 28:
                raise
            print('PC disk full; live report remains at ' + str(self.output / 'results.md'), flush=True)

    def install_bundle(self):
        bundle = self.output / 'bundle.tar'
        with tarfile.open(bundle, 'w') as tar:
            tar.add(HERE / 'power_test.py', arcname='power_test.py')
            tar.add(HERE / 'cases', arcname='cases')
        command(SCP + [str(bundle), 'root@10.42.0.2:/tmp/mship-power-sweep-bundle.tar'])
        code = '''import os,shutil,tarfile
from pathlib import Path
root=Path('/usr/local/share/mship-power-tests');root.mkdir(parents=True,exist_ok=True)
with tarfile.open('/tmp/mship-power-sweep-bundle.tar') as t:t.extractall(root,filter='data')
target=Path('/usr/local/sbin/mship-power-test');tmp=target.with_suffix('.new')
shutil.copy2(root/'power_test.py',tmp);tmp.chmod(0o755);os.replace(tmp,target)
print('Extended harness and independent case scripts installed')'''
        print(python_phone(code), flush=True)
        self.bundle_installed = True

    def ready(self):
        deadline = time.monotonic() + 21600
        charging = False
        while time.monotonic() < deadline:
            code = '''import json
from pathlib import Path
b=Path('/sys/class/power_supply/battery')
print(json.dumps({'capacity':int((b/'capacity').read_text()),'temperature_C':int((b/'temp').read_text())/10,'status':(b/'status').read_text().strip(),'limit':int((b/'charge_control_end_threshold').read_text())}))'''
            values = json.loads(python_phone(code))
            if values['capacity'] < 40:
                charging = True
            threshold = min(values['limit'], 80) if charging else 40
            if values['capacity'] >= threshold and values['temperature_C'] <= 38:
                return
            self.update('recharging_or_cooling', battery=values)
            time.sleep(30)
        raise RuntimeError('Battery readiness timeout after six hours')

    def start_vm(self):
        if self.state['vm_started']:
            if not self.serial:
                conf = json.loads(phone('cat', VM + '/vm.json').stdout)
                self.serial = 'vsock:' + str(conf['cid']) + ':5555'
            return
        # The user approved temporary Android starts. Only this named unit is owned by the sweep.
        self.state['vm_started'] = True
        self.update('starting_android')
        r = phone('systemd-run', '--collect', '--unit=' + VM_UNIT, '--uid=mship', '--property=KillMode=mixed',
                  '--property=RuntimeMaxSec=10h',
                  '--property=TimeoutStopSec=90', '--setenv=XDG_RUNTIME_DIR=/run/mship-wayland',
                  '--setenv=WAYLAND_DISPLAY=wayland-1', '/usr/local/bin/mship-vm-pixelos-crosvm')
        print(r.stdout + r.stderr, flush=True)
        conf = json.loads(phone('cat', VM + '/vm.json').stdout)
        self.serial = 'vsock:' + str(conf['cid']) + ':5555'
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            phone('adb', 'connect', self.serial, check=False)
            r = phone('adb', '-s', self.serial, 'shell', 'getprop', 'sys.boot_completed', check=False)
            if r.returncode == 0 and r.stdout.strip() == '1':
                self.update('android_booted', serial=self.serial)
                return
            time.sleep(15)
        raise RuntimeError('Android did not boot/authorize ADB within 10 minutes')

    def stop_vm(self):
        if not self.state['vm_started']:
            return
        phone('/usr/local/sbin/mship-admin', 'vm-stop', VM, timeout=110)
        phone('systemctl', 'stop', VM_UNIT, timeout=110, check=False)
        self.state['vm_started'] = False
        self.serial = None
        self.update('android_stopped')

    def start_traffic(self):
        self.traffic_stop = threading.Event()
        self.traffic = subprocess.Popen(SSH + ['timeout 2300 cat > /dev/null'], stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.traffic_bytes = 0
        def send():
            block = bytes(256 * 1024)
            target = time.monotonic()
            try:
                while not self.traffic_stop.is_set():
                    self.traffic.stdin.write(block)
                    self.traffic.stdin.flush()
                    self.traffic_bytes += len(block)
                    target += .25
                    self.traffic_stop.wait(max(0, target - time.monotonic()))
            except (BrokenPipeError, OSError, ValueError):
                pass
        self.traffic_thread = threading.Thread(target=send, daemon=True)
        self.traffic_thread.start()

    def stop_traffic(self):
        if self.traffic:
            self.traffic_stop.set()
            self.traffic.terminate()
            try:
                self.traffic.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.traffic.kill()
            self.traffic_thread.join(timeout=5)
            self.traffic = None

    def run_phase(self, phase):
        self.update('running', phase=phase['id'], label=phase['label'])
        if not phase.get('adopt'):
            args = ['/usr/local/share/mship-power-tests/cases/' + phase['id'] + '.sh', '--output', self.remote_output(phase)]
            if phase.get('vm'):
                args += ['--adb-serial', self.serial]
            try:
                existing = self.info(phase)
                if 'original_mtime' not in existing:
                    phone(*args)
            except Exception as e:
                # CLI preflight is read-only and fails before launching the unit.
                if phone('systemctl', 'is-active', '--quiet', 'mship-power-test', check=False).returncode == 0:
                    raise
                self.state['failed'][phase['id']] = str(e)
                self.update('condition_unavailable', phase=phase['id'])
                return
            if phase.get('transfer'):
                self.start_traffic()
        deadline = time.monotonic() + 2700
        while time.monotonic() < deadline:
            try:
                info = self.info(phase)
            except Exception as e:
                # USB-unbound case deliberately removes SSH; local runtime limit/cleanup remain armed.
                self.update('waiting_for_usb', phase=phase['id'], detail=str(e))
                time.sleep(30)
                continue
            if info.get('restoration'):
                self.stop_traffic()
                self.archive(phase)
                if info['restoration']['errors']:
                    raise RuntimeError('Cleanup failed: ' + str(info['restoration']['errors']))
                if 'summary' not in info:
                    reason = phone('journalctl', '-u', 'mship-power-test', '-n', '25', '--no-pager').stdout
                    self.state['failed'][phase['id']] = reason
                    self.update('condition_incomplete', phase=phase['id'])
                    if 'screen changed' in reason or 'VMs changed' in reason:
                        raise RuntimeError('External phone/VM activity interrupted the sweep')
                    return
                summary = info['summary']
                if summary['seconds'] < 1799 or summary['samples'] < 590:
                    self.state['failed'][phase['id']] = 'Short measurement; not accepted as a 30-minute result'
                else:
                    self.state['completed'][phase['id']] = summary
                self.update('condition_recorded', phase=phase['id'])
                # ExecStopPost can still be finishing after restoration.json appears.
                for _ in range(30):
                    if phone('systemctl', 'is-active', '--quiet', 'mship-power-test', check=False).returncode != 0:
                        return
                    time.sleep(1)
                raise RuntimeError('Test unit remained active after completion')
            if phone('systemctl', 'is-active', '--quiet', 'mship-power-test', check=False).returncode != 0:
                reason = phone('journalctl', '-u', 'mship-power-test', '-n', '25', '--no-pager').stdout
                self.state['failed'][phase['id']] = reason
                self.update('condition_unavailable', phase=phase['id'])
                if phase.get('adopt'):
                    raise RuntimeError('Initial baseline missing; cannot establish the initial restoration snapshot')
                return
            self.update('measuring', phase=phase['id'], progress=info)
            time.sleep(30)
        raise RuntimeError('Condition timeout; local job must finish or be stopped before proceeding')

    def archive(self, phase):
        dest = self.output / 'cases' / phase['id']
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            command(SCP + ['-r', 'root@10.42.0.2:' + self.remote_output(phase), str(dest)], timeout=45)
        if phase.get('transfer'):
            save(dest / 'transfer.json', {'target_MiB_per_s': 1, 'uploaded_bytes': self.traffic_bytes})

    def cleanup(self):
        self.stop_traffic()
        errors = []
        try:
            phone('systemctl', 'stop', 'mship-power-test', check=False, timeout=330)
        except Exception as e:
            errors.append('test stop: ' + str(e))
        try:
            self.stop_vm()
        except Exception as e:
            errors.append('VM stop: ' + str(e))
        code = '''import json,subprocess,sys
from pathlib import Path
s=json.loads((Path(sys.argv[1])/'original.json').read_text())
b=Path('/sys/class/power_supply/battery');(b/'charge_behaviour').write_text(s['charge_behaviour'])
for name,values in s['cpu'].items():
 p=Path('/sys/devices/system/cpu/cpufreq')/name
 (p/'scaling_max_freq').write_text((p/'cpuinfo_max_freq').read_text())
 for k in ('scaling_min_freq','scaling_max_freq','scaling_governor'):(p/k).write_text(values[k])
subprocess.run(['runuser','-u','mship','--','env','XDG_RUNTIME_DIR=/run/mship-wayland','/usr/local/bin/mship-power',s['screen']],check=True)
if s['sleepd_active']:subprocess.run(['systemctl','start','mothershipd'],check=True)
print('Initial CPU/charging/display/sleep settings restored')'''
        try:
            print(python_phone(code, self.remote_output(self.manifest['phases'][0])), flush=True)
        except Exception as e:
            errors.append('initial settings: ' + str(e))
        if errors:
            raise RuntimeError('; '.join(errors))

    def run(self):
        try:
            for phase in self.manifest['phases']:
                if phase['id'] in self.state['completed'] or phase['id'] in self.state['failed']:
                    continue
                if not phase.get('adopt') and not self.bundle_installed:
                    self.install_bundle()
                if not phase.get('adopt'):
                    self.ready()
                if phase.get('vm'):
                    if self.state.get('android_unavailable'):
                        self.state['failed'][phase['id']] = self.state['android_unavailable']
                        self.update('condition_unavailable', phase=phase['id'])
                        continue
                    try:
                        self.start_vm()
                    except Exception as e:
                        self.state['android_unavailable'] = str(e)
                        self.state['failed'][phase['id']] = str(e)
                        self.update('android_unavailable', error=str(e))
                        self.stop_vm()
                        continue
                elif self.state['vm_started']:
                    self.stop_vm()
                self.run_phase(phase)
            self.update('measurements_finished', phase='—')
        except BaseException as e:
            self.update('stopped', error=str(e))
            raise
        finally:
            try:
                self.cleanup()
                self.update('complete' if self.state['state'] == 'measurements_finished' else 'stopped_and_restored')
            except Exception as e:
                self.update('cleanup_needs_attention', cleanup_error=str(e))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=REPO / 'reports/standby/20261013-power-sweep')
    parser.add_argument('--archive-target', help='Optional rsync destination for results after each condition')
    args = parser.parse_args()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda number, frame: sys.exit(128 + number))
    Queue(args.output, archive_target=args.archive_target).run()


if __name__ == '__main__':
    main()
