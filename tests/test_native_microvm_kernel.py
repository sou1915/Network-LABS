"""Real guest kernel capabilities: boot one guest and compare its KERNEL report with NETWORK_LABS_EXPECT_KERNEL."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
from network_labs.appliances.guest_image import build
from network_labs.appliances.guest_startup import query
from network_labs.appliances.microvm import router_example
from network_labs.appliances.runtime import Manager, process_identity


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1' and os.environ.get('NETWORK_LABS_EXPECT_KERNEL'),
                     'Opt-in real KVM test with an expected kernel report')
class GuestKernelTests(unittest.TestCase):
    def test_guest_kernel_reports_the_expected_capabilities(self):
        expected = dict(item.split('=') for item in os.environ['NETWORK_LABS_EXPECT_KERNEL'].split(','))
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'kernel'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlkr-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = router_example(kernel, root / 'base.ext4')
            state = patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state')
            config = patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config')
            with state, config:
                manager = Manager(spec['name'])
                records = []
                with manager.locked():
                    try:
                        manager.start(spec)
                        records.extend(manager.state['vms'])
                        socket = manager.directory / 'R1' / 'guest.vsock'
                        deadline = time.monotonic() + 40
                        while True:
                            try:
                                query(socket, 'ready')
                                break
                            except (ValueError, OSError):
                                if time.monotonic() >= deadline:
                                    raise
                                time.sleep(.1)
                        report = dict(line.split('=') for line in query(socket, 'kernel').splitlines())
                        (evidence / 'result.json').write_text(json.dumps({'kernel': str(kernel), 'report': report}, indent=2))
                        print('GUEST_KERNEL_CAPABILITIES ' + json.dumps(report, sort_keys=True), flush=True)
                        self.assertEqual({key: report.get(key) for key in expected}, expected, report)
                    finally:
                        manager.state = None
                        if manager.directory.exists():
                            manager.stop()
                for record in records:
                    self.assertNotEqual(process_identity(record['pid']), record['starttime'])
