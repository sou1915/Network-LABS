"""First launch: verified downloads, the full guest disk, the checklist and the remembered paths."""
import hashlib
import io
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest import mock

from network_labs.appliances import setup


def archive(members):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as tar:
        for name, body in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return data.getvalue()


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        patcher = mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': self.folder.name + '/config',
                                               'XDG_DATA_HOME': self.folder.name + '/data'})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop('NETWORK_LABS_MICROVM_KERNEL', None)

    def test_downloads_are_refused_unless_their_checksum_matches(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'not the release'
        with mock.patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                setup._download('https://example.invalid/x', '0' * 64)
            body = b'the release'
            response.__enter__.return_value.read.return_value = body
            self.assertEqual(setup._download('https://example.invalid/x', hashlib.sha256(body).hexdigest()), body)

    def test_only_the_two_known_programs_are_taken_from_the_release(self):
        members = {name: name.encode() for name in setup.FIRECRACKER['members']}
        members['release-v1.10.1-x86_64/../../evil'] = b'x'
        folder = setup.fetch_firecracker(self.folder.name, fetch=lambda url, sha: archive(members))
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['firecracker', 'jailer'])
        self.assertTrue(os.access(folder / 'firecracker', os.X_OK))
        self.assertFalse((Path(self.folder.name).parent / 'evil').exists())

    def test_the_network_labs_kernel_is_downloaded_once_its_checksum_is_pinned(self):
        fetched = []

        def fetch(url, sha256):
            fetched.append((url, sha256))
            return b'kernel'
        self.assertIs(setup.kernel_release(), setup.GUEST_KERNEL if setup.GUEST_KERNEL['sha256'] else setup.KERNEL)
        with mock.patch.dict(setup.GUEST_KERNEL, sha256='a' * 64), mock.patch.object(setup, '_which', return_value=None):
            result = setup.prepare(download=True, folder=self.folder.name, fetch=fetch)
        self.assertIn((setup.GUEST_KERNEL['url'], 'a' * 64), fetched)
        self.assertTrue(result['kernel'].endswith('vmlinux-5.10.223-network-labs'))
        self.assertEqual((Path(self.folder.name) / 'vmlinux-5.10.223-network-labs').read_bytes(), b'kernel')
        self.assertNotIn('vlan-kernel', [s['id'] for s in result['steps']])  # VLANs come with this kernel
        self.assertTrue(setup.GUEST_KERNEL['url'].startswith('https://github.com/sou1915/Network-LABS/releases/download/'))
        with mock.patch.dict(setup.GUEST_KERNEL, sha256=None), mock.patch.object(setup, '_which', return_value=None):
            fetched.clear()
            result = setup.prepare(download=True, folder=self.folder.name + '/other', fetch=fetch)
        self.assertEqual(fetched[-1], (setup.KERNEL['url'], setup.KERNEL['sha256']))  # Firecracker's, until then
        self.assertIn('vlan-kernel', [s['id'] for s in result['steps']])

    def test_checklist_without_downloads_names_each_fix(self):
        with mock.patch.object(setup, '_which', return_value=None):
            result = setup.prepare(folder=self.folder.name)
        self.assertFalse(result['ready'])
        failed = {s['id']: s['fix'] for s in result['steps'] if not s['ok']}
        self.assertIn('--download', failed['firecracker'])
        self.assertIn('apt install', failed['tools'])
        self.assertIn('--download', failed['kernel'])
        text = setup.report(result)
        self.assertIn('Pas encore prêt', text)
        self.assertIn('→ sudo apt install', text)

    @unittest.skipUnless(all(setup._which(n) for n in ('busybox', 'mke2fs', 'debugfs', 'gcc', 'bird', 'birdc'))
                         and all(setup._which(setup.TOOLS[n]) for n in ('keepalived', 'dnsmasq', 'chronyd', 'chronyc'))
                         and setup._which(('xtables-legacy-multi', 'iptables-legacy')), 'image tools required')
    def test_builds_one_full_disk_once_and_remembers_the_paths(self):
        from network_labs.appliances import progress
        kernel = Path(self.folder.name) / 'vmlinux'
        kernel.write_bytes(b'k')
        first = setup.prepare(kernel=kernel, folder=self.folder.name)
        image = {s['id']: s for s in first['steps']}['image']
        self.assertTrue(image['ok'], image)
        self.assertIn('construit', image['detail'])
        listing = shutil.which('debugfs') or '/usr/sbin/debugfs'
        import subprocess
        files = subprocess.run([listing, '-R', 'ls /usr/sbin', first['disk']], capture_output=True, text=True).stdout
        for program in ('bird', 'keepalived', 'dnsmasq', 'chronyd'):
            self.assertIn(program, files)
        again = setup.prepare(kernel=kernel, folder=self.folder.name)
        self.assertIn('à jour', {s['id']: s for s in again['steps']}['image']['detail'])
        self.assertEqual(progress.load()['paths'], {'kernel': str(kernel), 'disk': first['disk']})


if __name__ == '__main__':
    unittest.main()
