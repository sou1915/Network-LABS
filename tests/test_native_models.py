"""Vendor models on native nodes: catalogue, validation, draft helpers and the GUI bridge."""
import unittest

from network_labs.appliances import native_models
from network_labs.appliances.spec import validate
from network_labs.appliances.topology_edit import add_microvm_node, add_node
from network_labs.appliances.ui_bridge import public_topology, validate_topology


def first(role):
    return next(m for m in native_models.MODELS.values() if m['role'] == role)


def empty():
    return {'version': 1, 'name': 'vendor', 'budget_mib': 2048, 'reserve_mib': 512, 'nodes': [], 'links': []}


class CatalogueTest(unittest.TestCase):
    def test_many_brands_in_every_native_role(self):
        models = native_models.MODELS.values()
        self.assertGreaterEqual(len(native_models.MODELS), 30)
        for role in ('router', 'switch', 'firewall', 'host'):
            brands = {m['brand'] for m in models if m['role'] == role}
            self.assertGreaterEqual(len(brands), 3, role)
        self.assertNotIn('Générique', {m['brand'] for m in models})

    def test_library_groups_cover_every_model_once(self):
        listed = [m['id'] for _, entries in native_models.grouped() for m in entries]
        self.assertEqual(sorted(listed), sorted(native_models.MODELS))

    def test_labels_and_short_names(self):
        switch = first('switch')
        node = {'name': 'SW1', 'role': 'switch', 'model': switch['id']}
        self.assertTrue(native_models.label(node).startswith(switch['brand'] + ' · '))
        self.assertNotIn(' · ', native_models.label(node, short=True)[len(switch['brand']) + 3:])
        self.assertEqual(native_models.label({'name': 'R', 'role': 'router'}), 'Routeur Linux')

    def test_default_ports_respect_the_runtime(self):
        router, host = first('router'), first('host')
        self.assertEqual(native_models.default_ports(host['id'], 'oci'), 1)
        self.assertLessEqual(native_models.default_ports(router['id'], 'firecracker'), native_models.MICROVM_PORTS)
        self.assertGreaterEqual(native_models.default_ports(router['id'], 'firecracker'), 2)

    def test_unknown_or_mismatched_model_is_refused(self):
        with self.assertRaises(ValueError):
            native_models.validate({'name': 'X', 'role': 'host', 'model': 'no-such-model'})
        with self.assertRaisesRegex(ValueError, 'pas host'):
            native_models.validate({'name': 'X', 'role': 'host', 'model': first('router')['id']})


class DraftTest(unittest.TestCase):
    def test_container_node_takes_model_port_aliases(self):
        router = first('router')
        lab = add_node(empty(), name='R1', role='router', rootfs='/rootfs', ports=2, model=router['id'])
        node = lab['nodes'][0]
        self.assertEqual(node['model'], router['id'])
        self.assertEqual(node['interface_aliases'], {router['ports'][0]: 'eth0', router['ports'][1]: 'eth1'})

    def test_micro_vm_node_keeps_eth_names(self):
        firewall = first('firewall')
        lab = add_microvm_node(empty(), name='FW1', role='firewall', kernel='/k', disk='/d', ports=2,
                               addresses='10.0.0.1/24,10.0.1.1/24', model=firewall['id'])
        node = lab['nodes'][0]
        self.assertEqual(node['model'], firewall['id'])
        self.assertEqual(node['interface_aliases'], {})

    def test_lab_validation_refuses_a_wrong_model(self):
        lab = add_microvm_node(empty(), name='H1', role='host', kernel='/k', disk='/d', addresses='10.0.0.2/24')
        lab['nodes'][0]['model'] = first('switch')['id']
        with self.assertRaises(ValueError):
            validate(lab)

    def test_bridge_exposes_and_accepts_the_model(self):
        host = first('host')
        lab = add_microvm_node(empty(), name='H1', role='host', kernel='/k', disk='/d', addresses='10.0.0.2/24',
                               model=host['id'])
        graph = public_topology(lab)
        self.assertEqual(graph['nodes'][0]['model'], host['id'])
        validate_topology(graph)


if __name__ == '__main__':
    unittest.main()
