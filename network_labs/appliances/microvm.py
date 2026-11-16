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
