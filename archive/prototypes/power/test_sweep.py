"""Report/queue checks without a phone, including incomplete-measurement handling."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('sweep', Path(__file__).with_name('sweep.py'))
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


class SweepTest(unittest.TestCase):
    def test_plan_is_complete_and_all_scripts_request_30_minutes(self):
        manifest = json.loads((s.HERE / 'sweep.json').read_text())
        ids = [v['id'] for v in manifest['phases']]
        self.assertEqual(len(ids), len(set(ids)))
        for phase in manifest['phases']:
            if not phase.get('adopt'):
                text = (s.HERE / 'cases' / (phase['id'] + '.sh')).read_text()
                self.assertIn('--seconds 1800', text)
                self.assertIn('--settle 300', text)
        for c in manifest['comparisons']:
            self.assertTrue(set(c['reference_ids'] + [c['option_id']]) <= set(ids))

    def test_reports_pending_until_both_control_and_option_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'docs').mkdir()
            with patch.object(s, 'REPO', root):
                q = s.Queue(root / 'reports')
                q.report()
                self.assertEqual(json.loads((q.output / 'comparisons.json').read_text()), [])
                self.assertNotIn('| Measured |', (root / 'motorola_nio/docs/standby-measurements.md').read_text())

    def test_power_saving_and_temperature_caution_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'docs').mkdir()
            with patch.object(s, 'REPO', root):
                q = s.Queue(root / 'reports')
                base = {'seconds': 1800, 'samples': 600, 'mean_mA': 250, 'mean_mW': 1000, 'mean_temperature_C': 30}
                q.state['completed'] = {'s02-screen-on': base,
                                         's02-screen-off': dict(base, mean_mW=700, mean_temperature_C=33)}
                q.report()
                result = json.loads((q.output / 'comparisons.json').read_text())[0]
                self.assertEqual(result['saving_mW'], 300)
                self.assertEqual(result['saving_percent'], 30)
                self.assertIn('caution', result)
                text = (root / 'motorola_nio/docs/standby-measurements.md').read_text()
                self.assertIn('+300.0 (+30.0%)', text)
                self.assertIn('temperature drift', text)

    def test_full_repo_disk_does_not_abort_ram_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'docs').mkdir()
            original = Path.write_text
            def write(path, text, *args, **kwargs):
                if path.parent == root / 'docs':
                    raise OSError(28, 'No space left on device')
                return original(path, text, *args, **kwargs)
            with patch.object(s, 'REPO', root):
                q = s.Queue(root / 'ram-results')
                with patch.object(Path, 'write_text', write):
                    q.update('measuring')
                self.assertEqual(json.loads((q.output / 'status.json').read_text())['state'], 'measuring')
                self.assertTrue((q.output / 'results.md').exists())

    def test_results_archive_runs_after_condition_without_deleting_remote_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = s.Queue(Path(tmp), archive_target='nas:/results')
            with patch.object(s, 'command') as command:
                q.sync_archive()
                args = command.call_args.args[0]
                self.assertEqual(args[-1], 'nas:/results/')
                self.assertNotIn('--delete', args)

    def test_failed_option_is_not_reported_as_zero_saving(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'docs').mkdir()
            with patch.object(s, 'REPO', root):
                q = s.Queue(root / 'reports')
                q.state['failed']['s02-screen-off'] = 'temperature guard stopped test'
                q.report()
                self.assertEqual(json.loads((q.output / 'comparisons.json').read_text()), [])
                self.assertIn('| Incomplete |', (root / 'motorola_nio/docs/standby-measurements.md').read_text())


if __name__ == '__main__':
    unittest.main()
