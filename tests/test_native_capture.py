"""Capture bounds, descriptor isolation, output safety and child cleanup."""
from contextlib import contextmanager
import os
from pathlib import Path
import signal
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from network_labs.appliances.capture import capture, limits, pcap_summary, _finish
from network_labs.appliances.runtime import RuntimeFailure
from network_labs.appliances.spec import example, namespace


def pcap(endian='<', nano=False, payload=b'packet'):
    magic = (b'\x4d\x3c\xb2\xa1' if nano else b'\xd4\xc3\xb2\xa1') if endian == '<' else (b'\xa1\xb2\x3c\x4d' if nano else b'\xa1\xb2\xc3\xd4')
    header = magic + struct.pack(endian + 'HHIIII', 2, 4, 0, 0, 64, 1)
    return header + struct.pack(endian + 'IIII', 1, 0, len(payload), len(payload)) + payload


class CaptureTests(unittest.TestCase):
    def test_packet_time_and_file_budgets_fail_before_host_actions(self):
        for changes in ({'seconds': 0}, {'seconds': 61}, {'seconds': True}, {'packets': 10001},
                        {'snaplen': 1}, {'snaplen': 65536}, {'snaplen': 65535, 'packets': 10000},
                        {'expression': 'a' * 513}, {'expression': 'icmp\0'}):
            options = dict(seconds=10, packets=100, snaplen=2048, expression='icmp'); options.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                limits(**options)

    def test_pcap_endianness_precision_empty_and_truncated_records(self):
        with tempfile.TemporaryFile('w+b') as handle:
            for endian in ('<', '>'):
                for nano in (False, True):
                    raw = pcap(endian, nano)
                    handle.seek(0); handle.truncate(); handle.write(raw)
                    self.assertEqual(pcap_summary(handle)['captured_packets'], 1)
            for raw in (b'', b'not pcap' * 4, pcap()[:-1], pcap()[:30], pcap(payload=b'a' * 65)):
                handle.seek(0); handle.truncate(); handle.write(raw)
                with self.assertRaises(RuntimeFailure):
                    pcap_summary(handle)
            handle.seek(0); handle.truncate(); handle.write(pcap()[:24])
            self.assertEqual(pcap_summary(handle)['captured_packets'], 0)

    def test_capture_pins_namespace_releases_lock_and_passes_filter_literally(self):
        spec = example('/rootfs'); locked = []; ready = []
        @contextmanager
        def lock():
            locked.append(True)
            try:
                yield
            finally:
                locked.pop()
        manager = SimpleNamespace(name=spec['name'], locked=lock, read=lambda: {'phase': 'running', 'spec': spec},
                                  crun=Mock(return_value=subprocess.CompletedProcess([], 0, '{"status":"running"}', '')),
                                  ns=Mock())
        class Process:
            def __init__(self, args, **kwargs):
                self.returncode = None; self.stderr = None
                self.args = args; self.options = kwargs
                self.assert_fd = os.fstat(kwargs['pass_fds'][0])
                self.active_lock = bool(locked)
                kwargs['stdout'].write(pcap())
            def communicate(self, timeout):
                self.returncode = 0
                return None, b''
            def poll(self):
                return self.returncode
        expression = 'icmp or host 192.0.2.20; echo nope'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / namespace(spec, 0)).touch()
            children = []
            def spawn(*args, **kwargs):
                child = Process(*args, **kwargs); children.append(child); return child
            with patch('network_labs.appliances.capture.NETNS_ROOT', root), patch('shutil.which', side_effect=lambda p: '/usr/bin/' + p), \
                 patch('network_labs.appliances.capture.subprocess.Popen', side_effect=spawn), patch('network_labs.appliances.capture._ready', return_value=b'listening on eth0'), patch.dict(os.environ, {}, clear=True):
                report = capture(manager, 'PC1', 'eth0', root / 'capture.pcap', snaplen=64, expression=expression,
                                 ready=lambda: ready.append(not locked))
            child = children[0]
            self.assertTrue(child.active_lock); self.assertEqual(ready, [True])
            self.assertEqual(child.args[-2:], ['--', expression])
            self.assertIn('-p', child.args)
            self.assertTrue(any(a.startswith('--net=/proc/self/fd/') for a in child.args))
            self.assertEqual(child.args[:4], ['/usr/bin/timeout', '--signal=INT', '--kill-after=2s', '10s'])
            self.assertNotIn('shell', child.options)
            self.assertEqual(child.options['env']['LC_ALL'], 'C')
            self.assertEqual(report['captured_packets'], 1)
            self.assertEqual((root / 'capture.pcap').stat().st_mode & 0o777, 0o600)
            self.assertTrue(child.options['stderr'].closed)
            manager.crun.assert_called_once_with('state', 'PC1', check=False)
            manager.ns.assert_called_once_with(0, 'ip', 'link', 'show', 'dev', 'eth0')

    def test_interface_and_output_rejections_never_spawn_capture(self):
        spec = example('/rootfs')
        from contextlib import nullcontext
        manager = SimpleNamespace(name=spec['name'], locked=nullcontext, read=lambda: {'phase': 'running', 'spec': spec},
                                  crun=lambda *a, **k: subprocess.CompletedProcess([], 0, '{"status":"running"}', ''), ns=lambda *a: None)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / namespace(spec, 0)).touch()
            target = root / 'existing.pcap'; target.write_bytes(b'keep')
            symlink = root / 'symlink.pcap'; symlink.symlink_to(target)
            with patch('network_labs.appliances.capture.NETNS_ROOT', root), patch('shutil.which', return_value='/tool'), \
                 patch('network_labs.appliances.capture.subprocess.Popen') as spawn:
                for port in ('any', 'eno1', '--help', 'eth99'):
                    with self.assertRaises(ValueError):
                        capture(manager, 'PC1', port, root / 'unused')
                for path in (target, symlink):
                    with self.assertRaises(FileExistsError):
                        capture(manager, 'PC1', 'eth0', path)
                with self.assertRaises(ValueError):
                    capture(manager, 'MISSING', 'eth0', root / 'unused')
                spawn.assert_not_called()
            self.assertEqual(target.read_bytes(), b'keep')

    def test_cleanup_interrupts_then_kills_a_stalled_capture(self):
        process = Mock()
        process.pid = 12345
        process.poll.return_value = None
        process.communicate.side_effect = [subprocess.TimeoutExpired('tcpdump', 2), (None, b'closed')]
        with patch('network_labs.appliances.capture.os.killpg') as kill_group:
            self.assertEqual(_finish(process), b'closed')
            kill_group.assert_called_once_with(12345, signal.SIGKILL)
        process.send_signal.assert_called_once_with(signal.SIGINT)

    def test_missing_capture_tool_has_no_lifecycle_fallback(self):
        manager = Mock()
        with patch('shutil.which', return_value=None), self.assertRaises(RuntimeFailure):
            capture(manager, 'PC1', 'eth0', '/unused')
        manager.locked.assert_not_called()
