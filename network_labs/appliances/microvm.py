"""Reference micro-VM manifest, with a separate VMM and disk copy per node."""
from pathlib import Path
from .spec import validate


def example(kernel,disk,*,memory_mib=128,vcpus=1):
    """Read-only manifest generation; assets and guest boot are checked at start."""
    return validate({'version':1,'name':'microvm-pair','budget_mib':2048,'reserve_mib':512,
        'nodes':[{'name':name,'runtime':'firecracker','role':'host',
                  'kernel':str(Path(kernel).resolve()),'disk':str(Path(disk).resolve()),
                  'memory_mib':memory_mib,'vcpus':vcpus,'interfaces':{'eth0':address}}
                 for name,address in [('VM1','192.0.2.10/24'),('VM2','192.0.2.20/24')]],
        'links':[[['VM1','eth0'],['VM2','eth0']]]})


def multinic_example(kernel, disk):
    """One dual-interface host and two endpoints; no routing/bridging in the guest."""
    spec = example(kernel, disk)
    center = spec['nodes'][0]
    center['interfaces']['eth1'] = '198.51.100.10/24'
    right = dict(spec['nodes'][1])
    right['name'] = 'VM3'
    right['interfaces'] = {'eth0': '198.51.100.20/24'}
    spec['nodes'].append(right)
    spec['links'].append([['VM1', 'eth1'], ['VM3', 'eth0']])
    return validate(spec)


def router_example(kernel, disk):
    """R1 forwards IPv4 between two segments; VM2 and VM3 reach each other only through it."""
    spec = multinic_example(kernel, disk)
    spec['name'] = 'microvm-router'
    router, left, right = spec['nodes']
    router.update(name='R1', role='router', interfaces={'eth0': '192.0.2.1/24', 'eth1': '198.51.100.1/24'})
    left['gateway'] = '192.0.2.1'
    right['gateway'] = '198.51.100.1'
    spec['links'] = [[['R1', 'eth0'], ['VM2', 'eth0']], [['R1', 'eth1'], ['VM3', 'eth0']]]
    return validate(spec)


def router_chain_example(kernel, disk):
    """VM2 - R1 - R2 - VM3: each router holds one declared static route across the transit link."""
    spec = router_example(kernel, disk)
    spec['name'] = 'microvm-router-chain'
    first, left, right = spec['nodes']
    first['interfaces']['eth1'] = '203.0.113.1/30'
    first['guest_network'] = {'addresses': [], 'routes': [{'network': '198.51.100.0/24', 'gateway': '203.0.113.2'}]}
    second = dict(first, name='R2', interfaces={'eth0': '203.0.113.2/30', 'eth1': '198.51.100.1/24'},
                  guest_network={'addresses': [], 'routes': [{'network': '192.0.2.0/24', 'gateway': '203.0.113.1'}]})
    spec['nodes'] = [first, second, left, right]
    spec['links'] = [[['R1', 'eth0'], ['VM2', 'eth0']], [['R1', 'eth1'], ['R2', 'eth0']], [['R2', 'eth1'], ['VM3', 'eth0']]]
    return validate(spec)


def quad_router_example(kernel, disk):
    """R1 uses all four guest ports, eth0..eth3, each the gateway of one endpoint guest."""
    base = {'runtime': 'firecracker', 'kernel': str(Path(kernel).resolve()), 'disk': str(Path(disk).resolve()), 'memory_mib': 128, 'vcpus': 1}
    nets = ['192.0.2', '198.51.100', '203.0.113', '100.64.0']
    nodes = [dict(base, name='R1', role='router', interfaces={f'eth{i}': f'{net}.1/24' for i, net in enumerate(nets)})]
    nodes += [dict(base, name=f'VM{i + 1}', role='host', interfaces={'eth0': f'{net}.10/24'}, gateway=f'{net}.1') for i, net in enumerate(nets)]
    return validate({'version': 1, 'name': 'microvm-router-quad', 'budget_mib': 2048, 'reserve_mib': 512, 'nodes': nodes,
                     'links': [[['R1', f'eth{i}'], [f'VM{i + 1}', 'eth0']] for i in range(4)]})


def firewall_nat_example(kernel, disk):
    """FW1 hides the inside behind its outside address and publishes VM2's ICMP on that address."""
    spec = firewall_example(kernel, disk)
    spec['name'] = 'microvm-firewall-nat'
    policy = spec['nodes'][0]['firewall']
    policy['rules'].append({'name': 'published-ping-in', 'in': 'eth1', 'out': 'eth0', 'destination': '192.0.2.20/32', 'protocol': 'icmp', 'action': 'accept'})
    policy['nat'] = [{'name': 'hide-inside', 'type': 'masquerade', 'out': 'eth1', 'source': '192.0.2.0/24'},
                     {'name': 'publish-vm2', 'type': 'dnat', 'in': 'eth1', 'destination': '198.51.100.1/32', 'protocol': 'icmp', 'to': '192.0.2.20'}]
    return validate(spec)


def switch_example(kernel, disk):
    """SW1 bridges three endpoint guests into one segment; it holds no address and routes nothing."""
    base = {'runtime': 'firecracker', 'kernel': str(Path(kernel).resolve()), 'disk': str(Path(disk).resolve()), 'memory_mib': 128, 'vcpus': 1}
    nodes = [dict(base, name='SW1', role='switch', interfaces={f'eth{i}': '' for i in range(3)})]
    nodes += [dict(base, name=f'VM{i + 1}', role='host', interfaces={'eth0': f'192.0.2.{11 + i}/24'}) for i in range(3)]
    return validate({'version': 1, 'name': 'microvm-switch', 'budget_mib': 2048, 'reserve_mib': 512, 'nodes': nodes,
                     'links': [[['SW1', f'eth{i}'], [f'VM{i + 1}', 'eth0']] for i in range(3)]})


def firewall_example(kernel, disk):
    """FW1 lets the inside (VM2) ping out and keeps the outside (VM3) from starting anything inward."""
    spec = router_example(kernel, disk)
    spec['name'] = 'microvm-firewall'
    spec['nodes'][0].update(name='FW1', role='firewall', firewall={
        'default': 'drop', 'stateful': True,
        'rules': [{'name': 'inside-ping-out', 'in': 'eth0', 'out': 'eth1', 'source': '192.0.2.0/24', 'protocol': 'icmp', 'action': 'accept'}],
        'nat': []})
    spec['links'] = [[['FW1', 'eth0'], ['VM2', 'eth0']], [['FW1', 'eth1'], ['VM3', 'eth0']]]
    return validate(spec)
