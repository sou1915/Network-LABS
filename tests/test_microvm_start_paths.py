"""Every micro-VM reference lab through the real Manager.start, with host commands recorded instead of run.

Container-only code reached for a micro-VM node (a crun call, a container file, a container
service starter) fails here, before a real-KVM run would. Guest startup itself is replaced:
it has its own unit tests and real-KVM acceptance.
"""
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from network_labs.appliances import microvm, runtime

EXAMPLES = sorted(name for name, function in inspect.getmembers(microvm, inspect.isfunction)
                  if name.endswith('example') and list(inspect.signature(function).parameters)[:2] == ['kernel', 'disk'])


class MicroVMStartPathTests(unittest.TestCase):
    def test_reference_labs_start_and_stop_without_container_code(self):
        self.assertGreaterEqual(len(EXAMPLES), 8, EXAMPLES)
        for name in EXAMPLES:
            with self.subTest(example=name), tempfile.TemporaryDirectory() as root:
                spec = getattr(microvm, name)('/kernel', '/disk')
                commands = []
                def record(argv, **options):
                    commands.append([str(a) for a in argv])
                    return type('Result', (), {'returncode': 1 if argv[:2] == ['ip', 'link'] else 0, 'stdout': '', 'stderr': ''})()
                def started(manager, node, index):
                    manager.state['vms'].append({'name': node['name'], 'pid': 1, 'starttime': None, 'jailed': False})
                    manager.save()
                with patch.object(runtime, 'STATE_ROOT', Path(root)), patch.object(runtime, 'run', side_effect=record), \
                     patch.object(runtime.Manager, 'preflight'), patch.object(runtime, 'jailer_path', return_value=None), \
                     patch.object(runtime.Manager, 'crun', side_effect=AssertionError('crun called for a micro-VM lab')), \
                     patch.object(runtime.Manager, 'start_vm', autospec=True, side_effect=started) as start_vm:
                    manager = runtime.Manager(spec['name'])
                    manager.start(spec)
                    self.assertEqual([c.args[1]['name'] for c in start_vm.call_args_list], [n['name'] for n in spec['nodes']])
                    state = json.loads((manager.directory / 'state.json').read_text())
                    self.assertEqual(state['phase'], 'running', name)
                    self.assertEqual(state['containers'], [])
                    self.assertFalse([c for c in commands if 'crun' in c[0]], name)
