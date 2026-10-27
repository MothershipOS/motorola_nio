#!/usr/bin/env python3
"""Temporary nio battery tests, with USB power inhibited and automatic restoration."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import statistics
import subprocess
import sys
import time
import traceback

B = Path('/sys/class/power_supply/battery')
U = Path('/sys/class/power_supply/pm8150b-charger')
CPU = Path('/sys/devices/system/cpu/cpufreq')
BALANCED = {'policy0': 1804800, 'policy4': 2419200, 'policy7': 2841600}
POWERSAVE = {'policy0': 1516800, 'policy4': 1478400, 'policy7': 1516800}
DEVICES = {'gpu': '/sys/bus/platform/devices/3d00000.gpu',
           'ufs': '/sys/bus/platform/devices/1d84000.ufshc',
           'camss': '/sys/bus/platform/devices/ac6a000.camss',
           'usb-secondary': '/sys/bus/platform/devices/a6f8800.usb'}
TOUCH = '0:0:Novatek_NT36672C_Touchscreen'
SCRIPT = str(Path(__file__).resolve())


def read(path):
    return Path(path).read_text().strip()


def write(path, value):
    Path(path).write_text(str(value))


def run(*args):
    return subprocess.run(args, text=True, capture_output=True, timeout=15, check=True).stdout.strip()


def save(output, name, value):
    tmp = output / (name + '.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    tmp.replace(output / name)


def unit_command(values):
    """Quote transient ExecStopPost argv; $ expands but % is already literal."""
    return ' '.join('"' + str(v).replace('\\', '\\\\').replace('"', '\\"')
                    .replace('$', '$$') + '"' for v in values)


def active_behaviour(value):
    match = re.search(r'\[([^\]]+)\]', value)
    if not match:
        raise RuntimeError('Cannot identify active charge_behaviour: ' + value)
    return match[1]


def handover_status():
    """who holds which hardware (mothershipd's handover, via its command)"""
    r = subprocess.run(['/usr/local/bin/mship-handover', 'status'], capture_output=True, text=True)
    return json.loads(r.stdout or '{}')


def screen(action):
    if action == 'status':
        outputs = [o for o in sway('-t', 'get_outputs') if o['name'] == 'DSI-1']
        if outputs:
            return 'on' if outputs[0]['power'] else 'off'
        # Sway omits the panel while the existing handover handle leases it to a VM.
        owner = handover_status().get('display')
        value = read('/run/mothership/screen')
        if owner and owner != 'host' and value in ('on', 'off'):
            return value
        raise RuntimeError('Panel absent without a VM display lease')
    return run('runuser', '-u', 'mship', '--', 'env', 'XDG_RUNTIME_DIR=/run/mship-wayland',
               '/usr/local/bin/mship-power', action)


def sway(*args):
    socks = sorted(Path('/run/mship-wayland').glob('sway-ipc.*.sock'))
    if len(socks) != 1:
        raise RuntimeError('Expected one host compositor socket')
    result = run('runuser', '-u', 'mship', '--', 'env', 'XDG_RUNTIME_DIR=/run/mship-wayland',
                 'SWAYSOCK=' + str(socks[0]), 'swaymsg', *args)
    values = json.loads(result)
    if isinstance(values, list) and any(v.get('success') is False for v in values):
        raise RuntimeError('Compositor command failed: ' + result)
    return values


def process_identity(pid):
    try:
        stat = read(f'/proc/{pid}/stat').rsplit(')', 1)[1].split()
        return {'pid': pid, 'start_ticks': stat[19], 'state': stat[0]}
    except (FileNotFoundError, ProcessLookupError):
        return None


def named_processes(name):
    identities = []
    for p in Path('/proc').glob('[0-9]*/comm'):
        try:
            if read(p) == name:
                identity = process_identity(int(p.parent.name))
                if identity:
                    identities.append(identity)
        except (FileNotFoundError, ProcessLookupError):
            pass
    return identities


def device_observation():
    result = {}
    for name, base in DEVICES.items():
        result[name] = {}
        for key in ('control', 'runtime_status', 'runtime_active_time', 'runtime_suspended_time'):
            try:
                result[name][key] = read(Path(base) / 'power' / key)
            except OSError as e:
                result[name][key] = str(e)
    for name, args in (('wifi', ('iw', 'dev', 'wlp1s0', 'get', 'power_save')),
                       ('wifi_link', ('iw', 'dev', 'wlp1s0', 'link'))):
        try:
            result[name] = run(*args)
        except subprocess.CalledProcessError as e:
            result[name] = e.stderr.strip()
    result['bluetooth'] = {str(p): read(p / 'soft') for p in Path('/sys/class/rfkill').glob('rfkill*')
                           if read(p / 'type') == 'bluetooth'}
    result['bluetooth_adapter'] = run('bluetoothctl', 'show')
    result['usb_udc'] = {str(p): read(p) for p in Path('/sys/kernel/config/usb_gadget').glob('*/UDC')}
    result['brightness'] = read('/sys/class/backlight/backlight/brightness')
    result['screen_flag'] = read('/run/mothership/screen')
    result['inputs'] = sway('-t', 'get_inputs')
    result['interrupts'] = read('/proc/interrupts')
    try:
        result['suspend_success'] = read('/sys/power/suspend_stats/success')
    except OSError:
        result['suspend_success'] = 'unavailable'
    try:
        result['wakeup_sources'] = read('/sys/kernel/debug/wakeup_sources')
    except OSError:
        pass
    return result


def adb(serial, *args):
    return run('adb', '-s', serial, 'shell', *args)


def vm_pids():
    result = []
    for p in Path('/proc').glob('[0-9]*/comm'):
        try:
            name = read(p)
            # crosvm --name changes comm to the guest name (for example pixelos).
            # Check the executable too, so named VMs cannot evade host/guest guards.
            if name == 'crosvm' or name.startswith('qemu-system-'):
                result.append(int(p.parent.name))
            else:
                executable = (p.parent / 'exe').readlink().name.removesuffix(' (deleted)')
                if executable == 'crosvm' or executable.startswith('qemu-system-'):
                    result.append(int(p.parent.name))
        except (FileNotFoundError, ProcessLookupError):
            pass
    return sorted(result)


def idle_counters():
    return {str(p): {'name': read(p / 'name'), 'disabled': read(p / 'disable'),
                     'time_us': int(read(p / 'time')), 'usage': int(read(p / 'usage'))}
            for p in Path('/sys/devices/system/cpu').glob('cpu[0-9]*/cpuidle/state*')}


def bluetooth_power(value):
    """rfkill unblocking starts firmware setup; wait for actual BlueZ power state."""
    deadline = time.monotonic() + 30
    last_error = None
    while True:
        if 'Powered: ' + value in run('bluetoothctl', 'show'):
            return
        try:
            run('bluetoothctl', 'power', 'on' if value == 'yes' else 'off')
        except subprocess.CalledProcessError as e:
            last_error = e.stderr or e.stdout
        if 'Powered: ' + value in run('bluetoothctl', 'show'):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('Bluetooth adapter power did not settle: ' + str(last_error))
        time.sleep(.5)


def sample():
    current = int(read(B / 'current_now'))
    voltage = int(read(B / 'voltage_now'))
    lines = read('/proc/stat').splitlines()
    return {'monotonic': time.monotonic(), 'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'current_uA': current,
            'draw_mA': -current / 1000, 'draw_mW': -current * voltage / 1e9,
            'voltage_uV': voltage, 'temperature_C': int(read(B / 'temp')) / 10,
            'capacity_percent': int(read(B / 'capacity')),
            'cpu_ticks': [int(v) for v in lines[0].split()[1:9]],
            'interrupts': int(next(s for s in lines if s.startswith('intr ')).split()[1]),
            'context_switches': int(next(s for s in lines if s.startswith('ctxt ')).split()[1]),
            'frequencies_kHz': {p.name: int(read(p / 'scaling_cur_freq')) for p in CPU.glob('policy*')}}


def guard(pids, discharge=True, expected_screen='off'):
    if int(read(B / 'capacity')) < 20 or int(read(B / 'temp')) >= 420:
        raise RuntimeError('Battery below 20% or at/above 42 C')
    if vm_pids() != pids:
        raise RuntimeError('Running VMs changed during the test')
    if discharge and (read(U / 'online') != '0' or read(B / 'status') != 'Discharging'
                      or int(read(B / 'current_now')) >= 0):
        raise RuntimeError('USB still powers the phone or battery is not discharging; no valid measurement')
    if discharge and read('/run/mothership/screen') != expected_screen:
        raise RuntimeError('Host screen changed during the test')


def guest_snapshot(serial):
    power = adb(serial, 'dumpsys', 'power')
    idle = adb(serial, 'dumpsys', 'deviceidle')
    battery = adb(serial, 'dumpsys', 'battery')
    wake = re.search(r'\bmWakefulness=(\w+)', power)
    if not wake or wake[1] not in ('Awake', 'Asleep'):
        raise RuntimeError('Guest must be fully Awake or Asleep before testing')
    if 'UPDATES STOPPED' in battery or 'mForceIdle=true' in idle:
        raise RuntimeError('Guest already has a forced battery/Doze state; reset it before testing')
    enabled = {}
    for kind in ('Deep', 'Light'):
        match = re.search(r'\bm' + kind + r'Enabled=(true|false)', idle)
        if not match:
            raise RuntimeError('Cannot snapshot guest Doze settings')
        enabled[kind.lower()] = match[1] == 'true'
    return {'serial': serial, 'wakefulness': wake[1], 'enabled': enabled,
            'power': power, 'idle': idle, 'battery': battery,
            'screen_timeout': adb(serial, 'settings', 'get', 'system', 'screen_off_timeout')}


def preflight(args):
    if os.geteuid() != 0:
        raise RuntimeError('Run on the nio host as root')
    behaviour = read(B / 'charge_behaviour')
    if 'force-discharge' not in behaviour.replace('[', '').replace(']', '').split():
        raise RuntimeError('Charger driver lacks force-discharge. Install the updated PM8150B module first; '
                           'inhibit-charge alone cannot measure phone power with USB attached.')
    if set(p.name for p in CPU.glob('policy*')) != set(BALANCED):
        raise RuntimeError('Unexpected CPU layout; this harness is for nio/SM8250')
    pids = vm_pids()
    guard(pids, discharge=False)
    if (args.mode == 'host' and pids) or (args.mode != 'host' and len(pids) != 1):
        raise RuntimeError('Host test needs no VMs; Android tests need exactly one running VM')
    state = {'boot_id': read('/proc/sys/kernel/random/boot_id'), 'mode': args.mode,
             'charge_behaviour': active_behaviour(behaviour), 'usb_online': read(U / 'online'),
             'screen': screen('status'), 'pids': pids, 'kernel': run('uname', '-r'),
             'sleepd_active': subprocess.run(['systemctl', 'is-active', '--quiet', 'mothershipd']).returncode == 0,
             'cpu': {p.name: {k: read(p / k) for k in ('scaling_min_freq', 'scaling_max_freq', 'scaling_governor')}
                     for p in CPU.glob('policy*')}}
    state['harness_sha256'] = hashlib.sha256(Path(SCRIPT).read_bytes()).hexdigest()
    state['persistent_configs'] = {str(p): read(p) for p in
                                  (Path('/etc/mothership/cpu.json'), Path('/etc/mothership/power.json'),
                                   Path('/etc/mothership/battery.json'))}
    if state['screen'] not in ('on', 'off'):
        raise RuntimeError('Cannot read host display power')
    if args.mode != 'host':
        if not args.adb_serial:
            raise RuntimeError('Specify the Android VM transport with --adb-serial')
        state['guest'] = guest_snapshot(args.adb_serial)
    state['test_screen'] = args.screen
    state['parameters'] = {k: getattr(args, k) for k in
                           ('profile', 'screen', 'touch', 'deep_idle', 'wifi_power_save', 'wifi_radio',
                            'bluetooth', 'runtime_device', 'runtime_control', 'usb_data', 'pause_pwrkey_poll')}
    state['screen_flag'] = read('/run/mothership/screen')
    state['idle_disable'] = {str(p / 'disable'): read(p / 'disable') for p in
                             Path('/sys/devices/system/cpu').glob('cpu[0-9]*/cpuidle/state*')}
    state['extras'] = {'brightness': read('/sys/class/backlight/backlight/brightness'),
                       'touch': next(v['libinput']['send_events'] for v in sway('-t', 'get_inputs')
                                     if v['identifier'] == TOUCH),
                       'swayidle': named_processes('swayidle'),
                       'wifi_ps': run('iw', 'dev', 'wlp1s0', 'get', 'power_save').split()[-1],
                       'wifi_radio': run('nmcli', 'radio', 'wifi'),
                       'wifi_link': run('iw', 'dev', 'wlp1s0', 'link'),
                       'bt_soft': {str(p / 'soft'): read(p / 'soft') for p in Path('/sys/class/rfkill').glob('rfkill*')
                                   if read(p / 'type') == 'bluetooth'},
                       'bt_powered': re.search(r'Powered: (yes|no)', run('bluetoothctl', 'show')).group(1),
                       'runtime': {str(Path(v) / 'power/control'): read(Path(v) / 'power/control') for v in DEVICES.values()},
                       'udc': {str(p): read(p) for p in Path('/sys/kernel/config/usb_gadget').glob('*/UDC')},
                       'pwrkey_active': subprocess.run(['systemctl', 'is-active', '--quiet', 'mship-pwrkey-rearm']).returncode == 0}
    if args.pause_pwrkey_poll and (args.usb_data != 'keep' or args.mode != 'host'):
        raise RuntimeError('Power-key polling may only be paused during an awake host test with USB data')
    if args.usb_data == 'off' and args.mode != 'host':
        raise RuntimeError('USB data isolation is limited to host-only tests')
    if args.usb_data == 'off' and not any(state['extras']['udc'].values()):
        raise RuntimeError('No bound configfs USB gadget is available for the USB data comparison')
    return state


def restore(output):
    original = output / 'original.json'
    if not original.exists():
        return
    marker = output / 'restoration.json'
    if marker.exists() and not json.loads(marker.read_text())['errors']:
        return
    state = json.loads(original.read_text())
    if state['boot_id'] != read('/proc/sys/kernel/random/boot_id'):
        raise RuntimeError('Refusing to restore a snapshot from a different boot')
    errors = []

    def attempt(label, action):
        try:
            action()
        except Exception as e:
            errors.append(label + ': ' + str(e))

    extra = state.get('extras', {})
    # Restore the control link before charging or trying guest cleanup.
    for path, value in extra.get('udc', {}).items():
        def usb_restore(path=path, value=value):
            if read(path) != value:
                write(path, value + '\n')
        attempt('USB data', usb_restore)
    # Restore power even if the guest has crashed or ADB no longer responds.
    def charging():
        write(B / 'charge_behaviour', state['charge_behaviour'])
        for _ in range(50):
            policy_ok = active_behaviour(read(B / 'charge_behaviour')) == state['charge_behaviour']
            power_ok = (state['charge_behaviour'] == 'force-discharge' or state['usb_online'] == '0'
                        or read(U / 'present') == '0' or read(U / 'online') == '1')
            if policy_ok and power_ok:
                return
            time.sleep(.2)
        raise RuntimeError('Charger policy/power path did not restore within 10 seconds')

    attempt('charging', charging)
    for path, value in state.get('idle_disable', {}).items():
        attempt('idle ' + path, lambda path=path, value=value: write(path, value))
    for path, value in extra.get('runtime', {}).items():
        attempt('runtime ' + path, lambda path=path, value=value: write(path, value))
    for path, value in extra.get('bt_soft', {}).items():
        attempt('Bluetooth', lambda path=path, value=value: write(path, value))
    if extra.get('bt_powered'):
        attempt('Bluetooth adapter power', lambda: bluetooth_power(extra['bt_powered']))
    if extra:
        attempt('Wi-Fi radio', lambda: run('nmcli', 'radio', 'wifi', 'on' if extra['wifi_radio'] == 'enabled' else 'off'))
        if extra['wifi_radio'] == 'enabled':
            def wifi_restore():
                for i in range(60):
                    try:
                        run('iw', 'dev', 'wlp1s0', 'set', 'power_save', extra['wifi_ps'])
                        if extra.get('wifi_link', '').startswith('Connected') and not run('iw', 'dev', 'wlp1s0', 'link').startswith('Connected'):
                            raise RuntimeError('Wi-Fi has not reassociated')
                        return
                    except Exception:
                        if i == 59:
                            raise
                        time.sleep(1)
            attempt('Wi-Fi power save/association', wifi_restore)
        if extra['pwrkey_active']:
            attempt('power key recovery', lambda: run('systemctl', 'start', 'mship-pwrkey-rearm'))
    for name, values in state['cpu'].items():
        def frequency(name=name, values=values):
            p = CPU / name
            write(p / 'scaling_max_freq', read(p / 'cpuinfo_max_freq'))
            for key in ('scaling_min_freq', 'scaling_max_freq', 'scaling_governor'):
                write(p / key, values[key])
            if any(read(p / key) != value for key, value in values.items()):
                raise RuntimeError('CPU setting readback differs')
        attempt(name, frequency)
    if 'guest' in state:
        guest = state['guest']
        serial = guest['serial']
        attempt('guest unforce', lambda: adb(serial, 'dumpsys', 'deviceidle', 'unforce'))
        attempt('guest battery', lambda: adb(serial, 'dumpsys', 'battery', 'reset'))
        for kind, enabled in guest['enabled'].items():
            attempt('guest ' + kind, lambda kind=kind, enabled=enabled:
                    adb(serial, 'dumpsys', 'deviceidle', 'enable' if enabled else 'disable', kind))
        def guest_settings():
            idle = adb(serial, 'dumpsys', 'deviceidle')
            for kind, enabled in guest['enabled'].items():
                if 'm' + kind.title() + 'Enabled=' + str(enabled).lower() not in idle:
                    raise RuntimeError('Doze enable readback differs: ' + kind)
            if 'UPDATES STOPPED' in adb(serial, 'dumpsys', 'battery'):
                raise RuntimeError('Guest battery simulation remains active')
        attempt('guest settings readback', guest_settings)
        attempt('guest display', lambda: adb(serial, 'input', 'keyevent',
                'KEYCODE_WAKEUP' if guest['wakefulness'] == 'Awake' else 'KEYCODE_SLEEP'))
        if 'screen_timeout' in guest:
            value = guest['screen_timeout']
            attempt('guest timeout', lambda: adb(serial, 'settings', 'delete' if value == 'null' else 'put',
                    'system', 'screen_off_timeout', *([] if value == 'null' else [value])))
    attempt('host display', lambda: screen(state['screen']))
    if extra:
        attempt('brightness', lambda: write('/sys/class/backlight/backlight/brightness', extra['brightness']))
        attempt('touch', lambda: sway('input', TOUCH, 'events', extra['touch']))
        attempt('screen flag', lambda: write('/run/mothership/screen', state['screen_flag']))
        for identity in extra['swayidle']:
            current = process_identity(identity['pid'])
            if current and current['start_ticks'] == identity['start_ticks'] and identity['state'] != 'T':
                attempt('idle timeout', lambda pid=identity['pid']: os.kill(pid, signal.SIGCONT))
    if state['sleepd_active']:
        attempt('sleep daemon', lambda: run('systemctl', 'start', 'mothershipd'))
    save(output, 'restoration.json', {'errors': errors, 'restored_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
    if errors:
        raise RuntimeError('Restoration incomplete: ' + '; '.join(errors))


def guest_guard(state):
    if 'guest' not in state:
        return
    serial = state['guest']['serial']
    deep = adb(serial, 'dumpsys', 'deviceidle', 'get', 'deep')
    if state['mode'] == 'doze' and deep != 'IDLE':
        raise RuntimeError('Guest did not remain in forced deep Doze: ' + deep)
    if state['mode'] == 'android' and deep != 'ACTIVE':
        raise RuntimeError('Android baseline unexpectedly entered Doze: ' + deep)
    wakefulness = 'Asleep' if state.get('test_screen', 'off') == 'off' else 'Awake'
    if not re.search(r'\bmWakefulness=' + wakefulness + r'\b', adb(serial, 'dumpsys', 'power')):
        raise RuntimeError('Guest screen state changed')


def condition_check(args, state):
    """Reject a requested option that did not actually take effect."""
    if args.mode == 'host' and screen('status') != args.screen:
        raise RuntimeError('Physical host output power differs from the requested screen state')
    for p in CPU.glob('policy*'):
        maximum = int(read(p / 'cpuinfo_max_freq'))
        cap = {'balanced': BALANCED[p.name], 'powersave': POWERSAVE[p.name],
               'minimum': int(read(p / 'cpuinfo_min_freq')), 'performance': maximum}[args.profile]
        if int(read(p / 'scaling_max_freq')) != min(cap, maximum):
            raise RuntimeError('CPU profile cap changed during test: ' + p.name)
        governor = 'performance' if args.profile == 'performance' else 'schedutil'
        if read(p / 'scaling_governor') != governor:
            raise RuntimeError('CPU governor changed during test: ' + p.name)
    if args.runtime_device:
        base = Path(DEVICES[args.runtime_device]) / 'power'
        if read(base / 'control') != args.runtime_control:
            raise RuntimeError('Runtime-PM request did not take effect')
        if args.runtime_control == 'on' and read(base / 'runtime_status') != 'active':
            raise RuntimeError('Device did not become active for runtime-PM control measurement')
    if args.wifi_power_save != 'keep' and run('iw', 'dev', 'wlp1s0', 'get', 'power_save').split()[-1] != args.wifi_power_save:
        raise RuntimeError('Wi-Fi power-save request did not take effect')
    if args.wifi_radio != 'keep':
        expected = 'disabled' if args.wifi_radio == 'off' else 'enabled'
        if run('nmcli', 'radio', 'wifi') != expected:
            raise RuntimeError('Wi-Fi radio request did not take effect')
    if args.bluetooth != 'keep':
        expected = 'yes' if args.bluetooth == 'on' else 'no'
        if 'Powered: ' + expected not in run('bluetoothctl', 'show'):
            raise RuntimeError('Bluetooth radio request did not take effect')
    if args.deep_idle == 'wfi-only':
        for path, value in state['idle_disable'].items():
            if Path(path).parent.name != 'state0' and value == '0' and read(path) != '1':
                raise RuntimeError('Deeper CPU idle was re-enabled during the WFI-only condition')
    if args.usb_data == 'off' and any(read(path) for path in state['extras']['udc']):
        raise RuntimeError('USB data was rebound during the test')
    if args.touch != 'keep':
        value = next(v['libinput']['send_events'] for v in sway('-t', 'get_inputs') if v['identifier'] == TOUCH)
        if value != args.touch:
            raise RuntimeError('Touch delivery state changed during the test')
    for path, value in state['persistent_configs'].items():
        if read(path) != value:
            raise RuntimeError('Persistent configuration changed during test: ' + path)


def worker(args, output):
    with open('/run/lock/mship-power-test.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = preflight(args)
        save(output, 'original.json', state)
        try:
            if state['sleepd_active']:
                run('systemctl', 'stop', 'mothershipd')
            for p in CPU.glob('policy*'):
                write(p / 'scaling_max_freq', read(p / 'cpuinfo_max_freq'))
                write(p / 'scaling_min_freq', read(p / 'cpuinfo_min_freq'))
                maximum = int(read(p / 'cpuinfo_max_freq'))
                cap = {'balanced': BALANCED[p.name], 'powersave': POWERSAVE[p.name],
                       'minimum': int(read(p / 'cpuinfo_min_freq')), 'performance': maximum}[args.profile]
                write(p / 'scaling_max_freq', min(cap, maximum))
                write(p / 'scaling_governor', 'performance' if args.profile == 'performance' else 'schedutil')
            for identity in state['extras']['swayidle']:
                if identity['state'] != 'T':
                    os.kill(identity['pid'], signal.SIGSTOP)
            if args.deep_idle == 'wfi-only':
                for path, value in state['idle_disable'].items():
                    if Path(path).parent.name != 'state0' and value == '0':
                        write(path, '1')
            if args.wifi_power_save != 'keep':
                run('iw', 'dev', 'wlp1s0', 'set', 'power_save', args.wifi_power_save)
            if args.wifi_radio != 'keep':
                run('nmcli', 'radio', 'wifi', args.wifi_radio)
            if args.bluetooth != 'keep':
                if args.bluetooth == 'off':
                    bluetooth_power('no')
                for path in state['extras']['bt_soft']:
                    write(path, '1' if args.bluetooth == 'off' else '0')
                if args.bluetooth == 'on':
                    bluetooth_power('yes')
            if args.runtime_device:
                write(Path(DEVICES[args.runtime_device]) / 'power/control', args.runtime_control)
            if args.pause_pwrkey_poll:
                run('systemctl', 'stop', 'mship-pwrkey-rearm')
            if 'guest' in state:
                serial = state['guest']['serial']
                adb(serial, 'dumpsys', 'battery', 'unplug')
                if args.screen == 'on':
                    adb(serial, 'settings', 'put', 'system', 'screen_off_timeout', '2147483647')
                adb(serial, 'input', 'keyevent', 'KEYCODE_SLEEP' if args.screen == 'off' else 'KEYCODE_WAKEUP')
                adb(serial, 'dumpsys', 'deviceidle', 'disable', 'all')
                if args.mode == 'doze':
                    adb(serial, 'dumpsys', 'deviceidle', 'enable', 'deep')
                    adb(serial, 'dumpsys', 'deviceidle', 'force-idle', 'deep')
            screen(args.screen)
            if args.touch != 'keep':
                sway('input', TOUCH, 'events', args.touch)
            if args.usb_data == 'off':
                for path in state['extras']['udc']:
                    write(path, '\n')
            write(B / 'charge_behaviour', 'force-discharge')
            deadline = time.monotonic() + 15
            while True:
                try:
                    guard(state['pids'], expected_screen=args.screen)
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.5)
            guest_guard(state)
            print(f'{args.mode}: battery discharge confirmed; settling {args.settle}s', flush=True)
            save(output, 'status.json', {'state': 'settling', 'seconds': args.settle, 'parameters': state['parameters']})
            deadline = time.monotonic() + args.settle
            while time.monotonic() < deadline:
                guard(state['pids'], expected_screen=args.screen)
                time.sleep(min(args.interval, max(0, deadline - time.monotonic())))
            guest_guard(state)
            condition_check(args, state)
            observation_before = device_observation()
            save(output, 'status.json', {'state': 'measuring', 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                                         'seconds': args.seconds, 'parameters': state['parameters']})
            before_idle = idle_counters()
            first = sample()
            data = []
            start = time.monotonic()
            next_sample = start
            with (output / 'samples.jsonl').open('w') as samples:
                while time.monotonic() - start < args.seconds:
                    guard(state['pids'], expected_screen=args.screen)
                    value = sample()
                    if value['draw_mA'] <= 0:
                        raise RuntimeError('Non-discharge sample; measurement is invalid')
                    data.append(value)
                    samples.write(json.dumps(value) + '\n')
                    samples.flush()
                    next_sample += args.interval
                    time.sleep(max(0, next_sample - time.monotonic()))
            guard(state['pids'], expected_screen=args.screen)
            last = sample()
            elapsed = time.monotonic() - start
            after_idle = idle_counters()
            guest_guard(state)
            condition_check(args, state)
            ticks = [b - a for a, b in zip(first['cpu_ticks'], last['cpu_ticks'])]
            total = sum(ticks)
            summary = {'mode': args.mode, 'seconds': elapsed, 'samples': len(data),
                       'parameters': state['parameters'], 'environment_before': observation_before,
                       'environment_after': device_observation(),
                       'mean_mA': statistics.mean(s['draw_mA'] for s in data),
                       'mean_mW': statistics.mean(s['draw_mW'] for s in data),
                       'mean_temperature_C': statistics.mean(s['temperature_C'] for s in data),
                       'cpu_busy_percent': 100 * (1 - (ticks[3] + ticks[4]) / total) if total else None,
                       'interrupts_per_s': (last['interrupts'] - first['interrupts']) / elapsed,
                       'context_switches_per_s': (last['context_switches'] - first['context_switches']) / elapsed,
                       'idle': {p: {'name': v['name'], 'disabled': v['disabled'],
                                     'residency_percent': 100 * (after_idle[p]['time_us'] - v['time_us']) / 1e6 / elapsed,
                                     'entries': after_idle[p]['usage'] - v['usage']} for p, v in before_idle.items()},
                       'note': 'Whole-phone battery gauge; USB data remains connected. Absolute gauge calibration unverified.'}
            save(output, 'summary.json', summary)
            save(output, 'status.json', {'state': 'complete', 'seconds': elapsed, 'samples': len(data)})
            print(f"{args.mode}: {summary['mean_mA']:.1f} mA, {summary['mean_mW']:.0f} mW; results {output}", flush=True)
        except BaseException as e:
            save(output, 'failure.json', {'error': str(e), 'exception': type(e).__name__,
                                         'traceback': traceback.format_exc()})
            raise
        finally:
            restore(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', choices=('host', 'android', 'doze'), default='host')
    parser.add_argument('--adb-serial', help='Explicit Android VM transport, e.g. vsock:3:5555; no fixed CID assumption')
    parser.add_argument('--seconds', type=int, default=300)
    parser.add_argument('--settle', type=int, default=60)
    parser.add_argument('--interval', type=float, default=3)
    parser.add_argument('--profile', choices=('balanced', 'powersave', 'minimum', 'performance'), default='balanced')
    parser.add_argument('--screen', choices=('on', 'off'), default='off')
    parser.add_argument('--touch', choices=('keep', 'enabled', 'disabled'), default='disabled')
    parser.add_argument('--deep-idle', choices=('existing', 'wfi-only'), default='existing')
    parser.add_argument('--wifi-power-save', choices=('keep', 'on', 'off'), default='keep')
    parser.add_argument('--wifi-radio', choices=('keep', 'on', 'off'), default='keep')
    parser.add_argument('--bluetooth', choices=('keep', 'on', 'off'), default='keep')
    parser.add_argument('--runtime-device', choices=tuple(DEVICES))
    parser.add_argument('--runtime-control', choices=('on', 'auto'), default='auto')
    parser.add_argument('--usb-data', choices=('keep', 'off'), default='keep')
    parser.add_argument('--pause-pwrkey-poll', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', action='store_true', help='Read-only readiness check')
    parser.add_argument('--restore', action='store_true', help='Restore the snapshot in --output')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.mode == 'doze' and args.screen != 'off':
        parser.error('Doze test requires the screen off')
    if not (10 <= args.seconds <= 1800 and 0 <= args.settle <= 300 and 1 <= args.interval <= min(30, args.seconds)):
        parser.error('Use 10..1800 seconds, 0..300 settle seconds, and 1..30 second interval <= duration')
    if args.restore:
        if not args.output:
            parser.error('--restore requires --output')
        with open('/run/lock/mship-power-test.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            restore(args.output)
    elif args.check:
        preflight(args)
        print('Ready: force-discharge supported and prerequisites checked; no settings changed')
    elif args.worker:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, lambda signum, frame: sys.exit(128 + signum))
        worker(args, args.output)
    else:
        preflight(args)
        output = (args.output or Path('/var/tmp') / ('mship-power-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))).resolve()
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        unit = 'mship-power-test'
        command = ['python3', SCRIPT, args.mode, '--worker', '--output', str(output),
                   '--seconds', str(args.seconds), '--settle', str(args.settle), '--interval', str(args.interval)]
        if args.adb_serial:
            command += ['--adb-serial', args.adb_serial]
        for key, value in vars(args).items():
            if key in ('profile', 'screen', 'touch', 'deep_idle', 'wifi_power_save', 'wifi_radio',
                       'bluetooth', 'runtime_control', 'usb_data', 'runtime_device') and value is not None:
                command += ['--' + key.replace('_', '-'), str(value)]
        if args.pause_pwrkey_poll:
            command += ['--pause-pwrkey-poll']
        cleanup = unit_command(('python3', SCRIPT, '--restore', '--output', output))
        # Journal logging and local lifetime survive losing the USB SSH connection.
        run('systemd-run', '--collect', '--unit=' + unit, '--property=RuntimeMaxSec=' + str(args.seconds + args.settle + 240),
            '--property=TimeoutStopSec=300', '--property=UMask=0077',
            '--property=ExecStopPost=' + cleanup,
            'systemd-inhibit', '--what=sleep', '--mode=block', '--who=mship-power-test', *command)
        print(f'Started {unit}\nResults: {output}\nProgress: journalctl -fu {unit}\nStop and restore: systemctl stop {unit}')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('Power test failed: ' + str(e), file=sys.stderr)
        sys.exit(1)
