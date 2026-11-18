"""Real router guest: two endpoint guests reach each other only through its forwarding."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
from network_labs.appliances.guest_image import build
from network_labs.appliances.guest_control import request
from network_labs.appliances.guest_startup import save_observed, observe, query
from network_labs.appliances.microvm import router_example
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, process_identity


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class RouterGuestTests(unittest.TestCase):
    def test_forwarding_between_segments_loss_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'router'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlrt-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = router_example(kernel, root / 'base.ext4')
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name']); records = []; results = {'probes': []}
                with manager.locked():
                    try:
                        manager.start(spec); records.extend(manager.state['vms'])
                        sockets = {n['name']: manager.directory / n['name'] / 'guest.vsock' for n in spec['nodes']}

                        def probe(name, destination, expected, attempts=1):
                            # The first packet across a fresh path can be spent on ARP; retries are only allowed where stated.
                            for _ in range(attempts):
                                result = request(sockets[name], 'ping', destination=destination)
                                if (result['exit_code'] == 0) == expected: break
                            results['probes'].append({'source': name, 'destination': destination, 'expected': expected, **result})
                            self.assertEqual(result['exit_code'] == 0, expected, result)
                            return result

                        def wait_ready():
                            for name in ('VM2', 'VM3'):
                                deadline = time.monotonic() + 40
                                while True:
                                    try: query(sockets[name], 'ready'); break
                                    except (ValueError, OSError):
                                        if time.monotonic() >= deadline: raise
                                        time.sleep(.1)

                        wait_ready()
                        self.assertEqual(query(sockets['R1'], 'forwarding').strip(), '1')
                        self.assertEqual(query(sockets['VM2'], 'forwarding').strip(), '0')
                        results['router_routes'] = query(sockets['R1'], 'routes')
                        results['endpoint_routes'] = query(sockets['VM2'], 'routes')
                        self.assertIn('default via 192.0.2.1', results['endpoint_routes'])
                        # Each endpoint first reaches its own gateway, then the far segment through the router.
                        probe('VM2', '192.0.2.1', True, attempts=3); probe('VM3', '198.51.100.1', True, attempts=3)
                        forward = probe('VM2', '198.51.100.20', True, attempts=3); probe('VM3', '192.0.2.20', True, attempts=3)
                        direct = probe('VM2', '192.0.2.1', True)
                        # One routed hop costs exactly one TTL relative to the directly connected gateway.
                        ttl = lambda result: int(result['output'].split('ttl=')[1].split()[0])
                        self.assertEqual(ttl(forward), ttl(direct) - 1, (forward, direct)); results['ttl'] = {'direct': ttl(direct), 'routed': ttl(forward)}
                        # Negative control: the same lab without forwarding does not pass traffic, gateways stay reachable.
                        query(sockets['R1'], 'forward', state='off')
                        probe('VM2', '198.51.100.20', False); probe('VM3', '192.0.2.20', False)
                        probe('VM2', '192.0.2.1', True); probe('VM3', '198.51.100.1', True)
                        with self.assertRaisesRegex(ValueError, 'not forwarding'): save_observed(manager)
                        query(sockets['R1'], 'forward', state='on')
                        probe('VM2', '198.51.100.20', True, attempts=3)
                        # Losing the far-side port breaks only the routed path.
                        query(sockets['R1'], 'link', interface='eth1', state='down')
                        probe('VM2', '198.51.100.20', False); probe('VM2', '192.0.2.1', True)
                        query(sockets['R1'], 'link', interface='eth1', state='up')
                        probe('VM2', '198.51.100.20', True, attempts=5)
                        results['saved'] = save_observed(manager)
                        restored = load_startup(manager.name)
                        self.assertEqual(restored['nodes'][0]['role'], 'router')
                        for name in sockets: shutil.copyfile(manager.directory / name / 'console.log', evidence / (name + '-before-restart.log'))
                        manager.stop()
                        for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                        manager = Manager(spec['name']); manager.start(restored); records.extend(manager.state['vms'])
                        wait_ready()
                        results['restored_profiles'] = {n['name']: observe(sockets[n['name']], n) for n in restored['nodes']}
                        self.assertEqual(query(sockets['R1'], 'forwarding').strip(), '1')
                        probe('VM2', '198.51.100.20', True, attempts=3); probe('VM3', '192.0.2.20', True, attempts=3)
                        results['cold_restore_passed'] = True
                        (evidence / 'result.json').write_text(json.dumps(results, indent=2))
                    finally:
                        for name in ('R1', 'VM2', 'VM3'):
                            console = manager.directory / name / 'console.log'
                            if console.exists(): shutil.copyfile(console, evidence / (name + '.log'))
                        if manager.directory.exists(): manager.stop()
                for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                self.assertFalse(manager.directory.exists())
                (evidence / 'cleanup.txt').write_text('All owned VMMs and private lab resources removed.\n')

    def test_two_router_chain_static_routes_withdrawal_and_restore(self):
        from network_labs.appliances.microvm import router_chain_example
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'router-chain'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlrc-') as temporary:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = router_chain_example(kernel, root / 'base.ext4')
            names = [n['name'] for n in spec['nodes']]
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name']); records = []; results = {'probes': []}
                with manager.locked():
                    try:
                        manager.start(spec); records.extend(manager.state['vms'])
                        sockets = {name: manager.directory / name / 'guest.vsock' for name in names}

                        def probe(name, destination, expected, attempts=1):
                            for _ in range(attempts):
                                result = request(sockets[name], 'ping', destination=destination)
                                if (result['exit_code'] == 0) == expected: break
                            results['probes'].append({'source': name, 'destination': destination, 'expected': expected, **result})
                            self.assertEqual(result['exit_code'] == 0, expected, result)
                            return result

                        def wait_ready():
                            for name in ('VM2', 'VM3'):
                                deadline = time.monotonic() + 40
                                while True:
                                    try: query(sockets[name], 'ready'); break
                                    except (ValueError, OSError):
                                        if time.monotonic() >= deadline: raise
                                        time.sleep(.1)

                        wait_ready()
                        results['routes'] = {name: query(sockets[name], 'routes') for name in ('R1', 'R2')}
                        # The declared transit routes were installed by startup, R1's through its second port.
                        self.assertIn('198.51.100.0/24 via 203.0.113.2 dev eth1', results['routes']['R1'])
                        self.assertIn('192.0.2.0/24 via 203.0.113.1 dev eth0', results['routes']['R2'])
                        # Vendor 'show' commands read the running guests: R1 as a Cisco ISR, R2 as a Juniper MX.
                        from network_labs.appliances.vendor_show import show
                        r1, r2 = (dict(n, model=m) for n, m in zip(spec['nodes'][:2], ('cisco-isr4331', 'juniper-mx204')))
                        results['show'] = {'R1# show ip route': show(r1, manager.observe_node('R1'), 'show ip route'),
                                           'R2> show route': show(r2, manager.observe_node('R2'), 'show route')}
                        table = results['show']['R1# show ip route']
                        self.assertIn('S        198.51.100.0/24 [1/0] via 203.0.113.2, GigabitEthernet0/0/1', table)
                        self.assertIn('C        192.0.2.0/24 is directly connected, GigabitEthernet0/0/0', table)
                        self.assertIn('192.0.2.0/24       *[Static/5]', results['show']['R2> show route'])
                        direct = probe('VM2', '192.0.2.1', True, attempts=3)
                        routed = probe('VM2', '198.51.100.20', True, attempts=5); probe('VM3', '192.0.2.20', True, attempts=5)
                        ttl = lambda result: int(result['output'].split('ttl=')[1].split()[0])
                        # Two routers on the return path cost exactly two TTLs.
                        self.assertEqual(ttl(routed), ttl(direct) - 2, (routed, direct)); results['ttl'] = {'direct': ttl(direct), 'routed': ttl(routed)}
                        # A vendor ping sends real echo requests from R1's guest across R2 to VM3
                        # (after the probes above, so ARP on the path is already resolved).
                        from network_labs.appliances.vendor_show import ping_text
                        results['show']['R1# ping 198.51.100.20'] = ping_text(r1, manager.ping_node('R1', '198.51.100.20'))
                        self.assertIn('Success rate is 100 percent (5/5)', results['show']['R1# ping 198.51.100.20'])
                        for prompt, text in results['show'].items():
                            print(f'\n{prompt}\n{text}', flush=True)
                        # Withdrawing R1's route through eth1 breaks the far segment only; a save then records its absence.
                        query(sockets['R1'], 'route-delete', network='198.51.100.0/24', gateway='203.0.113.2', interface='eth1')
                        probe('VM2', '198.51.100.20', False); probe('VM2', '192.0.2.1', True)
                        query(sockets['R1'], 'route-add', network='198.51.100.0/24', gateway='203.0.113.2', interface='eth1')
                        probe('VM2', '198.51.100.20', True, attempts=3)
                        results['saved'] = save_observed(manager)
                        restored = load_startup(manager.name)
                        self.assertEqual(restored['nodes'][0]['guest_network']['routes'], [{'network': '198.51.100.0/24', 'gateway': '203.0.113.2'}])
                        for name in names: shutil.copyfile(manager.directory / name / 'console.log', evidence / (name + '-before-restart.log'))
                        manager.stop()
                        for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                        manager = Manager(spec['name']); manager.start(restored); records.extend(manager.state['vms'])
                        wait_ready()
                        results['restored_profiles'] = {n['name']: observe(sockets[n['name']], n) for n in restored['nodes']}
                        probe('VM2', '198.51.100.20', True, attempts=5); probe('VM3', '192.0.2.20', True, attempts=5)
                        results['cold_restore_passed'] = True
                        (evidence / 'result.json').write_text(json.dumps(results, indent=2))
                    finally:
                        for name in names:
                            console = manager.directory / name / 'console.log'
                            if console.exists(): shutil.copyfile(console, evidence / (name + '.log'))
                        if manager.directory.exists(): manager.stop()
                for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                self.assertFalse(manager.directory.exists())
                (evidence / 'cleanup.txt').write_text('All owned VMMs and private lab resources removed.\n')


    def test_capture_usage_and_kernel_report_on_a_running_router(self):
        """Operations that must not hold the lab lock: capture a routed ping on the router's far port."""
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from network_labs.appliances.capture import capture
        self.assertEqual(os.geteuid(), 0)
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'router-capture'
        evidence.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlcp-') as temporary, ThreadPoolExecutor(max_workers=1) as pool:
            root = Path(temporary)
            build(shutil.which('busybox'), root / 'base.ext4', with_agent=True)
            spec = router_example(kernel, root / 'base.ext4')
            with patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state'), patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                manager = Manager(spec['name']); records = []; results = {}
                with manager.locked():
                    manager.start(spec); records.extend(manager.state['vms'])
                try:
                    sockets = {n['name']: manager.directory / n['name'] / 'guest.vsock' for n in spec['nodes']}
                    for name in ('VM2', 'VM3'):
                        deadline = time.monotonic() + 40
                        while True:
                            try: query(sockets[name], 'ready'); break
                            except (ValueError, OSError):
                                if time.monotonic() >= deadline: raise
                                time.sleep(.1)
                    results['kernel'] = dict(line.split('=') for line in query(sockets['R1'], 'kernel').splitlines())
                    print('GUEST_KERNEL_CAPABILITIES ' + json.dumps(results['kernel'], sort_keys=True), flush=True)
                    self.assertEqual(sorted(results['kernel']), ['bridge', 'conntrack', 'iptables', 'ipv6_forwarding', 'nftables', 'vlan'])
                    # Resolve neighbours first so the capture sees exactly one request and one reply.
                    deadline = time.monotonic() + 15
                    while request(sockets['VM2'], 'ping', destination='198.51.100.20')['exit_code'] and time.monotonic() < deadline: time.sleep(.2)
                    ready = threading.Event(); path = root / 'routed.pcap'
                    future = pool.submit(capture, Manager(spec['name']), 'R1', 'eth1', path, seconds=10, packets=2, expression='icmp', ready=ready.set)
                    self.assertTrue(ready.wait(8), 'Guest capture did not become ready')
                    self.assertEqual(request(sockets['VM2'], 'ping', destination='198.51.100.20')['exit_code'], 0)
                    report = future.result(timeout=15); results['capture'] = report
                    self.assertEqual((report['captured_packets'], report['stop_reason']), (2, 'completed'), report)
                    self.assertIn('tap1', report['source'])
                    with self.assertRaises(ValueError): capture(Manager(spec['name']), 'R1', 'eth2', root / 'no.pcap', seconds=1, packets=1)
                    with manager.locked():
                        manager.state = None
                        status = {n['name']: n for n in manager.status()['nodes']}
                    results['status'] = status
                    for name, node in status.items():
                        self.assertTrue(node['vmm_alive'], node)
                        self.assertGreater(node['vmm_memory_bytes'], 8 * 1024 * 1024, node); self.assertGreaterEqual(node['vmm_cpu_seconds'], 0, node)
                        self.assertEqual(node['vmm_memory_source'], 'cgroup' if node['vmm_jailed'] and records[0].get('cgroup') else 'process resident set', node)
                    (evidence / 'result.json').write_text(json.dumps(results, indent=2))
                    shutil.copyfile(path, evidence / 'routed.pcap')
                finally:
                    with manager.locked():
                        manager.state = None
                        if manager.directory.exists(): manager.stop()
                for record in records: self.assertNotEqual(process_identity(record['pid']), record['starttime'])
                self.assertFalse(manager.directory.exists())
