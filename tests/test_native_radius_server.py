import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import Mock, patch

from network_labs.appliances.examples import radius_lab
from network_labs.appliances.radius_server import config_text, prepare_files, observe, redact, start_servers
from network_labs.appliances.runtime import RuntimeFailure, static_busybox_rootfs
from network_labs.appliances.spec import load, validate
from network_labs.appliances.__main__ import main

SECRET = 'private-managed-radius-secret'
PASSWORD = 'private-managed-radius-password'
DIGEST = hashlib.sha256(PASSWORD.encode()).hexdigest()


class RadiusServerTests(unittest.TestCase):
    def test_private_manifest_and_generated_files_use_hashes_not_passwords(self):
        spec = radius_lab('/rootfs', SECRET, DIGEST); node = spec['nodes'][2]
        self.assertNotIn(PASSWORD, json.dumps(spec))
        text = config_text(node)
        self.assertIn('SHA2-Password := 0x' + DIGEST, text)
        self.assertIn('ipaddr = 192.0.2.20', text)
        self.assertIn('require_message_authenticator = yes', text)
        self.assertNotIn('Cleartext-Password', text)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'files').mkdir()
            prepare_files(root, node)
            self.assertEqual((root / 'files/radius').stat().st_mode & 0o777, 0o700)
            self.assertEqual((root / 'files/radius/radiusd.conf').stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / 'files/radius/radiusd.conf').read_text(), text)
            manifest = root / 'radius.json'; manifest.write_text(json.dumps(spec)); manifest.chmod(0o644)
            with self.assertRaises(ValueError): load(manifest)
            manifest.chmod(0o600)
            self.assertEqual(load(manifest), spec)

    def test_rejects_config_injection_unmanaged_clients_and_service_collisions(self):
        for secret in ('short', 'x' * 16 + '"', 'x' * 16 + '$', 'x' * 16 + '\\', 'x' * 16 + '\n'):
            with self.subTest(secret=secret), self.assertRaises(ValueError): radius_lab('/rootfs', secret, DIGEST)
        for edit in (
                lambda n: n['radius_server']['clients'].append(copy.deepcopy(n['radius_server']['clients'][0])),
                lambda n: n['radius_server']['clients'][0].update(address='192.0.2.99'),
                lambda n: n['radius_server']['clients'][0].update(address='192.0.2.20'),
                lambda n: n['radius_server']['users'].update({'bad"name': {'password_sha256': DIGEST}}),
                lambda n: n['radius_server']['users']['learner'].update(password_sha256='bad'),
                lambda n: n.update(startup=[['/bin/echo', 'unmanaged']]),
                lambda n: n['interfaces'].update(eth1='192.0.3.1/24'),
                lambda n: n.update(ntp_server={'interface': 'eth0', 'local_stratum': 10, 'clients': ['192.0.2.10']})):
            spec = radius_lab('/rootfs', SECRET, DIGEST); edit(spec['nodes'][2])
            with self.assertRaises(ValueError): validate(spec)
        spec = radius_lab('/rootfs', SECRET, DIGEST)
        other = copy.deepcopy(spec['nodes'][0]); other['name'] = 'PC3'; spec['nodes'].append(other)
        with self.assertRaises(ValueError): validate(spec)

    def test_observation_and_normal_reports_do_not_expose_credential_material(self):
        spec = radius_lab('/rootfs', SECRET, DIGEST); manager = Mock(); node = spec['nodes'][2]
        fingerprint = hashlib.sha256(config_text(node).encode()).hexdigest()
        permissions = ['600:0:0\n700:0:0\n']
        def reply(*args, **kwargs):
            value = permissions[0] if 'stat' in args else fingerprint + '  /lab/radius/radiusd.conf\n'
            return subprocess.CompletedProcess([], 0, value, SECRET)
        manager.crun.side_effect = reply
        report = observe(manager, node)
        self.assertTrue(report['configuration_verified'])
        self.assertNotIn(SECRET, json.dumps(report)); self.assertNotIn(DIGEST, json.dumps(report))
        permissions[0] = '644:0:0\n700:0:0\n'
        self.assertFalse(observe(manager, node)['configuration_verified'])
        original = copy.deepcopy(spec); safe = redact({'spec': spec})
        self.assertNotIn(SECRET, json.dumps(safe)); self.assertNotIn(DIGEST, json.dumps(safe))
        self.assertEqual(spec, original)
        manager.crun.side_effect = None
        manager.crun.return_value = subprocess.CompletedProcess([], 0, SECRET, '')
        self.assertFalse(observe(manager, node)['configuration_available'])

    def test_accounting_writer_drift_or_timeout_invalidates_configuration(self):
        from network_labs.appliances.radius_accounting_writer import SCRIPT, WRITER
        from network_labs.appliances.radius_server import CONFIG
        node = radius_lab('/rootfs', SECRET, DIGEST, allow_shell=True, accounting=True)['nodes'][2]
        for fault in (None, 'hash', 'mode', 'timeout'):
            manager = Mock()
            def reply(*args, **kwargs):
                if SCRIPT in args:
                    if fault == 'timeout': raise subprocess.TimeoutExpired('writer observation', 3)
                    if 'stat' in args:
                        text = '755:0:0\n' if fault == 'mode' else '700:0:0\n'
                    else:
                        digest = '0' * 64 if fault == 'hash' else hashlib.sha256(WRITER.encode()).hexdigest()
                        text = digest + '  ' + SCRIPT + '\n'
                elif 'stat' in args: text = '600:0:0\n700:0:0\n'
                else: text = hashlib.sha256(config_text(node).encode()).hexdigest() + '  ' + CONFIG + '\n'
                return subprocess.CompletedProcess([], 0, text, '')
            manager.crun.side_effect = reply
            with patch('network_labs.appliances.radius_observation.observe_process', return_value={}), \
                 patch('network_labs.appliances.ntp_socket.observe_socket', return_value={}):
                result = observe(manager, node)
            self.assertEqual(result['configuration_verified'], fault is None, result)
            self.assertEqual(result['writer_verified'], fault is None, result)

    def test_failed_parser_never_echoes_private_config_and_ready_start_is_bounded(self):
        spec = radius_lab('/rootfs', SECRET, DIGEST); manager = Mock(); manager.state = {'spec': spec}
        with tempfile.TemporaryDirectory() as folder:
            manager.directory = Path(folder); (manager.directory / 'PC2').mkdir()
            manager.crun.return_value = subprocess.CompletedProcess([], 1, SECRET, PASSWORD)
            with self.assertRaises(RuntimeFailure) as caught: start_servers(manager)
            self.assertNotIn(SECRET, str(caught.exception)); self.assertNotIn(PASSWORD, str(caught.exception))
            self.assertEqual(manager.crun.call_count, 1)
            def crun(*args, **options):
                if '--detach' in args: options['log'].write_text('Ready to process requests\n')
                return subprocess.CompletedProcess([], 0, '', '')
            manager.crun.side_effect = crun
            start_servers(manager)
            self.assertEqual((manager.directory / 'PC2/radius.log').stat().st_mode & 0o777, 0o600)

    def test_rootfs_options_require_complete_assets_before_creating_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); binary = root / 'busybox'
            elf = bytearray(128); elf[:6] = b'\x7fELF\x02\x01'
            struct.pack_into('<Q', elf, 32, 64); struct.pack_into('<HH', elf, 54, 56, 1)
            struct.pack_into('<I', elf, 64, 1); binary.write_bytes(elf)
            destination = root / 'rootfs'
            with self.assertRaises(ValueError): static_busybox_rootfs(binary, destination, freeradius='/bin/freeradius')
            self.assertFalse(destination.exists())
            asset = root / 'asset'; asset.write_text('trusted-test-asset')
            with patch('network_labs.appliances.radius_rootfs.rootfs_assets', return_value=[(asset, Path('/usr/lib/network-labs/freeradius/server'))]):
                static_busybox_rootfs(binary, destination, freeradius=asset, freeradius_modules=root, freeradius_dictionaries=root)
            self.assertEqual((destination / 'usr/lib/network-labs/freeradius/server').read_text(), 'trusted-test-asset')
            self.assertTrue((destination / 'etc/network-labs-radius-assets.json').exists())

    def test_dictionary_assets_include_pap_and_reject_symlinks(self):
        from network_labs.appliances.radius_rootfs import rootfs_assets
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); modules = root / 'modules'; modules.mkdir()
            dictionaries = root / 'dictionaries'; dictionaries.mkdir()
            (modules / 'rlm_pap.so').write_text('module'); (dictionaries / 'dictionary').write_text('dictionary')
            with patch('network_labs.appliances.radius_rootfs.assets', return_value=[]), \
                 patch('network_labs.appliances.radius_rootfs.shared_library_assets', return_value=[(modules / 'rlm_pap.so', Path('/usr/lib/network-labs/freeradius/modules/rlm_pap.so'))]):
                plan = rootfs_assets('/binary', modules, dictionaries)
                self.assertEqual(len(plan), 2)
                (dictionaries / 'unsafe').symlink_to(dictionaries / 'dictionary')
                with self.assertRaises(ValueError): rootfs_assets('/binary', modules, dictionaries)

    def test_rootfs_includes_dlopen_legacy_provider_and_fails_if_unavailable(self):
        from network_labs.appliances.radius_rootfs import rootfs_assets
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); modules = root / 'modules'; modules.mkdir()
            dictionaries = root / 'dictionaries'; dictionaries.mkdir()
            (modules / 'rlm_pap.so').touch(); (dictionaries / 'dictionary').touch()
            crypto = root / 'libcrypto.so.3'; crypto.touch()
            with patch('network_labs.appliances.radius_rootfs.assets', return_value=[(crypto, Path('/usr/lib/libcrypto.so.3'))]), \
                 patch('network_labs.appliances.radius_rootfs.shared_library_assets', side_effect=lambda source, destination: [(Path(source), Path(destination))]):
                with self.assertRaises(ValueError): rootfs_assets('/binary', modules, dictionaries)
                provider = root / 'ossl-modules/legacy.so'; provider.parent.mkdir(); provider.touch()
                plan = rootfs_assets('/binary', modules, dictionaries)
                self.assertIn((provider, provider), plan)

    def test_cli_example_hashes_private_password_and_requires_explicit_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); password = root / 'password'; secret = root / 'secret'
            for path, value in ((password, PASSWORD), (secret, SECRET)):
                path.write_text(value); path.chmod(0o600)
            with redirect_stdout(io.StringIO()) as output:
                code = main(['example', '--radius', '--rootfs', '/rootfs', '--radius-user', 'learner',
                             '--radius-password-file', str(password), '--radius-secret-file', str(secret)])
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue()); self.assertEqual(result['name'], 'radius-lan')
            self.assertNotIn(PASSWORD, output.getvalue())
            self.assertEqual(result['nodes'][2]['radius_server']['users']['learner']['password_sha256'], DIGEST)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(['example', '--radius', '--rootfs', '/rootfs']), 1)
                self.assertEqual(main(['example', '--radius', '--ntp', '--rootfs', '/rootfs']), 1)
