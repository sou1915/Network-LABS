"""Explicit, bounded ICMP verification between two observed single-NIC OCI hosts."""
from datetime import datetime, timezone
import ipaddress
import json
import re
import subprocess

from .route_lookup import _json_read
from .runtime import RuntimeFailure
from .spec import integer


def _text(value):
    return (value.decode(errors='replace') if isinstance(value, bytes) else value or '')[:8192]


def _endpoint(manager, index, node):
    result = {'node': node['name'], 'interface': 'eth0', 'status': 'unknown', 'address': None,
              'dhcp_client_configured': 'eth0' in node['dhcp_clients'], 'reasons': [],
              'container': None, 'kernel': None}
    try:
        state = manager.crun('state', node['name'], check=False, timeout=3)
        if state.returncode:
            result['reasons'].append('CONTAINER_STATE_UNAVAILABLE'); return result
        container = json.loads(state.stdout)
        if not isinstance(container, dict) or not isinstance(container.get('status'), str):
            raise ValueError('Missing container status.')
        result['container'] = container['status']
        if container['status'] != 'running':
            result.update(status='blocked', reasons=['CONTAINER_NOT_RUNNING']); return result
        observed = _json_read(manager, index, 'ip', '-j', '-4', 'addr', 'show', 'dev', 'eth0')
        result['kernel'] = observed
        if observed['status'] != 'observed':
            result['reasons'].append('ADDRESS_READ_UNAVAILABLE'); return result
        records = observed['records']
        if len(records) != 1 or records[0].get('ifname') != 'eth0':
            result['reasons'].append('INTERFACE_NOT_OBSERVED'); return result
        row = records[0]; flags = row.get('flags')
        if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
            raise ValueError('Missing interface flags.')
        if 'UP' not in flags or 'LOWER_UP' not in flags:
            result.update(status='blocked', reasons=['INTERFACE_DOWN']); return result
        addresses = []
        for item in row.get('addr_info', []):
            if item.get('family') != 'inet' or item.get('scope') != 'global':
                continue
            prefix = integer(item.get('prefixlen'), 1, 32, 'Observed IPv4 prefix')
            interface = ipaddress.IPv4Interface(str(item.get('local')) + '/' + str(prefix))
            ip = interface.ip
            if (ip.is_unspecified or ip.is_loopback or ip.is_multicast or ip.is_reserved or
                    (prefix < 31 and ip in (interface.network.network_address, interface.network.broadcast_address))):
                continue
            addresses.append(str(ip))
        if not addresses:
            result.update(status='blocked', reasons=['NO_USABLE_IPV4']); return result
        if len(addresses) != 1:
            result['reasons'].append('AMBIGUOUS_IPV4'); return result
        result.update(status='ready', address=addresses[0])
    except (OSError, RuntimeFailure, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired) as error:
        result['reasons'].append('ENDPOINT_READ_UNAVAILABLE'); result['error'] = _text(str(error))
    return result


def _probe(manager, index, source, destination, count):
    address = destination['address']
    route = _json_read(manager, index, 'ip', '-j', '-4', 'route', 'get', address)
    command = ['/bin/ping', '-n', '-I', 'eth0', '-c', str(count), '-W', '1', '-w', str(count + 2), address]
    result = {'source': source['node'], 'destination': destination['node'], 'destination_address': address,
              'route': route, 'status': 'unknown', 'command': command, 'requested_packets': count,
              'transmitted': None, 'received': None, 'loss_percent': None, 'reply_ttls': [],
              'returncode': None, 'stdout': '', 'stderr': '', 'attempted': False}
    if route['status'] == 'observed' and any(row.get('type') == 'local' or row.get('dev') == 'lo' for row in route['records']):
        result.update(status='blocked', error='LOCAL_ROUTE_CANNOT_VERIFY_REMOTE_HOST'); return result
    try:
        result['attempted'] = True
        ping = manager.crun('exec', source['node'], *command, check=False, timeout=count + 5)
        result.update(returncode=ping.returncode, stdout=_text(ping.stdout), stderr=_text(ping.stderr))
        matches = re.findall(r'(\d+) packets transmitted,\s*(\d+) (?:packets )?received', result['stdout'])
        if len(matches) == 1:
            transmitted, received = map(int, matches[0])
            if 0 <= received <= transmitted <= count and transmitted > 0:
                result.update(transmitted=transmitted, received=received,
                              loss_percent=100 * (transmitted - received) / transmitted)
                if ping.returncode in (0, 1):
                    result['status'] = 'passed' if ping.returncode == 0 and transmitted == received == count else 'failed'
        result['reply_ttls'] = [int(ttl) for ttl in re.findall(r'\bttl=(\d+)\b', result['stdout'], re.I)
                               if 0 <= int(ttl) <= 255]
    except subprocess.TimeoutExpired as error:
        result.update(stdout=_text(error.stdout), stderr=_text(error.stderr), error='PING_TIMEOUT')
    except (OSError, RuntimeFailure) as error:
        result['error'] = _text(str(error))
    return result


