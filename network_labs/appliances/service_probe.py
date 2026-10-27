"""Layered, bounded DNS/TCP/HTTP observations from a managed OCI host."""
from datetime import datetime, timezone
import ipaddress
import hashlib
import json
from pathlib import Path
import re
import subprocess
import ssl
import sys

from .runtime import RuntimeFailure
from .spec import integer
from .verify import _endpoint
from .route_lookup import _json_read


def unicast(value):
    address = ipaddress.IPv4Address(value)
    if address.is_unspecified or address.is_multicast or address.is_loopback or address.is_reserved:
        raise ValueError('Expected a remote unicast IPv4 address.')
    return str(address)


def load_ca(path):
    with Path(path).open('rb') as source:
        data = source.read(65537)
    if len(data) > 65536:
        raise ValueError('CA bundle exceeds 64 KiB.')
    return data.decode('ascii')


def probe(manager, source, target, *, protocol='http', port=None, path='/', timeout=3, ca_pem=None):
    """Caller holds lab lock. Sequential probes are evidence, not root-cause proof."""
    if protocol not in ('dns', 'tcp', 'http', 'https', 'sntp'):
        raise ValueError('Choose dns, tcp, http, https or sntp.')
    if protocol == 'https':
        if not isinstance(ca_pem, str) or len(ca_pem.encode('utf-8')) > 65536 or 'PRIVATE KEY' in ca_pem:
            raise ValueError('HTTPS requires an explicit PEM CA bundle of at most 64 KiB, without private keys.')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=ca_pem)
    elif ca_pem is not None:
        raise ValueError('A CA bundle is only supported with HTTPS.')
    integer(timeout, 1, 5, 'Probe timeout')
    if port is not None:
        integer(port, 1, 65535, 'Destination port')
    if protocol == 'dns' and port is not None:
        raise ValueError('DNS uses UDP port 53; omit --port.')
    if protocol == 'sntp' and port is not None:
        raise ValueError('SNTP uses UDP port 123; omit --port.')
    if protocol == 'tcp' and port is None:
        raise ValueError('TCP requires an explicit --port.')
    if not isinstance(path, str) or not re.fullmatch(r'/[!-~]{0,1023}', path) or '#' in path:
        raise ValueError('Use an ASCII HTTP path beginning with /; percent-encode spaces and Unicode.')
    if protocol not in ('http', 'https') and path != '/':
        raise ValueError('--path is only supported for HTTP/HTTPS.')
    if not isinstance(target, str):
        raise ValueError('Expected an IPv4 address or DNS name, not a URL.')
    try:
        ipaddress.IPv4Address(target)
    except ValueError:
        address = None
        target = target.rstrip('.').lower()
        if len(target) > 253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+', target) or re.fullmatch(r'[0-9.]+', target):
            raise ValueError('Use an IPv4 literal or a fully qualified ASCII DNS name.')
    else:
        address = unicast(target)
        if protocol == 'dns':
            raise ValueError('DNS A probe requires a DNS name.')
    state = manager.read()
    if state['phase'] != 'running' or 'pending_spec' in state or 'pending_node' in state:
        raise RuntimeFailure('Probe requires a running lab without pending configuration.')
    match = next(((i, n) for i, n in enumerate(state['spec']['nodes']) if n['name'] == source), None)
    if match is None or match[1]['runtime'] != 'oci' or match[1]['role'] != 'host' or set(match[1]['interfaces']) != {'eth0'} or match[1].get('subinterfaces') or match[1].get('port_channels'):
        raise ValueError('Probe supports a managed OCI host with one physical eth0.')
    index, node = match
    endpoint = _endpoint(manager, index, node)
    report = {'lab': manager.name, 'node': source, 'revision': state.get('revision', 0),
              'started_at': datetime.now(timezone.utc).isoformat(), 'target': target, 'protocol': protocol,
              'port': port or (53 if protocol == 'dns' else 123 if protocol == 'sntp' else 443 if protocol == 'https' else 80), 'path': path if protocol in ('http', 'https') else None,
              'endpoint': endpoint, 'stages': [], 'status': endpoint['status'], 'configuration_changed': False,
              'scope': 'Host Python sockets in the owned network namespace, bound to observed source IPv4. DNS uses exactly one guest IPv4 resolver, direct A over UDP; no search list, CNAME following, fallback or host resolver. TCP connect and HTTP(S) HEAD are separate connections. HTTP 2xx only; no redirects or body validation. HTTPS uses only the explicit CA bundle and verifies the target hostname/IP; no guest/host default CA fallback, revocation checking or mutual TLS. SNTP never sets clocks. Failures do not prove a routing/firewall/service root cause.'}
    def finish(status):
        report.update(status=status, finished_at=datetime.now(timezone.utc).isoformat())
        from .service_findings import findings
        report['findings'] = findings(report)
        return report
    if endpoint['status'] != 'ready':
        return finish(endpoint['status'])
    worker = Path(__file__).with_name('service_probe_worker.py').read_text()
    def execute(stage, **kwargs):
        request = dict(stage=stage, target=target, source=endpoint['address'], timeout=timeout, **kwargs)
        try:
            process = manager.ns(index, sys.executable, '-I', '-c', worker, json.dumps(request), check=False, timeout=timeout + 2)
            value = json.loads(process.stdout)
            if process.returncode or not isinstance(value, dict) or value.get('stage') != stage or value.get('status') not in ('passed', 'failed', 'unknown'):
                raise ValueError('Probe worker output unavailable')
            if stage == 'https' and value['status'] == 'passed' and value.get('certificate_verified') is not True:
                raise ValueError('HTTPS success lacks verified certificate evidence')
        except (OSError, RuntimeFailure, ValueError, subprocess.TimeoutExpired) as error:
            value = {'stage': stage, 'status': 'unknown', 'error': str(error)[:300]}
        value['request'] = {k: v for k, v in request.items() if k != 'ca_pem'}
        if 'ca_pem' in request:
            value['request']['ca_sha256'] = hashlib.sha256(request['ca_pem'].encode('utf-8')).hexdigest()
        report['stages'].append(value)
        return value
    if address is None:
        try:
            resolver = manager.crun('exec', source, '/bin/cat', '/etc/resolv.conf', check=False, timeout=3)
            if resolver.returncode or len(resolver.stdout) > 8192:
                raise ValueError('Guest resolver file unavailable')
            servers = [line.split('#', 1)[0].split() for line in resolver.stdout.splitlines()]
            servers = [row for row in servers if row and row[0] == 'nameserver']
            if len(servers) != 1 or len(servers[0]) != 2:
                raise ValueError('Exactly one guest IPv4 nameserver is required')
            server = unicast(servers[0][1])
        except (OSError, RuntimeFailure, ValueError, subprocess.TimeoutExpired) as error:
            report['stages'].append({'stage': 'dns', 'status': 'unknown', 'error': str(error)[:300]})
            return finish('unknown')
        dns = execute('dns', server=server)
        if dns['status'] != 'passed' or protocol == 'dns':
            return finish(dns['status'])
        try:
            addresses = dns.get('addresses', [])
            if len(addresses) != 1:
                raise ValueError('Multiple DNS addresses; no implicit target selection')
            address = unicast(addresses[0])
        except (ValueError, TypeError) as error:
            report['stages'].append({'stage': 'target', 'status': 'blocked', 'error': str(error)})
            return finish('blocked')
    route = _json_read(manager, index, 'ip', '-j', '-4', 'route', 'get', address)
    report.update(address=address, route=route)
    if address == endpoint['address'] or any(row.get('type') in ('local', 'broadcast', 'multicast') or row.get('dev') == 'lo' for row in route['records'] or []):
        report['stages'].append({'stage': 'target', 'status': 'blocked', 'error': 'Remote target required'})
        return finish('blocked')
    if protocol == 'sntp':
        return finish(execute('sntp', address=address)['status'])
    tcp = execute('tcp', address=address, port=report['port'])
    if tcp['status'] != 'passed' or protocol == 'tcp':
        return finish(tcp['status'])
    extra = {'ca_pem': ca_pem} if protocol == 'https' else {}
    return finish(execute(protocol, address=address, port=report['port'], path=path, **extra)['status'])


