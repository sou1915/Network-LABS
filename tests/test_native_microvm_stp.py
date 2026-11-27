"""Spanning tree on real switch guests: two 2960s joined by two cables (a loop, so classic STP runs in each guest kernel).
Exactly one port blocks, on the switch that is not the root, and PC1 still reaches PC2; « spanning-tree vlan 1 root
primary » typed live on that switch makes it the root and moves the blocked port to the other; shutting the new
non-root switch's root port brings its blocked port to forwarding, and PC1 still reaches PC2 (the redundant cable)."""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances import guest_console, guest_stp
from network_labs.appliances.guest_image import build
from network_labs.appliances.runtime import Manager, guest_mac

from tests.test_guest_stp import lab, ports
from tests.test_native_microvm_missions import wait_ready


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class SpanningTreeGuestTests(unittest.TestCase):
    def test_one_port_blocks_root_primary_moves_it_and_the_blocked_cable_takes_over(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'stp'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlstp-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = lab(str(kernel), str(root / 'base.ext4'))
            first = min(('SW1', 'SW2'), key=lambda n: guest_mac(n, 'eth0'))  # equal priorities: the lowest bridge MAC
            second = 'SW2' if first == 'SW1' else 'SW1'
            transcript, seen = [], {}
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), \
                    patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name'])
                try:
                    with manager.locked():
                        manager.start(spec)
                        wait_ready(manager, spec)
                    consoles = {name: guest_console.Console(spec['name'], name) for name in ('SW1', 'SW2', 'PC1')}
                    for name in ('SW1', 'SW2'):
                        consoles[name].line('en')

                    def typed(name, lines):
                        for line in lines:
                            prompt = consoles[name].prompt()
                            reply = consoles[name].line(line)
                            transcript.append(prompt + line + ('\n' + reply if reply else ''))
                        return transcript[-1]

                    def converged(blocking, label):
                        """Wait for BLOCKING's Fa0/2 (or Fa0/1) to block and the other switch's ports to forward."""
                        deadline = time.monotonic() + 40
                        while True:
                            views = {name: ports(consoles[name].line('show spanning-tree')) for name in ('SW1', 'SW2')}
                            states = sorted(state for view in views.values() for _, state in view.values())
                            if states.count('BLK') == 1 and set(states) == {'BLK', 'FWD'} and \
                                    'BLK' in [s for _, s in views[blocking].values()]:
                                break
                            if time.monotonic() >= deadline:
                                self.fail(f'{label}: no converged tree: {views}')
                            time.sleep(1)
                        seen[label] = views

                    def ping(label):
                        for _ in range(10):
                            seen[label] = consoles['PC1'].line('ping 192.168.1.20')
                            if '4 packets received' in seen[label]:
                                break
                            time.sleep(2)

                    converged(second, 'initial tree')
                    ping('PC1 -> PC2, initial tree')
                    typed(second, ['show spanning-tree'])
                    typed(first, ['show spanning-tree', 'show mac address-table'])
                    typed(second, ['conf t', 'spanning-tree vlan 1 root primary', 'end'])
                    converged(first, 'after root primary')
                    typed(second, ['show spanning-tree'])
                    typed(first, ['show spanning-tree'])
                    root_port = next(p for p, (role, _) in seen['after root primary'][first].items() if role == 'Root')
                    typed(first, ['conf t', f'int {root_port}', 'shutdown', 'end'])
                    deadline = time.monotonic() + 40
                    while True:  # the alternate port becomes the root port: listening, learning, then forwarding
                        view = ports(consoles[first].line('show spanning-tree'))
                        if ('Root', 'FWD') in view.values() and {s for _, s in view.values()} == {'FWD'}:
                            break
                        self.assertLess(time.monotonic(), deadline, f'the blocked cable never took over: {view}')
                        time.sleep(1)
                    seen['after the root port is shut'] = view
                    typed(first, ['show spanning-tree'])
                    ping('PC1 -> PC2, over the redundant cable')
                finally:
                    with manager.locked():
                        if manager.directory.exists():
                            manager.stop()
            text = '\n'.join(transcript)
            (evidence / 'result.json').write_text(json.dumps({'transcript': text, **seen}, indent=2, ensure_ascii=False))
            print('\n' + text, flush=True)
            for label, reply in seen.items():
                print(f'\n{label}:\n{reply}', flush=True)
            self.assertIn('4 packets received', seen['PC1 -> PC2, initial tree'])
            self.assertIn('4 packets received', seen['PC1 -> PC2, over the redundant cable'])
            # The running bridge IDs are the ones a stopped lab already showed (fixed guest MACs).
            bridges = [t for t in transcript if 'Bridge ID' in t]
            nodes = {n['name']: n for n in spec['nodes']}
            for name in ('SW1', 'SW2'):
                self.assertTrue(any(f'Address     {guest_stp.bridge_mac(nodes[name])}' in t.split('Bridge ID')[-1]
                                    for t in bridges if t.startswith(name)), name)
            self.assertIn('This bridge is the root', next(t for t in transcript if t.startswith(f'{second}#show spanning-tree')
                                                          and 'Priority    24577' in t))
            pc1 = re.sub(r'(..):(..):(..):(..):(..):(..)', r'\1\2.\3\4.\5\6', guest_mac('PC1', 'eth0'))
            self.assertIn(pc1, next(t for t in transcript if 'show mac address-table' in t))
