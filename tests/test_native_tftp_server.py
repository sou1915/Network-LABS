import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

from network_labs.appliances.examples import tftp_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.tftp_server import config_text, prepare_files, start_servers, drift
from network_labs.appliances.__main__ import main


class TftpServerTests(unittest.TestCase):
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
