"""Real-interface selection, DisMan configuration and source-policy boundaries."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from network_labs.appliances.examples import snmp_links_lab, snmp_lab
from network_labs.appliances.snmp import usm_credentials, config_text as agent_text, command
from network_labs.appliances.snmp_links import config_text, source_text, prepare, check_restart, observe, install_source_filter, INTERNAL, FILTER
from network_labs.appliances.runtime import RuntimeFailure
from network_labs.appliances.spec import validate


class LinkEventTests(unittest.TestCase):
    def spec(self, mode='trap'):
        return snmp_links_lab('/rootfs', usm_credentials('monitor', 'link-auth-password', 'link-privacy-password'), mode)

    def test_reference_modes_and_selected_physical_interface_are_bounded(self):
        for mode in ('trap', 'inform'):
            spec = self.spec(mode); self.assertEqual(validate(copy.deepcopy(spec)), spec)
            self.assertEqual(spec['nodes'][2]['snmp_agent']['link_events']['interfaces'], ['eth1'])
        for change in ({'interfaces': []}, {'interfaces': ['eth0']}, {'interfaces': ['vlan10']}, {'interfaces': ['eth1', 'eth1']},
                       {'interval': True}, {'interval': 1}, {'interval': 61}, {'unknown': True}):
            spec = self.spec(); spec['nodes'][2]['snmp_agent']['link_events'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): validate(spec)
        spec = snmp_lab('/rootfs'); spec['nodes'][2]['snmp_agent']['link_events'] = {'interfaces': ['eth1'], 'interval': 2}
        with self.assertRaises(ValueError): validate(spec)

    def test_numeric_instances_initial_baseline_and_internal_principal_do_not_weaken_polling(self):
        node = self.spec()['nodes'][2]; text = config_text(node, {'eth1': 7})
        self.assertIn('monitor -I -S -r 2', text)
        for column in ('1', '7', '8'): self.assertIn('.1.3.6.1.2.1.2.2.1.' + column + '.7', text)
        self.assertIn('createUser ' + INTERNAL + '\n', text)
        self.assertIn('usm auth exact NetworkLabsLinks none none', text)
        self.assertNotIn('defaultMonitors', text); self.assertNotIn('linkUpDownNotifications', text)
        rendered = agent_text(node); self.assertNotIn('sourceFilterType', rendered)
        self.assertIn('usm priv exact NetworkLabsView none none', rendered)
        guard = source_text(node); self.assertIn('ip daddr 192.0.2.20 udp dport 161 ip saddr != { 192.0.2.10 } drop', guard)
        self.assertIn('mteTriggerConf', command(node, 'a' * 24)[-2])
        with self.assertRaises(RuntimeFailure): config_text(node, {})

    def test_missing_or_replaced_interface_bindings_never_become_success(self):
        node = self.spec()['nodes'][2]; manager = Mock(); manager.state = {'spec': self.spec()}; manager.read.return_value = manager.state
        self.assertFalse(observe(manager, node)['configuration_verified'])
        manager.state['snmp_link_indices'] = {'R1': {'eth1': 7}}; manager.state['snmp_link_filters'] = {'R1': 'expected'}
        with patch('network_labs.appliances.snmp_links.observe_config', return_value={'configuration_verified': True}), \
             patch('network_labs.appliances.snmp_links.indices', return_value={'eth1': 9}), \
             patch('network_labs.appliances.snmp_links.filter_fingerprint', return_value='expected'):
            self.assertFalse(observe(manager, node)['configuration_verified'])

    def test_missing_native_modules_fail_without_synthesizing_events(self):
        manager = Mock(); manager.state = {'spec': self.spec()}; manager.crun.return_value = Mock(stdout='', stderr='', returncode=0)
        with self.assertRaisesRegex(RuntimeFailure, 'modules'): prepare(manager, manager.state['spec']['nodes'][2])
        manager.ns.assert_not_called()

    def test_runtime_file_is_private_and_observed_indices_are_not_startup_declarations(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Mock(); manager.directory = Path(folder); manager.state = {'spec': self.spec(), 'phase': 'starting'}
            node = manager.state['spec']['nodes'][2]; (manager.directory / 'R1/files').mkdir(parents=True)
            manager.crun.return_value = Mock(stdout='iquerySecName x\niquerySecLevel x\nmonitor x\nnotificationEvent x\n', stderr='', returncode=0)
            before = copy.deepcopy(manager.state['spec'])
            with patch('network_labs.appliances.snmp_links.indices', return_value={'eth1': 7}), \
                 patch('network_labs.appliances.snmp_links.install_source_filter'):
                prepare(manager, node)
            path = manager.directory / 'R1/files/snmp-link-events.conf'
            self.assertEqual(path.stat().st_mode & 0o777, 0o600); self.assertEqual(path.read_text(), config_text(node, {'eth1': 7}))
            self.assertEqual(manager.state['spec'], before)
            self.assertEqual(manager.state['snmp_link_indices']['R1'], {'eth1': 7})

    def test_drift_is_refused_before_restart_can_rotate_trap_identity(self):
        manager = Mock(); manager.state = {'spec': self.spec(), 'phase': 'running', 'snmp_link_indices': {'R1': {'eth1': 7}}}
        before = copy.deepcopy(manager.state)
        with patch('network_labs.appliances.snmp_links.observe', return_value={'configuration_verified': False}):
            with self.assertRaises(RuntimeFailure): check_restart(manager, manager.state['spec']['nodes'][2])
        self.assertEqual(manager.state, before)

    def test_failed_config_publication_does_not_record_binding_and_can_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Mock(); manager.directory = Path(folder); manager.state = {'spec': self.spec(), 'phase': 'starting'}
            node = manager.state['spec']['nodes'][2]; files = manager.directory / 'R1/files'; files.mkdir(parents=True)
            manager.crun.return_value = Mock(stdout='iquerySecName x\niquerySecLevel x\nmonitor x\nnotificationEvent x\n', stderr='', returncode=0)
            with patch('network_labs.appliances.snmp_links.indices', return_value={'eth1': 7}), \
                 patch('network_labs.appliances.snmp_links.install_source_filter'):
                with patch('network_labs.appliances.snmp_links.os.replace', side_effect=OSError('disk error')):
                    with self.assertRaises(OSError): prepare(manager, node)
                self.assertNotIn('snmp_link_indices', manager.state)
                self.assertEqual(list(files.iterdir()), [])
                prepare(manager, node)
            self.assertEqual(manager.state['snmp_link_indices']['R1'], {'eth1': 7})
            self.assertEqual((files / 'snmp-link-events.conf').read_text(), config_text(node, {'eth1': 7}))

    def test_source_table_collision_is_not_adopted(self):
        manager = Mock(); manager.state = {'spec': self.spec()}; manager.ns.return_value.stdout = json.dumps({'nftables': [{'table': {'family': 'inet', 'name': FILTER}}]})
        with self.assertRaisesRegex(RuntimeFailure, 'adopt'): install_source_filter(manager, manager.state['spec']['nodes'][2])
        self.assertFalse(any('-f' in c.args for c in manager.ns.call_args_list))

    def test_cli_modes_require_complete_credentials_and_cannot_mix_references(self):
        from network_labs.appliances.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'auth').write_text('link-auth-password'); (root / 'privacy').write_text('link-privacy-password')
            args = ['example', '--rootfs', '/rootfs', '--snmp-link-events', '--snmp-user', 'monitor',
                    '--snmp-auth-passphrase-file', str(root / 'auth'), '--snmp-privacy-passphrase-file', str(root / 'privacy')]
            for mode in ('trap', 'inform'):
                output = io.StringIO()
                with contextlib.redirect_stdout(output): self.assertEqual(main(args + ['--snmp-link-mode', mode]), 0)
                self.assertEqual(json.loads(output.getvalue())['name'], 'snmp-link-events')
            for bad in (args + ['--snmpv3'], ['example', '--rootfs', '/rootfs', '--snmp-link-events'],
                        ['example', '--rootfs', '/rootfs', '--snmp-link-mode', 'inform']):
                with contextlib.redirect_stderr(io.StringIO()): self.assertEqual(main(bad), 1)
