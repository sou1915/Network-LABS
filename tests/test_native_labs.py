import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from unittest.mock import patch

from network_labs.appliances import runtime
from network_labs.appliances.labs import list_labs, render
from network_labs.appliances.spec import example
from network_labs.appliances.runtime import RuntimeFailure


@contextmanager
def state_owner(root, uid=0, mode=None):
    """Model root-owned state even when the tests run as an ordinary user."""
    original_stat = Path.stat
    def observed_stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == root:
            fields = list(result); fields[4] = uid
            if mode is not None: fields[0] = mode
            return os.stat_result(fields)
        return result
    with patch.object(Path, 'stat', observed_stat), patch('os.geteuid', return_value=0):
        yield


class LabsTests(unittest.TestCase):
    def test_inventory_distinguishes_recorded_state_and_incomplete_lab(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runtime, 'STATE_ROOT', Path(folder)):
            root = Path(folder); (root / 'micro-lan').mkdir(); (root / 'broken').mkdir()
            (root / 'micro-lan/state.json').write_text(json.dumps({'phase': 'running', 'spec': example('/rootfs')}))
            (root / 'broken/state.json').write_text('{')
            (root / 'alias').symlink_to(root / 'micro-lan', target_is_directory=True)
            with state_owner(root): report = list_labs()
            self.assertEqual([row['name'] for row in report['labs']], ['broken', 'micro-lan'])
            self.assertEqual(report['labs'][0]['phase'], 'unknown'); self.assertTrue(report['labs'][0]['error'])
            self.assertEqual(report['labs'][1]['phase'], 'running')
            self.assertEqual([n['name'] for n in report['labs'][1]['nodes']], ['PC1', 'SW1', 'PC2'])
            self.assertIn('pas une vérification', render(report))

    def test_insecure_state_ownership_or_permissions_are_still_refused(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runtime, 'STATE_ROOT', Path(folder)):
            root = Path(folder)
            for uid, mode in ((1000, None), (0, 0o40777)):
                with state_owner(root, uid=uid, mode=mode), self.assertRaises(RuntimeFailure):
                    list_labs()

    def test_missing_root_is_empty_and_non_root_is_refused(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runtime, 'STATE_ROOT', Path(folder) / 'absent'):
            with patch('os.geteuid', return_value=0): self.assertEqual(list_labs()['labs'], [])
            with patch('os.geteuid', return_value=1000), self.assertRaises(RuntimeFailure): list_labs()
            self.assertFalse(runtime.STATE_ROOT.exists())

    def test_cli_json_does_not_require_lab_name(self):
        from network_labs.appliances.__main__ import main
        report = {'labs': [], 'scope': 'recorded'}
        with patch('network_labs.appliances.labs.list_labs', return_value=report), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['labs', '--json']), 0)
        self.assertEqual(json.loads(output.getvalue()), report)
