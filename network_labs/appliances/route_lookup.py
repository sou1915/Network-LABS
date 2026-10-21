"""Observed IPv4 routing decisions; never a computed path or delivery verdict."""
from datetime import datetime, timezone
import ipaddress
import json
import os
import subprocess

from .interface_stats import managed_ports
from .runtime import RuntimeFailure

READ_TIMEOUT = 3


def ipv4_settings(manager, index, node):
    # Slash-separated sysctl paths preserve dots in eth0.20 interface names.
    requests = {'net/ipv4/conf/all/rp_filter': ('all', 'rp_filter')}
    for name in sorted(managed_ports(node)):
        for key in ('rp_filter', 'forwarding'):
            requests[f'net/ipv4/conf/{name}/{key}'] = (name, key)
    values, error = {}, None
    expected = {key.replace('/', '.'): value for key, value in requests.items()}
    try:
        result = manager.ns(index, 'sysctl', *requests, check=False, timeout=READ_TIMEOUT)
        seen = set()
        for line in result.stdout.splitlines():
            key, separator, value = line.partition('=')
            key = key.strip().replace('/', '.')
            if not separator or key not in expected:
                continue
            target = expected[key]
            if key in seen:
                values[target] = None
                continue
            seen.add(key)
            try:
                number = int(value.strip())
                values[target] = number if number in ((0, 1, 2) if target[1] == 'rp_filter' else (0, 1)) else None
            except ValueError:
                values[target] = None
        if result.returncode:
            error = result.stderr.strip()[:1000] or f'sysctl exited {result.returncode}'
    except (OSError, RuntimeFailure, subprocess.TimeoutExpired) as exc:
        error = str(exc)[:1000]
    all_value = values.get(('all', 'rp_filter'))
    ports = {}
    for name in sorted(managed_ports(node)):
        value = values.get((name, 'rp_filter'))
        effective = max(all_value, value) if all_value is not None and value is not None else None
        ports[name] = {'rp_filter': value, 'effective_rp_filter': effective,
                       'rp_filter_mode': {0: 'disabled', 1: 'strict', 2: 'loose'}.get(effective),
                       'forwarding': values.get((name, 'forwarding'))}
    return {'source': 'Actual per-namespace IPv4 sysctls; no settings changed',
            'all_rp_filter': all_value, 'interfaces': ports, 'error': error,
            'available': all_value is not None and all(p['effective_rp_filter'] is not None and p['forwarding'] is not None for p in ports.values()),
            'note': 'Effective rp_filter is max(all,interface). This is not a per-packet source-validation verdict.'}


def _json_read(manager, index, *args):
    returncode = None
    try:
        result = manager.ns(index, *args, check=False, timeout=READ_TIMEOUT)
        returncode = result.returncode
        if result.returncode:
            return {'status': 'command_failed', 'records': None, 'returncode': result.returncode,
                    'error': result.stderr.strip()[:1000] or result.stdout.strip()[:1000]}
        records = json.loads(result.stdout)
        if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
            raise ValueError('Expected an array of kernel JSON records.')
        return {'status': 'observed', 'records': records, 'returncode': 0, 'error': None}
    except (OSError, ValueError, RuntimeFailure, subprocess.TimeoutExpired) as exc:
        return {'status': 'unavailable', 'records': None, 'returncode': returncode, 'error': str(exc)[:1000]}


def _address(value):
    if not isinstance(value, str):
        raise ValueError('Route lookup addresses must be IPv4 text.')
    address = ipaddress.IPv4Address(value)
    if address.is_unspecified or address.is_multicast or int(address) == 0xffffffff:
        raise ValueError('Route lookup requires a usable non-multicast IPv4 address.')
    return str(address)


