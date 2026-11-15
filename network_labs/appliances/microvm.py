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
