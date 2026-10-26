"""Collector policy, offline module assets and declarative persistence boundaries."""
import copy
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch
from network_labs.appliances.examples import syslog_lab, dual_stack_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.syslog_server import files, drift, command, start_server, rootfs_assets
from network_labs.appliances.service_adapters import adapters
from network_labs.appliances.dns_rootfs import shared_library_assets
from network_labs.appliances.runtime import RuntimeFailure


class SyslogServerTests(unittest.TestCase):
    def test_example_normalizes_and_receiver_policy_cannot_be_empty_or_injected(self):
        spec = syslog_lab('/rootfs')
        self.assertEqual(validate(copy.deepcopy(spec)), spec)
        for values in ([], ['*'], ['224.0.0.1'], ['127.0.0.1'], ['192.0.2.10'], ['192.0.2.99'], [3], ['192.0.2.20'] * 65):
            candidate = copy.deepcopy(spec); candidate['nodes'][0]['syslog_server']['senders'] = values
            with self.subTest(values=values), self.assertRaises(ValueError): validate(candidate)
        spec['nodes'][0]['syslog_server']['senders'] *= 2
        self.assertEqual(validate(spec)['nodes'][0]['syslog_server']['senders'], ['192.0.2.20'])

    def test_interface_startup_unknown_fields_and_ipv6_compositions_are_refused(self):
        for changes in ({'interface': 'eth9'}, {'interface': None}, {'unexpected': True}):
            spec = syslog_lab('/rootfs'); spec['nodes'][0]['syslog_server'].update(changes)
            with self.assertRaises(ValueError): validate(spec)
        for field, value in [('shutdown', ['eth0']), ('startup', [['/bin/echo', 'unmanaged']])]:
            spec = syslog_lab('/rootfs'); spec['nodes'][0][field] = value
            with self.assertRaises(ValueError): validate(spec)
        spec = dual_stack_lab('/rootfs'); spec['nodes'][0]['syslog_server'] = {'interface': 'eth0', 'senders': ['198.51.100.20']}
        with self.assertRaises(ValueError): validate(spec)
        old = syslog_lab('/rootfs')['nodes'][0]; new = copy.deepcopy(old); new['interfaces']['eth0'] = '192.0.2.11/24'
        with self.assertRaises(ValueError): adapters(new, old)

    def test_config_binds_only_declared_address_filters_and_rotates_volatile_logs(self):
        values = files(syslog_lab('/rootfs')['nodes'][0]); config = values['syslog-server.conf']
        self.assertIn('address="192.0.2.10" port="514" ipFreeBind="0"', config)
        self.assertIn('if not ($fromhost-ip == "192.0.2.20") then stop', config)
        self.assertIn('rotation.sizeLimit="65536"', config)
        self.assertIn('rotation.sizeLimitCommand="/bin/sh /lab/rotate-syslog.sh"', config)
        self.assertIn('/bin/busybox mv -f /run/remote-syslog.log /run/remote-syslog.log.1', values['rotate-syslog.sh'])
        self.assertNotIn('imuxsock', config); self.assertNotIn('imklog', config)
        self.assertEqual(command()[0], '/usr/lib/network-labs/rsyslogd')
        self.assertEqual(command()[-2:], ['-f', '/lab/syslog-server.conf'])

    def test_file_audit_is_not_delivery_or_daemon_liveness(self):
        node = syslog_lab('/rootfs')['nodes'][0]
        with patch('network_labs.appliances.syslog_server.observe_config', return_value={'configuration_verified': True}):
            self.assertEqual(drift(Mock(), node), [])
        with patch('network_labs.appliances.syslog_server.observe_config', return_value={'configuration_verified': False}):
            self.assertTrue(drift(Mock(), node))
        manager = Mock(); manager.crun.return_value.returncode = 1
        manager.crun.return_value.stdout = ''; manager.crun.return_value.stderr = 'bad config'
        with self.assertRaises(RuntimeFailure): start_server(manager, node)
        self.assertFalse(any('--detach' in c.args for c in manager.crun.call_args_list))

    def test_rootfs_copies_explicit_required_modules_and_uses_real_version_probe(self):
        with patch('network_labs.appliances.dns_rootfs.assets', return_value=[]) as binary, \
             patch('network_labs.appliances.dns_rootfs.shared_library_assets', return_value=[]) as module:
            rootfs_assets('/trusted/rsyslogd', '/trusted/modules')
            self.assertEqual(binary.call_args.kwargs['version_args'], ('-v',))
            self.assertEqual([c.args[0].name for c in module.call_args_list], ['imudp.so', 'lmnet.so'])

    def test_dynamic_module_dependencies_are_copied_even_without_elf_interpreter(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'module.so'; raw = bytearray(64); raw[:6] = b'\x7fELF\x02\x01'
            struct.pack_into('<H', raw, 16, 3); path.write_bytes(raw)
            library = Path(folder) / 'librequired.so'; library.write_bytes(b'fixture')
            result = Mock(returncode=0, stdout=' librequired.so => ' + str(library) + ' (0x123)\n')
            with patch('network_labs.appliances.dns_rootfs.subprocess.run', return_value=result):
                self.assertIn((library.resolve(), library), shared_library_assets(path, '/usr/lib/module.so'))
            result.stdout = ' librequired.so => not found\n'
            with patch('network_labs.appliances.dns_rootfs.subprocess.run', return_value=result), self.assertRaises(ValueError):
                shared_library_assets(path, '/usr/lib/module.so')
            path.write_bytes(b'not an ELF')
            with self.assertRaises(ValueError): shared_library_assets(path, '/usr/lib/module.so')
