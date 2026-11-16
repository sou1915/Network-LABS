"""Persistent TCP sender policy, bounded volatile queues and lifecycle contracts."""
import copy
from unittest.mock import Mock, patch
import unittest
from network_labs.appliances.examples import syslog_tcp_lab, management_lab
from network_labs.appliances.management import commands, managed_files, start_service, drift
from network_labs.appliances.spec import validate
from network_labs.appliances.syslog_forward import files, REQUIRED_MODULES, command
from network_labs.appliances.syslog_server import rootfs_assets
from network_labs.appliances.runtime import RuntimeFailure
from network_labs.appliances.service_adapters import adapters


class SyslogForwardTests(unittest.TestCase):
    def test_example_and_legacy_sender_have_distinct_actual_daemons(self):
        spec = syslog_tcp_lab('/rootfs', forward=True); self.assertEqual(validate(copy.deepcopy(spec)), spec)
        node = spec['nodes'][2]
        self.assertEqual(commands(node)['syslog'], command())
        self.assertEqual(commands(management_lab('/rootfs')['nodes'][2])['syslog'][:2], ['/bin/busybox', 'syslogd'])
        config = files(node)['syslog-forward.conf']
        for token in ('queue.type="FixedArray" queue.size="256"', 'queue.timeoutEnqueue="0"', 'queue.saveOnShutdown="off"',
                      'TCP_Framing="octet-counted"', 'protocol="tcp"', 'action.resumeRetryCount="-1"', 'SysSock.Use="off"',
                      'Socket="/dev/log"', 'file="/run/messages"'):
            self.assertIn(token, config)
        self.assertNotIn('queue.filename', config); self.assertNotIn('imklog', config); self.assertNotIn('imudp', config)
        self.assertIn('syslog-forward.conf', managed_files(node))

    def test_incompatible_targets_transports_and_shared_roles_fail_before_start(self):
        edits = [lambda s: s['nodes'][2]['management'].update(syslog_transport='tls'),
                 lambda s: s['nodes'][2]['management'].update(syslog_remote=''),
                 lambda s: s['nodes'][0]['syslog_server'].update(transport='udp'),
                 lambda s: s['nodes'][2].update(role='router'),
                 lambda s: s['nodes'][2]['interfaces'].update(eth1=''),
                 lambda s: s['nodes'][2].update(syslog_server={'interface':'eth0','senders':['192.0.2.10']})]
        for edit in edits:
            spec = syslog_tcp_lab('/rootfs', forward=True); edit(spec)
            with self.subTest(edit=edit), self.assertRaises(ValueError): validate(spec)
        node = syslog_tcp_lab('/rootfs', forward=True)['nodes'][2]; old = copy.deepcopy(node)
        node['management']['syslog_transport'] = 'udp'
        with self.assertRaises(ValueError): adapters(node, old)

    def test_assets_and_configuration_rejection_cannot_launch_sender(self):
        with patch('network_labs.appliances.dns_rootfs.assets', return_value=[]), patch('network_labs.appliances.dns_rootfs.shared_library_assets', return_value=[]) as module:
            rootfs_assets('/trusted/rsyslogd', '/trusted/modules', forward=True)
            self.assertTrue(set(REQUIRED_MODULES).issubset({c.args[0].name for c in module.call_args_list}))
        node = syslog_tcp_lab('/rootfs', forward=True)['nodes'][2]; manager = Mock()
        manager.crun.return_value.returncode=1; manager.crun.return_value.stdout=''; manager.crun.return_value.stderr='bad config'
        with self.assertRaisesRegex(RuntimeFailure, 'forwarding configuration rejected'): start_service(manager, node, 'syslog')
        self.assertFalse(any('--detach' in c.args for c in manager.crun.call_args_list))
        with patch('network_labs.appliances.management.observe_config', return_value={'configuration_verified':False}): self.assertTrue(drift(manager, node))
