"""Failure-path checks for the battery measurement harness; no hardware required."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('power_test', Path(__file__).with_name('power_test.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PowerTest(unittest.TestCase):
    def test_exited_process_does_not_abort_vm_sampling(self):
        with patch.object(p.Path, 'glob', return_value=[Path('/proc/123/comm'), Path('/proc/456/comm')]), \
             patch.object(p, 'read', side_effect=[ProcessLookupError(3, 'No such process'), 'crosvm']):
            self.assertEqual(p.vm_pids(), [456])

    def test_named_crosvm_is_detected_by_executable(self):
        with patch.object(p.Path, 'glob', return_value=[Path('/proc/123/comm')]), \
             patch.object(p, 'read', return_value='pixelos'), \
             patch.object(p.Path, 'readlink', return_value=Path('/opt/mship-gpu/bin/crosvm')):
            self.assertEqual(p.vm_pids(), [123])

    def test_non_vm_executable_is_not_counted(self):
        with patch.object(p.Path, 'glob', return_value=[Path('/proc/123/comm')]), \
             patch.object(p, 'read', return_value='python3'), \
             patch.object(p.Path, 'readlink', return_value=Path('/usr/bin/python3')):
            self.assertEqual(p.vm_pids(), [])

    def test_process_exiting_before_executable_read_does_not_abort_scan(self):
        with patch.object(p.Path, 'glob', return_value=[Path('/proc/123/comm')]), \
             patch.object(p, 'read', return_value='pixelos'), \
             patch.object(p.Path, 'readlink', side_effect=FileNotFoundError()):
            self.assertEqual(p.vm_pids(), [])

    def test_exited_process_does_not_abort_idle_process_snapshot(self):
        with patch.object(p, 'read', side_effect=ProcessLookupError(3, 'No such process')):
            self.assertIsNone(p.process_identity(123))
        with patch.object(p.Path, 'glob', return_value=[Path('/proc/123/comm')]), \
             patch.object(p, 'read', side_effect=ProcessLookupError(3, 'No such process')):
            self.assertEqual(p.named_processes('swayidle'), [])

    def test_bluetooth_firmware_setup_error_can_settle_to_success(self):
        setup_error = subprocess.CalledProcessError(1, ['bluetoothctl', 'power', 'on'], stderr='In progress')
        with patch.object(p, 'run', side_effect=['Powered: no', setup_error, 'Powered: no', 'Powered: yes']), \
             patch.object(p.time, 'sleep'):
            p.bluetooth_power('yes')

    def test_bluetooth_already_restored_does_not_repeat_power_command(self):
        with patch.object(p, 'run', return_value='Powered: yes') as run:
            p.bluetooth_power('yes')
            run.assert_called_once_with('bluetoothctl', 'show')

    def test_leased_panel_status_uses_existing_shared_screen_handle(self):
        with patch.object(p, 'sway', return_value=[]), \
             patch.object(p, 'handover_status', return_value={'display': '/var/lib/mothership/vms/pixelos'}), \
             patch.object(p, 'read', side_effect=['off']):
            self.assertEqual(p.screen('status'), 'off')

    def test_absent_panel_without_lease_is_rejected(self):
        with patch.object(p, 'sway', return_value=[]), \
             patch.object(p, 'handover_status', return_value={'display': 'host'}), \
             patch.object(p, 'read', side_effect=['off']):
            with self.assertRaisesRegex(RuntimeError, 'absent without'):
                p.screen('status')

    def test_host_panel_status_reads_actual_compositor_power(self):
        with patch.object(p, 'sway', return_value=[{'name':'DSI-1','power':True}]), \
             patch.object(p, 'read') as read:
            self.assertEqual(p.screen('status'), 'on')
            read.assert_not_called()

    def test_current_driver_refused_before_any_setting_changes(self):
        args = argparse.Namespace(mode='host', adb_serial=None)
        with patch.object(p.os, 'geteuid', return_value=0), \
             patch.object(p, 'read', return_value='[auto] inhibit-charge'), \
             patch.object(p, 'write') as write, patch.object(p, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'lacks force-discharge'):
                p.preflight(args)
            write.assert_not_called()
            run.assert_not_called()

    def test_inhibited_charging_is_not_valid_discharge_while_usb_supplies_host(self):
        values = {p.B / 'capacity': '60', p.B / 'temp': '310', p.B / 'status': 'Not charging',
                  p.B / 'current_now': '-10000', p.U / 'online': '1'}
        with patch.object(p, 'read', side_effect=values.__getitem__), patch.object(p, 'vm_pids', return_value=[]):
            with self.assertRaisesRegex(RuntimeError, 'USB still powers'):
                p.guard([])

    def test_vm_start_invalidates_host_measurement(self):
        values = {p.B / 'capacity': '60', p.B / 'temp': '310'}
        with patch.object(p, 'read', side_effect=values.__getitem__), patch.object(p, 'vm_pids', return_value=[345]):
            with self.assertRaisesRegex(RuntimeError, 'Running VMs changed'):
                p.guard([])

    def test_guest_failure_still_restores_charging_cpu_display_and_sleep_daemon(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            battery, usb, cpu = (output / n for n in ('battery', 'usb', 'cpu'))
            policy = cpu / 'policy0'
            battery.mkdir(); usb.mkdir(); policy.mkdir(parents=True)
            (battery / 'charge_behaviour').write_text('auto inhibit-charge [force-discharge]')
            (usb / 'online').write_text('0'); (usb / 'present').write_text('1')
            for key, value in {'cpuinfo_max_freq': '1804800', 'scaling_min_freq': '300000',
                               'scaling_max_freq': '1804800', 'scaling_governor': 'schedutil'}.items():
                (policy / key).write_text(value)
            state = {'boot_id': 'same-boot', 'charge_behaviour': 'inhibit-charge', 'usb_online': '1',
                     'screen': 'on', 'sleepd_active': True,
                     'cpu': {'policy0': {'scaling_min_freq': '300000', 'scaling_max_freq': '300000',
                                          'scaling_governor': 'powersave'}},
                     'guest': {'serial': 'vm-transport', 'enabled': {'deep': True, 'light': False},
                               'wakefulness': 'Awake'}}
            p.save(output, 'original.json', state)
            original_read, original_write = p.read, p.write
            writes = []

            def read(path):
                if str(path) == '/proc/sys/kernel/random/boot_id':
                    return 'same-boot'
                return original_read(path)

            def write(path, value):
                writes.append((path, value))
                if path == battery / 'charge_behaviour':
                    original_write(path, 'auto [inhibit-charge] force-discharge')
                    original_write(usb / 'online', '1')
                else:
                    original_write(path, value)

            with patch.object(p, 'B', battery), patch.object(p, 'U', usb), patch.object(p, 'CPU', cpu), \
                 patch.object(p, 'read', side_effect=read), patch.object(p, 'write', side_effect=write), \
                 patch.object(p, 'adb', side_effect=RuntimeError('ADB lost')), \
                 patch.object(p, 'screen') as screen, patch.object(p, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'Restoration incomplete'):
                    p.restore(output)
                self.assertEqual(writes[0], (battery / 'charge_behaviour', 'inhibit-charge'))
                self.assertEqual(original_read(policy / 'scaling_max_freq'), '300000')
                self.assertEqual(original_read(policy / 'scaling_governor'), 'powersave')
                screen.assert_called_once_with('on')
                run.assert_called_once_with('systemctl', 'start', 'mothershipd')
                self.assertTrue(json.loads((output / 'restoration.json').read_text())['errors'])

    def test_restore_refuses_previous_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            p.save(output, 'original.json', {'boot_id': 'old-boot'})
            with patch.object(p, 'read', return_value='new-boot'), patch.object(p, 'write') as write:
                with self.assertRaisesRegex(RuntimeError, 'different boot'):
                    p.restore(output)
                write.assert_not_called()

    def test_restore_without_snapshot_is_noop_for_failed_preflight(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(p, 'write') as write:
            p.restore(Path(tmp))
            write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