def lookup(manager, name, destination, *, source=None, ingress=None):
    """Caller holds the lab lock. All commands target this owned OCI netns."""
    destination = _address(destination)
    source = _address(source) if source is not None else None
    if ingress is not None and source is None:
        raise ValueError('Forwarded lookup requires both --ingress and --source.')
    state = manager.read()
    if state['phase'] != 'running':
        raise RuntimeFailure('Lab must be running before route lookup.')
    match = next(((i, n) for i, n in enumerate(state['spec']['nodes']) if n['name'] == name), None)
    if match is None or match[1]['runtime'] != 'oci':
        raise ValueError('Route lookup requires an existing OCI node; no VM guest adapter is available.')
    index, node = match
    if ingress is not None and ingress not in managed_ports(node):
        raise ValueError('Ingress must be a managed Linux interface of this node.')
    status = manager.crun('state', name, check=False, timeout=READ_TIMEOUT)
    if status.returncode or json.loads(status.stdout).get('status') != 'running':
        raise RuntimeFailure('Node container must be running before route lookup.')
    links = _json_read(manager, index, 'ip', '-j', '-d', 'link', 'show')
    if ingress is not None and (links['records'] is None or not any(r.get('ifname') == ingress for r in links['records'])):
        raise RuntimeFailure('Ingress interface is absent or its observation is unavailable.')
    query = [destination]
    if source is not None:
        query += ['from', source]
    if ingress is not None:
        query += ['iif', ingress]
    report = {'version': 1, 'lab': manager.name, 'node': name, 'revision': state.get('revision', 0),
              'started_at': datetime.now(timezone.utc).isoformat(),
              'query': {'destination': destination, 'source': source, 'ingress': ingress,
                        'origin': 'forwarded' if ingress is not None else 'local', 'uid': os.geteuid()},
              'source': 'Actual Linux ip route get/fibmatch in the node namespace',
              'test_packets_sent': False, 'packet_delivery': 'not_tested',
              'scope': 'Sequential observations, not an atomic snapshot. Unmarked IPv4 lookup; no transport/TOS selectors, nftables, NAT, conntrack, return-path or delivery simulation.',
              'lookup': _json_read(manager, index, 'ip', '-j', '-4', 'route', 'get', *query),
              'fibmatch': _json_read(manager, index, 'ip', '-j', '-4', 'route', 'get', 'fibmatch', *query),
              'rules': _json_read(manager, index, 'ip', '-j', '-4', 'rule', 'show'),
              'ipv4_settings': ipv4_settings(manager, index, node), 'links': links,
              'selected': None, 'egress_link': None, 'neighbor_target': None, 'neighbors': None,
              'neighbor_scope': 'Only plain IPv4 next-hop/direct neighbors are queried; via/encap contexts and unresolved nexthop objects remain unqueried.'}
    for key in ('lookup', 'fibmatch'):
        observed = report[key]
        rows = observed['records']
        if rows is not None and (not rows or not isinstance(rows[0].get('dst'), str) or
                                 (key == 'lookup' and not isinstance(rows[0].get('dev') or rows[0].get('type'), str))):
            observed.update(status='unavailable', records=None, error='Kernel route JSON lacks usable route fields.')
    routes = report['lookup']['records']
    if routes:
        row = routes[0]
        report['selected'] = {key: row.get(key) for key in ('dst', 'type', 'dev', 'gateway', 'via', 'encap', 'nhid', 'prefsrc', 'src', 'table', 'flags')}
        device = row.get('dev')
        report['egress_link'] = next((r for r in links['records'] or [] if r.get('ifname') == device), None)
        # Only query observed interface names; never pass arbitrary record text
        # as an ip option. Local routes do not need an Ethernet neighbor.
        plain = not any(key in row for key in ('via', 'encap', 'nexthops')) and ('nhid' not in row or isinstance(row.get('gateway'), str))
        if plain and row.get('type') not in ('local', 'broadcast', 'multicast') and isinstance(device, str) and report['egress_link'] is not None:
            target = row.get('gateway', destination)
            report['neighbor_target'] = target
            report['neighbors'] = _json_read(manager, index, 'ip', '-j', '-4', 'neigh', 'show', 'nud', 'all', 'to', target, 'dev', device)
    from .route_findings import findings
    report['findings'] = findings(report)
    report['completed_at'] = datetime.now(timezone.utc).isoformat()
    return report


def render(report):
    query = report['query']
    lines = [f"Route IPv4 | {report['lab']}/{report['node']} | destination {query['destination']}",
             'Aucun paquet de test envoyé ; une route sélectionnée ne prouve pas la livraison.']
    if query['source'] is not None:
        lines.append('Source : ' + query['source'] + (' | entrée : ' + query['ingress'] if query['ingress'] else ' | origine locale'))
    selected = report['selected']
    if selected is not None:
        lines.append(f"Décision kernel : dev={selected['dev'] or '?'} via={selected['gateway'] or 'non affiché'} type={selected['type'] or 'non affiché'}.")
    else:
        lines.append('Décision kernel non disponible : ' + (report['lookup']['error'] or 'aucune entrée retournée') + '.')
    matched = report['fibmatch']['records']
    lines.append('Entrée FIB observée : ' + (str(matched[0].get('dst', '?')) if matched else 'indisponible') + '.')
    if selected is not None and selected.get('prefsrc'):
        lines.append('Source préférée retournée par le kernel : ' + str(selected['prefsrc']) + '.')
    if report['egress_link'] is not None:
        link = report['egress_link']
        lines.append('Lien de sortie : flags=' + str(link.get('flags')) + ', operstate=' + str(link.get('operstate')) + '.')
    if query['ingress'] is not None:
        settings = report['ipv4_settings']['interfaces'].get(query['ingress'], {})
        forwarding = settings.get('forwarding')
        lines.append(f"Entrée {query['ingress']} : forwarding={forwarding if forwarding is not None else 'inconnu'}, rp_filter={settings.get('rp_filter_mode') or 'inconnu'}.")
    neighbors = report['neighbors']
    if neighbors is not None:
        lines.append('Voisin ' + str(report['neighbor_target']) + ' : ' +
                     (json.dumps(neighbors['records'], ensure_ascii=False) if neighbors['records'] is not None else 'indisponible') + '.')
    missing = [name for name in ('lookup', 'fibmatch', 'rules', 'links') if report[name]['records'] is None]
    if not report['ipv4_settings']['available']:
        missing.append('ipv4_settings')
    if missing:
        lines.append('Relevés incomplets : ' + ', '.join(missing) + '.')
    for finding in report.get('findings', []):
        lines.append('[' + finding['severity'].upper() + '] ' + finding['message'])
        if finding.get('next_step'):
            lines.append('  À vérifier : ' + finding['next_step'])
    lines += ['Observer les flags de lien, le voisinage et les règles ; tester séparément firewall, NAT et retour.',
              'Relevés successifs, non atomiques ; lookup IPv4 sans marque ni sélecteurs transport/TOS. Aucun verdict firewall/NAT/conntrack ou bout en bout.']
    return '\n'.join(lines)
