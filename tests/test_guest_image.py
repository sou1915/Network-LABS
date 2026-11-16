"""Guest disks are inspected as ext4, never treated as proof of VM boot."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from network_labs.appliances.guest_image import build


class GuestImageTests(unittest.TestCase):
    def test_invalid_sizes_and_existing_destination_never_run_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'disk'
            with patch('subprocess.run', side_effect=AssertionError('unexpected process')):
                for size in (True, 0, 15, 1025, '64'):
                    with self.assertRaises(ValueError):
                        build('/missing', output, size_mib=size)
                output.symlink_to('/missing')
                with self.assertRaises(ValueError):
                    build('/missing', output)
                self.assertTrue(output.is_symlink())

    def test_bad_binary_leaves_no_output_or_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'busybox'
            binary.write_text('not ELF')
            with self.assertRaises(ValueError):
                build(binary, Path(directory) / 'disk')
            self.assertEqual(list(Path(directory).iterdir()), [binary])

    @unittest.skipUnless(os.environ.get('NETWORK_LABS_GUEST_BUSYBOX') and shutil.which('debugfs') and shutil.which('mke2fs'),
                         'Set NETWORK_LABS_GUEST_BUSYBOX and install e2fsprogs for actual image tests')
    def test_actual_ext4_init_ownership_and_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'disk.ext4'
            binary = os.environ['NETWORK_LABS_GUEST_BUSYBOX']
            report = build(binary, output, size_mib=16, with_agent=True)
            self.assertTrue(report['guest_agent_installed'])
            self.assertFalse(report['guest_boot_verified'])
            self.assertFalse(report['guest_control_available'])
            self.assertEqual(output.stat().st_size, 16 * 1024 * 1024)
            def inspect(command):
                return subprocess.run(['debugfs', '-R', command, str(output)],
                                      check=True, capture_output=True, text=True).stdout
            self.assertIn('NETWORK_LABS_GUEST_INIT_COMPLETE', inspect('cat /sbin/init'))
            self.assertIn('exec /bin/busybox init', inspect('cat /sbin/init'))
            self.assertNotIn('/bin/busybox mountpoint', inspect('cat /sbin/init'))
            for name in ('/sbin/init', '/bin/busybox', '/bin/sh', '/etc/shadow'):
                metadata = inspect('stat ' + name)
                self.assertRegex(metadata, r'User:\s+0\s+Group:\s+0')
            self.assertIn('0755', inspect('stat /sbin/init'))
            self.assertIn('0600', inspect('stat /etc/shadow'))
            self.assertIn('1777', inspect('stat /tmp'))
            self.assertNotIn('getty', inspect('cat /etc/inittab'))
            self.assertIn('::respawn:/sbin/network-labs-agent', inspect('cat /etc/inittab'))
            self.assertIn('0755', inspect('stat /sbin/network-labs-agent'))
            self.assertRegex(inspect('stat /sbin/network-labs-agent'), r'User:\s+0\s+Group:\s+0')
            with self.assertRaises(ValueError):
                build(binary, output)
            failed = Path(directory) / 'failed.ext4'
            with self.assertRaises(ValueError):
                build(binary, failed, mke2fs='/bin/false')
            self.assertFalse(failed.exists())
            with self.assertRaises(ValueError):
                build(binary, failed, with_agent=True, cc='/bin/false')
            self.assertFalse(failed.exists())
            self.assertEqual(list(Path(directory).iterdir()), [output])