def render(report):
    labels = {'passed': 'RÉUSSI', 'failed': 'ÉCHEC', 'unknown': 'INCONNU', 'blocked': 'BLOQUÉ'}
    safe = lambda value: json.dumps(value, ensure_ascii=True)
    lines = [f"Sonde {report['protocol'].upper()} : {labels[report['status']]} | {report['lab']}/{report['node']}",
             'Cible : ' + safe(report['target'])]
    from .service_findings import findings
    for finding in findings(report):
        lines.append('[' + labels[finding['status']] + '] ' + finding['message'])
        if finding['next_step']:
            lines.append('  À vérifier / limite : ' + finding['next_step'])
    for stage in report['stages']:
        if stage['stage'] == 'sntp' and stage['status'] == 'passed':
            lines.append(f"  Décalage estimé : {stage['offset_seconds']:+.6f} s ; délai calculé : {stage['round_trip_seconds']:.6f} s ; stratum : {stage['stratum']}.")
            if 'timestamps_unix_seconds' in stage:
                lines.append('  Quatre horodatages réels disponibles avec --json : émission client, réception serveur, émission serveur, réception client.')
                lines.append('  Le décalage suppose des délais aller/retour comparables ; une seule mesure ne garantit pas la précision.')
    lines.append('Utiliser --json pour les adresses, codes, erreurs et preuves détaillées.')
    lines.append('Observations successives ; un échec ne prouve pas sa cause. HTTP teste HEAD ; SNTP ne règle aucune horloge et ne certifie pas la source.')
    return '\n'.join(lines)
