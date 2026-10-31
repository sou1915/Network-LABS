"""Verify strict policy or prove clean refusal; never equate refusal with failover."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from network_labs.appliances.examples import stp_lacp_lab
from network_labs.appliances.runtime import Manager, RuntimeFailure, run, static_busybox_rootfs
from test_native_stp_lacp_carrier_integration import STPLACPPathScenario
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1', 'Opt-in privileged native test')
class NativeStrictLACPTests(STPLACPPathScenario, unittest.TestCase):
    def test_strict_policy_verified_or_cleanly_refused(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/sys/module/bonding').exists())
        for tool in ('busybox', 'crun', 'ip', 'bridge', 'tcpdump', 'tc'):
            self.assertIsNotNone(shutil.which(tool), tool)
        namespaces = run(['ip', 'netns', 'list']).stdout
        before = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        with tempfile.TemporaryDirectory() as folder:
            rootfs = static_busybox_rootfs(shutil.which('busybox'), Path(folder) / 'rootfs')
            spec = stp_lacp_lab(rootfs, 1, True); spec['name'] = 'strict-gate-' + str(os.getpid())
            manager = Manager(spec['name']); supported = False
            try:
                try:
                    with manager.locked(): manager.start(spec)
                except RuntimeFailure as error:
                    self.assertRegex(str(error), r'Explicit lacp_strict (requires|rejected|was not verified)')
                    print('STRICT_UNSUPPORTED: ' + str(error), flush=True)
                    self.assertFalse(manager.directory.exists(), 'Rejected policy leaked runtime state')
                else:
                    for name in ('SW1', 'SW2'):
                        actual = manager.inspect(name)['port_channels']['bond1']
                        self.assertIs(actual['lacp_strict'], True, actual)
                        self.assertIs(actual['lacp_strict_requested'], True, actual)
                    supported = True
            finally:
                if manager.directory.exists():
                    with manager.locked(): manager.stop()
        self.assertEqual(run(['ip', 'netns', 'list']).stdout, namespaces)
        after = {(r['ifname'], r['ifindex']) for r in json.loads(run(['ip', '-j', 'link', 'show']).stdout)}
        hardware = {n for n, _ in after - before if (Path('/sys/class/net') / n / 'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before, after, hardware), {'removed_or_replaced': set(), 'added_virtual': set()})
        if not supported:
            if os.environ.get('NETWORK_LABS_REQUIRE_STRICT') == '1': self.fail('Strict-capable kernel/iproute2 required by this run')
            return
        print('STRICT_VERIFIED: exercising both one-way directions, min-links 1 and 2', flush=True)
        for receiver in (4, 5):
            with self.subTest(receiver=receiver): self.exercise(control_loss=True, receiver=receiver, strict=True)
