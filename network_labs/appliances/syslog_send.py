"""One finite TCP submission plus a separate managed collector-log observation."""
import json
import re
import secrets
import sys
import time

from .runtime import RuntimeFailure
from .syslog_server import LOG, listen_address
from .verify import _endpoint

WORKER = '''import json,socket,sys
r=json.load(sys.stdin)
try:
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
        s.settimeout(3);s.bind((r['source'],0));s.connect((r['address'],514));s.sendall(r['frame'].encode('ascii'))
    print(json.dumps({'transmitted':True}))
except OSError as e:
    print(json.dumps({'transmitted':False,'detail':str(e)[:300]}))
'''


def frame(message):
    return str(len(message.encode('ascii'))) + ' ' + message


def send(manager, source, collector, message):
    """Caller holds the lab lock; TCP send completion is not a delivery verdict."""
    if not isinstance(message, str) or not re.fullmatch(r'[\x20-\x7e]{1,512}', message):
        raise ValueError('Syslog message requires 1..512 printable ASCII characters, without line breaks.')
    state = manager.read()
    if state['phase'] != 'running' or 'pending_spec' in state or 'pending_node' in state:
        raise RuntimeFailure('Syslog send requires a running lab without pending configuration.')
    if source == collector: raise ValueError('Choose two distinct managed hosts.')
    nodes = {n['name']: (i, n) for i, n in enumerate(state['spec']['nodes'])}
    for name in (source, collector):
        pair = nodes.get(name)
        if pair is None or pair[1]['runtime'] != 'oci' or pair[1]['role'] != 'host' or set(pair[1]['interfaces']) != {'eth0'}:
            raise ValueError('Syslog send requires two managed single-interface OCI hosts.')
    index, node = nodes[source]; _, server = nodes[collector]
    if (server.get('syslog_server') or {}).get('transport', 'udp') != 'tcp':
        raise ValueError('Destination must declare a managed TCP syslog collector.')
    endpoints = [_endpoint(manager, *nodes[name]) for name in (source, collector)]
    if any(e['status'] != 'ready' for e in endpoints):
        raise RuntimeFailure('Syslog source and collector require observed ready IPv4 endpoints.')
    address = listen_address(server)
    if address != endpoints[1]['address'] or address == endpoints[0]['address']:
        raise RuntimeFailure('Syslog collector address differs or endpoints are not distinct.')
    token = 'NLAB-' + secrets.token_hex(16)
    raw = '<133>1 - network-labs ' + source + ' - - - ' + token + ' ' + message
    expected = endpoints[0]['address'] + ' ' + raw
    report = {'lab': manager.name, 'source': source, 'collector': collector, 'transport': 'tcp',
              'framing': 'octet-counted', 'token': token, 'status': 'unknown', 'configuration_changed': False,
              'transmitted': False, 'collector_observed': False,
              'scope': 'Finite host-Python socket in the owned source netns; separate exact collector log observation. No TLS, authenticated sender, persistent forwarding, queue or application acknowledgement.'}
    result = manager.ns(index, sys.executable, '-I', '-c', WORKER,
                        input_text=json.dumps({'source': endpoints[0]['address'], 'address': address, 'frame': frame(raw)}), timeout=5)
    output = json.loads(result.stdout)
    report['transmitted'] = output['transmitted']
    if not output['transmitted']:
        report.update(status='failed', detail=output.get('detail', 'TCP submission failed')); return report
    until = time.monotonic() + 3
    while time.monotonic() < until:
        result = manager.crun('exec', collector, '/bin/busybox', 'tail', '-c', '8192', LOG, check=False, timeout=2)
        if result.returncode == 0 and expected in result.stdout.splitlines():
            report.update(status='passed', collector_observed=True, detail='Exact source address and fresh message observed in the collector log.'); return report
        time.sleep(.1)
    report['detail'] = 'TCP submission completed, but the exact message was not observed in the bounded collector log window; no delivery claim.'
    return report
