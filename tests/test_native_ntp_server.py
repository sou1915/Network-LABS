import copy
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.spec import example, validate
from network_labs.appliances.runtime import oci_config, RuntimeFailure
from network_labs.appliances.ntp_server import command, config_text, prepare_files, start_servers, drift


def ntp_spec():
    spec = example('/rootfs')
    switch = spec['nodes'][1]; switch['interfaces']['eth2'] = ''
    spec['nodes'].append({'name': 'PC3', 'runtime': 'oci', 'rootfs': '/rootfs', 'interfaces': {'eth0': '192.0.2.30/24'}})
    spec['links'].append([['SW1', 'eth2'], ['PC3', 'eth0']])
    spec['nodes'][2]['ntp_server'] = {'interface': 'eth0', 'upstream': '192.0.2.30', 'clients': ['192.0.2.10']}
    return validate(spec)


class NtpServerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('chronyd'), 'chronyd binary not installed')
    def test_installed_chronyd_accepts_generated_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'chrony.conf'; path.write_text(config_text(ntp_spec()['nodes'][2]))
            result = subprocess.run([shutil.which('chronyd'), '-p', '-f', str(path)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_valid_profile_is_bounded_and_cannot_adjust_host_time(self):
        spec = ntp_spec(); node = spec['nodes'][2]; text = config_text(node)
        self.assertIn('server 192.0.2.30 iburst\n', text)
        self.assertIn('allow 192.0.2.10/32\n', text)
        self.assertIn('bindaddress 192.0.2.20', text); self.assertIn('cmdport 0', text)
        self.assertNotIn('local stratum', text); self.assertNotIn('makestep', text)
        self.assertIn('-x', command()); self.assertNotIn('-q', command())
        caps = oci_config(spec, node, 2, Path('/rootfs'))['process']['capabilities']
        self.assertTrue(all('CAP_SYS_TIME' not in values for values in caps.values()))

    def test_rejects_nonmanaged_peers_and_invalid_policy(self):
        for update in ({'upstream': '192.0.2.99'}, {'clients': []}, {'clients': ['192.0.2.20']},
                       {'clients': ['192.0.2.30']}, {'upstream': '127.0.0.1'}, {'interface': 'missing'}):
            spec = ntp_spec(); spec['nodes'][2]['ntp_server'].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError): validate(spec)

    def test_file_preparation_validation_before_daemon_and_drift(self):
        spec = ntp_spec(); node = spec['nodes'][2]
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'files').mkdir(); prepare_files(folder, node)
            self.assertEqual((Path(folder) / 'files/ntp-server.conf').read_text(), config_text(node))
        manager = Mock(); manager.state = {'spec': spec}; manager.directory = Path('/tmp')
        manager.crun.return_value = Mock(returncode=1, stdout='', stderr='invalid config')
        with self.assertRaises(RuntimeFailure): start_servers(manager)
        self.assertEqual(manager.crun.call_count, 1)
        with patch('network_labs.appliances.ntp_server.observe_config', return_value={'configuration_verified': False}):
            self.assertTrue(drift(manager, node))
