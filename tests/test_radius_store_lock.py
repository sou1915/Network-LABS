"""Accounting capacity and atomic mutation across independent session callers."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from network_labs.appliances import radius_outbox as outbox
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.runtime import Manager, RuntimeFailure

SECRET = 'accounting-store-private-secret'


class StoreLockTests(unittest.TestCase):
    def manager(self):
        manager = Manager('store-lock')
        manager.state = {'phase': 'running', 'spec': radius_lab('/rootfs', SECRET, 'a' * 64,
            allow_shell=True, accounting=True, accounting_outbox=True)}
        return manager

    def test_parallel_enqueues_keep_capacity_without_partial_or_lost_records(self):
        with tempfile.TemporaryDirectory() as d, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(d) / 'saved'), \
                patch.object(outbox, 'MAX_ENTRIES', 2):
            manager = self.manager()
            def enqueue(n):
                try:
                    outbox.enqueue(manager, 'PC1', '192.0.2.20', 'learner', SECRET, 'aaa-' + format(n, '032x'),
                                   1, 9, 1, cleanup_complete=True)
                    return 'stored'
                except RuntimeFailure:
                    return 'full'
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(enqueue, range(8)))
            self.assertEqual(results.count('stored'), 2)
            self.assertEqual(outbox.pending(manager)['pending'], 2)
            self.assertEqual(len(list(outbox.folder(manager).iterdir())), 2)

    def test_lock_is_reentrant_and_serializes_an_independent_process(self):
        with tempfile.TemporaryDirectory() as d, patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(d) / 'saved'):
            manager = self.manager(); root = Path(d); process = None
            script = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from network_labs.appliances import runtime, radius_outbox
runtime.CONFIG_ROOT = Path(sys.argv[2])
Path(sys.argv[3]).write_text('waiting')
with radius_outbox.store_lock(runtime.Manager('store-lock')):
    Path(sys.argv[4]).write_text('acquired')
'''
            try:
                with outbox.store_lock(manager):
                    with outbox.store_lock(manager): pass
                    process = subprocess.Popen([sys.executable, '-I', '-c', script, str(Path(__file__).parents[1]),
                        str(root / 'saved'), str(root / 'waiting'), str(root / 'acquired')])
                    until = time.monotonic() + 2
                    while not (root / 'waiting').exists() and time.monotonic() < until: time.sleep(.01)
                    self.assertTrue((root / 'waiting').exists())
                    time.sleep(.05); self.assertFalse((root / 'acquired').exists())
                self.assertEqual(process.wait(timeout=3), 0)
                self.assertTrue((root / 'acquired').exists())
            finally:
                if process is not None and process.poll() is None: process.kill(); process.wait(timeout=1)

    def test_unsafe_lock_files_refuse_mutation(self):
        for kind in ('symlink', 'permissions', 'hardlink', 'fifo'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as d, \
                    patch('network_labs.appliances.runtime.CONFIG_ROOT', Path(d) / 'saved'):
                manager = self.manager(); lock = outbox.folder(manager, True).parent / 'accounting.lock'
                if kind == 'symlink': lock.symlink_to(Path(d) / 'outside')
                elif kind == 'fifo': os.mkfifo(lock, 0o600)
                else:
                    lock.touch(mode=0o600)
                    if kind == 'permissions': lock.chmod(0o644)
                    else: os.link(lock, Path(d) / 'other-link')
                with self.assertRaises((RuntimeFailure, OSError)):
                    with outbox.store_lock(manager): self.fail('Unsafe lock accepted')
                self.assertEqual(outbox.pending(manager)['pending'], 0)
