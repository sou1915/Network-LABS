"""Generated scenarios on real guests: what every ping really does matches the network model, broken and repaired."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from network_labs.appliances import missions, scenarios
from network_labs.appliances.guest_image import build
from network_labs.appliances.network_model import Model
from network_labs.appliances.runtime import Manager

from tests.test_native_microvm_missions import wait_ready


def picks(vlan):
    """One catalogue scenario per family this kernel can run (VLAN campuses need 802.1Q)."""
    wanted = {'campus': None} if vlan else {'chaine': 'ospf', 'etoile': 'statique', 'sortie': None}
    found = {}
    for number in range(1, scenarios.COUNT + 1):
        item = scenarios.scenario(number)
        family = item['family']
        if family in wanted and family not in found and (wanted[family] is None or wanted[family] in item['detail']):
            found[family] = number
        if len(found) == len(wanted):
            return sorted(found.values())
    raise AssertionError(f'no scenario for {set(wanted) - set(found)}')


def real_outcome(manager, item, expected_model, deadline):
    """[answered?] per probe, retried until it matches the model or DEADLINE (OSPF converges after boot)."""
    probes = missions.encode_probes(scenarios.checks_for(item))
    while True:
        results = missions.run_real(manager, item['id'], probes)['results']
        answered = [ok == expect for (_, ok, _), expect in zip(results, item['expected'])]
        if answered == expected_model or time.monotonic() >= deadline:
            return answered
        time.sleep(1)


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class ScenarioGuestTests(unittest.TestCase):
    def test_generated_scenarios_behave_on_real_guests_as_the_model_says(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel = Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        vlan = os.environ.get('NETWORK_LABS_GUEST_VLAN') == '1'
        evidence = Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE', '/tmp/network-labs-microvm-evidence')) / 'scenarios'
        evidence.mkdir(parents=True, exist_ok=True)
        report = {}
        with tempfile.TemporaryDirectory(prefix='nlscn-') as temporary:
            root = Path(temporary)
            disk = root / 'full.ext4'
            build(shutil.which('busybox'), disk, size_mib=128, with_agent=True, with_firewall=True, with_routing=True)
            state_root = patch('network_labs.appliances.runtime.STATE_ROOT', root / 'state')
            with state_root, patch('network_labs.appliances.runtime.CONFIG_ROOT', root / 'config'):
                for number in picks(vlan):
                    item = scenarios.scenario(number, kernel, disk)
                    for label, spec in (('broken', item['spec']), ('repaired', item['original'])):
                        model = [ok for ok, _ in Model(spec).ping_all(item['probes'])]
                        manager = Manager(spec['name'])
                        with manager.locked():
                            try:
                                manager.start(spec)
                                wait_ready(manager, spec)
                                real = real_outcome(manager, item, model, time.monotonic() + 45)
                            finally:
                                if manager.directory.exists():
                                    manager.stop()
                        report[f'{item["id"]} {label}'] = {'family': item['family'], 'detail': item['detail'],
                                                           'fault': item['fault']['answer'], 'model': model, 'real': real}
                        print(f'\nScenario {number} ({item["detail"]}) {label}: model {model} real {real}', flush=True)
        (evidence / 'result.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
        for key, row in report.items():
            with self.subTest(scenario=key):
                self.assertEqual(row['real'], row['model'], row)
                if key.endswith('repaired'):
                    self.assertEqual(row['real'], scenarios.scenario(int(key.split()[0].split('-')[1]))['expected'])
