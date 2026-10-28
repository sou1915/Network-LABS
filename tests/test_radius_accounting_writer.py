"""Real BusyBox append failure, validation and concurrent record checks."""
import os
from pathlib import Path
import resource
import signal
import subprocess
import tempfile
import unittest

from network_labs.appliances.radius_accounting_writer import WRITER


@unittest.skipUnless(Path('/bin/busybox').is_file(), 'Real BusyBox required')
class AccountingWriterTests(unittest.TestCase):
    def test_selected_fields_locking_and_partial_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer = root / 'writer.sh'; writer.write_text(WRITER)
            log = root / 'sessions'
            environment = dict(os.environ, USER_NAME='"learner"', ACCT_SESSION_ID='"aaa-first"',
                               NAS_IP_ADDRESS='192.0.2.10', ACCT_STATUS_TYPE='Start')
            args = ['/bin/busybox', 'sh', '-x', str(writer), str(log)]
            def run(**overrides):
                return subprocess.run(args, env=dict(environment, **overrides), capture_output=True, timeout=3)
            first = run()
            self.assertEqual(first.returncode, 0, first.stderr.decode())
            before = log.read_bytes()
            self.assertEqual(before, b'Start|aaa-first|learner|192.0.2.10|0|0\n')
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)
            for overrides in ({'USER_NAME': '"bad|name"'}, {'ACCT_SESSION_ID': '"$(id)"'},
                              {'ACCT_STATUS_TYPE': 'Stop', 'ACCT_SESSION_TIME': '4294967296',
                               'ACCT_TERMINATE_CAUSE': 'User-Request'}):
                self.assertEqual(run(**overrides).returncode, 2)
                self.assertEqual(log.read_bytes(), before)
            def partial_write_limit():
                signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
                resource.setrlimit(resource.RLIMIT_FSIZE, (len(before) + 8, len(before) + 8))
            failed = subprocess.run(args, env=dict(environment, ACCT_SESSION_ID='"aaa-new"'),
                                    preexec_fn=partial_write_limit, capture_output=True, timeout=3)
            self.assertEqual(failed.returncode, 2, failed)
            self.assertEqual(log.read_bytes(), before, 'Failed append must not leave a partial record')
            workers = [subprocess.Popen(args, env=dict(environment, ACCT_SESSION_ID='"aaa-parallel-%d"' % index),
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for index in range(8)]
            try:
                self.assertEqual([worker.wait(timeout=3) for worker in workers], [0] * 8)
            finally:
                for worker in workers:
                    if worker.poll() is None: worker.kill(); worker.wait(timeout=3)
            lines = log.read_text().splitlines()
            self.assertEqual(len(lines), 9)
            self.assertEqual({line.split('|')[1] for line in lines[1:]},
                             {'aaa-parallel-%d' % index for index in range(8)})
            self.assertTrue(all(len(line.split('|')) == 6 for line in lines))
