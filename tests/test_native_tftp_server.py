import copy
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

from network_labs.appliances.examples import tftp_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.tftp_server import config_text, prepare_files, start_servers, drift, observe_file
from network_labs.appliances.__main__ import main


class TftpServerTests(unittest.TestCase):
    def test_binary_payloads_are_exact_and_bounded(self):
        spec = tftp_lab('/rootfs'); node = spec['nodes'][2]
        payload = bytes(range(256)) * 256
        node['tftp_server']['files']['image.bin'] = {'base64': base64.b64encode(payload).decode('ascii')}
        spec = validate(spec); node = spec['nodes'][2]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'files').mkdir(); prepare_files(root, node)
            self.assertEqual((root / 'files/tftp/image.bin').read_bytes(), payload)
            self.assertEqual((root / 'files/tftp/sample.txt').read_bytes(), b'Network LABS TFTP\n')
        for value in ({'base64': '???'}, {'base64': 'YQ'}, {'base64': 'YR=='}, {'base64': 'YQ==', 'extra': 1},
                      {'base64': base64.b64encode(payload + b'x').decode('ascii')}):
            candidate = tftp_lab('/rootfs'); candidate['nodes'][2]['tftp_server']['files']['image.bin'] = value
            with self.subTest(value=str(value)[:30]), self.assertRaises(ValueError): validate(candidate)

    def test_binary_file_observation_compares_digest_without_exposing_contents(self):
        spec = tftp_lab('/rootfs'); node = spec['nodes'][2]; manager = Mock()
        payload = b'\x00\xffprivate-content'; digest = hashlib.sha256(payload).hexdigest()
        manager.crun.return_value = Mock(returncode=0, stdout=digest + '  /lab/tftp/image.bin\n')
        report = observe_file(manager, node, 'image.bin', payload)
        self.assertTrue(report['configuration_verified']); self.assertTrue(report['configuration_available'])
        self.assertNotIn('private-content', str(report))
        manager.crun.assert_called_once_with('exec', 'PC2', '/bin/busybox', 'sha256sum', '/lab/tftp/image.bin', check=False, timeout=3)
        manager.crun.return_value.stdout = '0' * 64 + '  /lab/tftp/image.bin\n'
        report = observe_file(manager, node, 'image.bin', payload)
        self.assertFalse(report['configuration_verified']); self.assertTrue(report['configuration_available'])
        manager.crun.return_value.stdout = 'invalid'
        report = observe_file(manager, node, 'image.bin', payload)
        self.assertFalse(report['configuration_available']); self.assertFalse(report['configuration_verified'])
        manager.crun.return_value.returncode = 1
        self.assertFalse(observe_file(manager, node, 'image.bin', payload)['configuration_available'])

    def test_reference_lab_and_cli(self):
        spec = tftp_lab('/rootfs'); node = spec['nodes'][2]
        self.assertEqual(spec['name'], 'tftp-lan'); self.assertEqual(node['tftp_server']['files']['sample.txt'], 'Network LABS TFTP\n')
        text = config_text(node)
        for line in ('port=0', 'interface=eth0', 'enable-tftp=eth0', 'tftp-root=/lab/tftp', 'tftp-secure', 'tftp-max=4'):
            self.assertIn(line + '\n', text)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example', '--tftp', '--rootfs', '/rootfs']), 0)
        self.assertEqual(json.loads(output.getvalue())['name'], 'tftp-lan')
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(['example', '--tftp', '--ntp', '--rootfs', '/rootfs']), 1)

    def test_policy_rejects_unsafe_names_large_files_and_service_collisions(self):
        for files in ({}, {'../secret': 'x'}, {'a/b': 'x'}, {'.': 'x'}, {'file': 'x' * 4097}, {'file': 42}):
            spec = tftp_lab('/rootfs'); spec['nodes'][2]['tftp_server']['files'] = files
            with self.subTest(files=repr(files)[:40]), self.assertRaises(ValueError): validate(spec)
        spec = tftp_lab('/rootfs'); spec['nodes'][2]['startup'] = [['/bin/true']]
        with self.assertRaises(ValueError): validate(spec)
        spec = tftp_lab('/rootfs'); spec['nodes'][2]['dns_server'] = {'interface': 'eth0', 'zone': 'lab.test', 'records': {'a.lab.test': '192.0.2.20'}}
        with self.assertRaises(ValueError): validate(spec)

    def test_files_and_service_start_with_explicit_read_only_scope(self):
        spec = tftp_lab('/rootfs'); node = spec['nodes'][2]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'files').mkdir()
            prepare_files(root, node)
            self.assertEqual((root / 'files/tftp/sample.txt').read_text(), 'Network LABS TFTP\n')
            self.assertEqual((root / 'files/tftp/sample.txt').stat().st_mode & 0o777, 0o644)
            self.assertEqual((root / 'files/tftp-server.conf').read_text(), config_text(node))
        manager = Mock(); manager.state = {'spec': spec}; manager.directory = Path('/tmp')
        before = copy.deepcopy(spec); start_servers(manager)
        self.assertEqual(manager.crun.call_count, 2)
        self.assertIn('--test', manager.crun.call_args_list[0].args)
        self.assertIn('--keep-in-foreground', manager.crun.call_args_list[1].args)
        self.assertEqual(spec, before)
        with patch('network_labs.appliances.tftp_server.observe', return_value={'configuration_verified': False}):
            self.assertTrue(drift(manager, node))
