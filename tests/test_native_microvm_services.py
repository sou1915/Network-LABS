"""Server services on real guests: SRV serves DNS (www.lab.local, web.lab.local as an alias), its web pages, NTP and a
syslog collector and TFTP; R1, between PC1's LAN and the server's, has « ip name-server », « ntp server » and « logging host »
typed in its CLI. PC1 resolves the names and fetches the pages from the server across R1, R1 pings a name and
synchronises its clock to SRV, and R1's log messages reach SRV's collector; R1 backs its configuration up to SRV by TFTP."""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances import guest_console
from network_labs.appliances.guest_image import build
from network_labs.appliances.runtime import Manager

from tests.test_guest_services import configured
from tests.test_native_microvm_missions import wait_ready


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class ServicesGuestTests(unittest.TestCase):
    def test_dns_web_ntp_and_syslog(self):
        self.assertEqual(os.geteuid(), 0)
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'services'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlsv-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = configured(str(kernel), str(root / 'base.ext4'))
            seen = {}
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), \
                    patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name'])
                try:
                    with manager.locked():
                        manager.start(spec)
                        wait_ready(manager, spec)
                    consoles = {name: guest_console.Console(spec['name'], name) for name in ('R1', 'SRV', 'PC1')}
                    consoles['R1'].line('en')
                    seen['PC1 nslookup'] = consoles['PC1'].line('nslookup web.lab.local')
                    seen['PC1 reverse'] = consoles['PC1'].line('nslookup 10.0.0.10')
                    seen['PC1 curl'] = consoles['PC1'].line('curl http://www.lab.local/hello.html')
                    seen['PC1 404'] = consoles['PC1'].line('curl -i http://www.lab.local/none.html')
                    seen['R1 ping name'] = consoles['R1'].line('ping www.lab.local')
                    deadline = time.monotonic() + 40
                    while True:
                        seen['R1 ntp status'] = consoles['R1'].line('show ntp status')
                        if seen['R1 ntp status'].startswith('Clock is synchronized') or time.monotonic() >= deadline:
                            break
                        time.sleep(2)
                    seen['R1 ntp associations'] = consoles['R1'].line('show ntp associations')
                    seen['R1 clock'] = consoles['R1'].line('show clock')
                    for line in ('conf t', 'logging trap debugging', 'end'):  # « end »: %SYS-5-CONFIG_I, to the collector
                        consoles['R1'].line(line)
                    time.sleep(1)
                    seen['SRV logread'] = consoles['SRV'].line('logread')
                    seen['R1 copy run tftp'] = '\n'.join(consoles['R1'].line(l) for l in ('copy running-config tftp:', '10.0.0.10', ''))
                    seen['SRV tftpboot'] = consoles['SRV'].line('cat /tftpboot/r1-confg')
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            (evidence / 'result.json').write_text(json.dumps(seen, indent=2, ensure_ascii=False))
            for label, text in seen.items():
                print(f'\n{label}:\n{text}', flush=True)
            self.assertIn('web.lab.local\tcanonical name = www.lab.local', seen['PC1 nslookup'])
            self.assertIn('Address: 10.0.0.10', seen['PC1 nslookup'])
            self.assertIn('name = www.lab.local', seen['PC1 reverse'])
            self.assertIn('<h1>Hello, World!</h1>', seen['PC1 curl'])
            self.assertTrue(seen['PC1 404'].startswith('HTTP/1.1 404'), seen['PC1 404'])
            self.assertIn('[OK]', seen['R1 ping name'])
            self.assertIn('Success rate is 100 percent', seen['R1 ping name'])
            self.assertTrue(seen['R1 ntp status'].startswith('Clock is synchronized, stratum 2, reference is 10.0.0.10'))
            self.assertIn('*~10.0.0.10', seen['R1 ntp associations'])
            self.assertFalse(seen['R1 clock'].startswith('*'))
            self.assertRegex(seen['R1 copy run tftp'], r'!!\n\d+ bytes copied')
            self.assertIn('ip name-server 10.0.0.10', seen['SRV tftpboot'])
            self.assertRegex(seen['SRV logread'], r'10\.0\.0\.1 <189>\d+: \*\w{3} +\d+ [\d:.]+: %SYS-5-CONFIG_I: Configured from console by console')