def verify(manager, source, destination, *, count=3, bidirectional=False):
    """Caller holds the lab lock; ICMP updates counters/caches but not configuration."""
    integer(count, 1, 5, 'Verification packet count')
    if type(bidirectional) is not bool:
        raise ValueError('bidirectional must be boolean.')
    if not isinstance(source, str) or not isinstance(destination, str) or source == destination:
        raise ValueError('Select two different managed OCI hosts.')
    state = manager.read()
    if state['phase'] != 'running' or 'pending_spec' in state or 'pending_node' in state:
        raise RuntimeFailure('Verification requires a running lab without pending configuration.')
    selected = []
    for name in (source, destination):
        match = next(((i, n) for i, n in enumerate(state['spec']['nodes']) if n['name'] == name), None)
        if match is None or match[1]['runtime'] != 'oci' or match[1]['role'] != 'host' or set(match[1]['interfaces']) != {'eth0'}:
            raise ValueError('Verification supports managed OCI hosts with one physical eth0 interface.')
        if match[1].get('subinterfaces') or match[1].get('port_channels'):
            raise ValueError('Verification does not support subinterfaces or port channels on endpoints.')
        selected.append(match)
    report = {'lab': manager.name, 'started_at': datetime.now(timezone.utc).isoformat(),
              'revision': state.get('revision', 0), 'status': 'unknown', 'directions': [],
              'endpoints': [_endpoint(manager, i, n) for i, n in selected],
              'scope': 'Explicit ICMP test between observed host addresses. No inferred topology path, DHCP lease provenance, VLAN isolation, OSPF convergence or application-service verdict.',
              'configuration_changed': False, 'probe_commands_attempted': 0}
    a, b = report['endpoints']
    if a['status'] == b['status'] == 'ready' and a['address'] == b['address']:
        for endpoint in (a, b):
            endpoint.update(status='blocked', reasons=['DUPLICATE_ENDPOINT_IPV4'])
    if any(endpoint['status'] != 'ready' for endpoint in (a, b)):
        report['status'] = 'unknown' if any(endpoint['status'] == 'unknown' for endpoint in (a, b)) else 'blocked'
    else:
        pairs = [(selected[0][0], a, b)] + ([(selected[1][0], b, a)] if bidirectional else [])
        for index, sender, receiver in pairs:
            report['directions'].append(_probe(manager, index, sender, receiver, count))
            report['probe_commands_attempted'] += int(report['directions'][-1]['attempted'])
        states = [direction['status'] for direction in report['directions']]
        report['status'] = 'passed' if all(value == 'passed' for value in states) else ('failed' if 'failed' in states else ('unknown' if 'unknown' in states else 'blocked'))
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    return report


def render(report):
    labels = {'passed': 'RÉUSSI', 'failed': 'ÉCHEC', 'blocked': 'BLOQUÉ', 'unknown': 'INCONNU'}
    lines = [f"Vérification ICMP : {labels[report['status']]} — {report['lab']}"]
    for endpoint in report['endpoints']:
        messages = {'CONTAINER_NOT_RUNNING': 'conteneur arrêté', 'CONTAINER_STATE_UNAVAILABLE': 'état conteneur indisponible',
                    'ADDRESS_READ_UNAVAILABLE': 'lecture adresse indisponible', 'INTERFACE_NOT_OBSERVED': 'interface non observée',
                    'INTERFACE_DOWN': 'interface sans état UP/LOWER_UP', 'NO_USABLE_IPV4': 'aucune IPv4 utilisable observée',
                    'AMBIGUOUS_IPV4': 'plusieurs adresses IPv4 ; sélection ambiguë',
                    'ENDPOINT_READ_UNAVAILABLE': 'observation incomplète', 'DUPLICATE_ENDPOINT_IPV4': 'même IPv4 sur les deux endpoints'}
        reasons = ', '.join(messages[reason] for reason in endpoint['reasons']) or 'IPv4 et interface observées'
        lines.append(f"{endpoint['node']}/eth0 : {endpoint['address'] or '?'} ; {reasons}.")
    for direction in report['directions']:
        display = lambda key: str(direction[key]) if direction[key] is not None else '?'
        lines.append(f"{direction['source']} → {direction['destination']} ({direction['destination_address']}) : "
                     f"{labels[direction['status']]} ; reçus/envoyés={display('received')}/{display('transmitted')}, perte={display('loss_percent')}%.")
        lines.append('  Lecture route kernel : ' + direction['route']['status'] + ' ; ' +
                     json.dumps(direction['route']['records'], ensure_ascii=False))
        if direction['stderr'] or direction.get('error'):
            lines.append('  Détail : ' + (direction.get('error') or direction['stderr']))
    lines.append('Un résultat positif couvre les sondes ICMP exécutées. Il ne valide pas tous les protocoles ni la cause précise d’un échec.')
    return '\n'.join(lines)
