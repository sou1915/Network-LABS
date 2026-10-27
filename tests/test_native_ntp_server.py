import copy
import io
import json
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout
from contextlib import redirect_stderr

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
    def test_isolated_reference_scenario_and_cli(self):
        from network_labs.appliances.examples import ntp_lab
        from network_labs.appliances.__main__ import main
        spec = ntp_lab('/rootfs'); source = spec['nodes'][3]; relay = spec['nodes'][2]
        self.assertEqual(spec['name'], 'ntp-lan')
        self.assertIn('local stratum 10\n', config_text(source))
        self.assertNotIn('server ', config_text(source))
        self.assertIn('server 192.0.2.30 iburst\n', config_text(relay))
        self.assertEqual(source['ntp_server']['clients'], ['192.0.2.20'])
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example', '--ntp', '--rootfs', '/rootfs']), 0)
        self.assertEqual(json.loads(output.getvalue())['name'], 'ntp-lan')
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(['example', '--ntp', '--syslog', '--rootfs', '/rootfs']), 1)

    def test_local_source_must_be_explicit_and_cannot_mix_with_upstream(self):
        from network_labs.appliances.examples import ntp_lab
        for change in ({'local_stratum': 1}, {'local_stratum': 15}, {'local_stratum': True},
                       {'upstream': '192.0.2.10'}):
            spec = ntp_lab('/rootfs'); spec['nodes'][3]['ntp_server'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): validate(spec)

    @unittest.skipUnless(shutil.which('chronyd'), 'chronyd binary not installed')
    def test_installed_chronyd_accepts_generated_config(self):
        from network_labs.appliances.examples import ntp_lab
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'chrony.conf'
            for node in (ntp_spec()['nodes'][2], ntp_lab('/rootfs')['nodes'][3]):
                path.write_text(config_text(node))
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
