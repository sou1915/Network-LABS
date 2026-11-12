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
