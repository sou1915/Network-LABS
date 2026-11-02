"""Bounded IOS-style read commands backed by actual Linux JSON observations."""
from datetime import datetime, timezone
import json
import re
import subprocess

from .route_lookup import _json_read
from .runtime import RuntimeFailure

COMMANDS = {
    'show ipv6 route': ('ip', '-j', '-6', 'route', 'show', 'table', 'main'),
    'show ipv6 interface brief': ('ip', '-j', '-6', 'addr', 'show'),
    'show ipv6 neighbors': ('ip', '-j', '-6', 'neigh', 'show', 'nud', 'all'),
    'show ip interface brief': ('ip', '-j', 'addr', 'show'),
    'show ip route': ('ip', '-j', '-4', 'route', 'show', 'table', 'main'),
    'show arp': ('ip', '-j', '-4', 'neigh', 'show', 'nud', 'all'),
    'show vlan brief': ('bridge', '-j', 'vlan', 'show'),
    'show mac address-table': ('bridge', '-j', 'fdb', 'show', 'br', 'br0'),
}


BIRD_COMMANDS = {
    'show ipv6 ospf neighbor': 'show ospf neighbors ospf6',
    'show ipv6 ospf interface': 'show ospf interface ospf6',
    'show ipv6 ospf': 'show protocols all ospf6',
    'show ipv6 route ospf': 'show route protocol ospf6 all',
    'show ip ospf neighbor': 'show ospf neighbors',
    'show ip ospf interface': 'show ospf interface ospf4',
    'show ip ospf': 'show protocols all ospf4',
    'show ip route ospf': 'show route protocol ospf4 all',
}


TREE_COMMAND = 'show spanning-tree'
LOG_COMMAND = 'show logging'
LOG_ARCHIVE_COMMAND = 'show logging archive'
LOG_COMMANDS = (LOG_COMMAND, LOG_ARCHIVE_COMMAND)

LLDP_COMMANDS = ('show lldp neighbors', 'show lldp neighbors detail')
NTP_COMMANDS = {'show ntp status': 'tracking', 'show ntp associations': 'sources'}


def show(manager, name, command):
    """Caller holds lab lock. No packet probes, config writes or topology inference."""
    if not isinstance(command, str) or '\n' in command or '\r' in command:
        raise ValueError('Enter one supported show command.')
    command = ' '.join(command.lower().split())
    query = command
    selection = None
    if command.startswith('show mac address-table '):
        match = re.fullmatch(r'show mac address-table (vlan|interface) ([a-z0-9_.-]+)', command)
        if not match:
            raise ValueError('Use show mac address-table [vlan 1..4094 | interface LINUX_NAME].')
        kind, value = match.groups()
        if kind == 'vlan':
            if not value.isdecimal() or not 1 <= int(value) <= 4094:
                raise ValueError('VLAN must be 1..4094.')
            value = int(value)
        selection = {'field': kind, 'value': value}
        command = 'show mac address-table'
    if command not in COMMANDS and command not in BIRD_COMMANDS and command not in LLDP_COMMANDS and command not in NTP_COMMANDS and command not in (TREE_COMMAND, *LOG_COMMANDS):
        raise ValueError('Supported commands: ' + '; '.join([*COMMANDS, *BIRD_COMMANDS, *LLDP_COMMANDS, *NTP_COMMANDS, TREE_COMMAND, *LOG_COMMANDS]))
    state = manager.read()
    if state['phase'] != 'running' or 'pending_spec' in state or 'pending_node' in state:
        raise RuntimeFailure('show requires a running lab without pending configuration.')
    match = next(((i, n) for i, n in enumerate(state['spec']['nodes']) if n['name'] == name), None)
    if match is None or match[1]['runtime'] != 'oci':
        raise ValueError('show requires an existing OCI node.')
    index, node = match
    if command in LOG_COMMANDS and not node.get('syslog_server'):
        raise ValueError('This node has no declared syslog collector.')
    if command in NTP_COMMANDS and not node.get('ntp_server'):
        raise ValueError('This node has no declared NTP server.')
    if command in ('show vlan brief', 'show mac address-table', TREE_COMMAND) and (node['role'] != 'switch' or node.get('switch_backend') == 'ovs'):
        raise ValueError('This bridge show command requires a Linux switch; OVS has a separate observation backend.')
    if selection and selection['field'] == 'interface' and selection['value'] not in {*node['interfaces'], 'br0'}:
        raise ValueError('Select a declared Linux switch port or br0.')
    if command in LLDP_COMMANDS and node.get('lldp') is None:
        raise ValueError('This node has no declared LLDP service.')
    if command in BIRD_COMMANDS and node.get('ospfv3' if command.startswith('show ipv6 ') else 'ospf') is None:
        raise ValueError('This node has no declared OSPF process. Configure it before querying BIRD.')
    report = dict(lab=manager.name, node=name, command=command, query=query, selection=selection, revision=state.get('revision', 0),
                  started_at=datetime.now(timezone.utc).isoformat(), status='unknown', observation=None,
                  kernel_command=list(COMMANDS[command]) if command in COMMANDS else None, configuration_changed=False, test_packets_sent=False,
                  source='Actual Linux kernel state; partial IOS-style command adapter, not vendor firmware',
                  scope='Linux interface names and raw kernel protocol/state labels. IPv4 main-table routes only; ARP includes unresolved entries; VLANs include tagged trunks and bridge-self membership; FDB includes local/permanent entries. No delivery or full vendor-feature verdict.')
    if command in BIRD_COMMANDS:
        report.update(daemon_command=BIRD_COMMANDS[command],
                      source='Actual BIRD 2 read-only control socket; partial IOS-style adapter',
                      scope='Actual BIRD text, not Cisco output. Protocol routes are the daemon RIB, not proof of kernel installation or packet delivery. No inferred neighbor roles or convergence verdict.')
    if command == TREE_COMMAND:
        report['scope'] = 'Linux common STP only, actual sysfs IDs and netlink port state. Sequential reads, no computed tree or global convergence/delivery verdict.'
    if command in LLDP_COMMANDS:
        report.update(daemon_command='show neighbors details',
                      source='Received lldpd JSON0 advertisements; no topology-derived neighbors',
                      scope='Advertised names and identifiers, not authenticated inventory. TTL is advertised, not remaining time. An empty table does not prove link failure or absent equipment.')
    if command in LOG_COMMANDS:
        target = 'rotated backup' if command == LOG_ARCHIVE_COMMAND else 'current log'
        report.update(source='Actual volatile rsyslog collector file', log_file=target,
                      scope='Last 8192 bytes of the ' + target + ' only; first line may be partial. No liveness or delivery verdict; sender IP is not authenticated.')
    if command in NTP_COMMANDS:
        report.update(daemon_command=NTP_COMMANDS[command], source='Actual chronyc output via local Unix socket; partial IOS-style adapter',
                      scope='Raw chronyc tracking or sources, not Cisco output. Local-reference mode does not establish accurate real-world time. No end-to-end delivery or authentication verdict.')
    try:
        container = manager.crun('state', name, check=False, timeout=3)
        if container.returncode:
            raise ValueError('Container state unavailable')
        status = json.loads(container.stdout)
        if not isinstance(status, dict) or not isinstance(status.get('status'), str):
            raise ValueError('Malformed container state')
        report['container_status'] = status['status']
        if status['status'] != 'running':
            report['status'] = 'blocked'
        elif command in LOG_COMMANDS:
            from .syslog_server import LOG
            path = LOG + '.1' if command == LOG_ARCHIVE_COMMAND else LOG
            result = manager.crun('exec', name, '/bin/busybox', 'tail', '-c', '8192', path, check=False, timeout=3)
            if result.returncode:
                raise ValueError('Collector ' + target + ' unavailable; it may not have been created yet.')
            report.update(status='observed', observation={'text': result.stdout})
        elif command == TREE_COMMAND:
            from .spanning_tree import kernel_ids, observe
            links = _json_read(manager, index, 'ip', '-j', '-d', 'link', 'show')
            report['kernel_command'] = ['ip', '-j', '-d', 'link', 'show']
            report['observation'] = {'links': links, 'ids': None, 'tree': None}
            if links['status'] != 'observed':
                raise ValueError('Bridge link observation unavailable')
            if any(not isinstance(r.get('ifname'), str) for r in links['records']):
                raise ValueError('Link name missing in kernel observation')
            bridge = next((r for r in links['records'] if r.get('ifname') == 'br0'), None)
            mode = (bridge or {}).get('linkinfo', {}).get('info_data', {}).get('stp_state')
            if mode not in (0, 1):
                raise ValueError('Linux bridge STP controller unavailable or unsupported')
            ids = kernel_ids(manager, index) if mode == 1 or node['spanning_tree']['mode'] == 'stp' else None
            report['observation']['ids'] = ids
            tree = observe(node, links['records'], ids)
            report['observation']['tree'] = tree
            valid_states = ('disabled', 'listening', 'learning', 'forwarding', 'blocking')
            complete = (set(tree['ports']) == set(node['switchports']) and
                        all(p.get('state') in valid_states for p in tree['ports'].values()))
            report['status'] = 'observed' if complete else 'partial'
        elif command in LLDP_COMMANDS:
            from .lldp import read_cli
            from .lldp_neighbors import normalize_neighbors
            raw = read_cli(manager, name, 'neighbors details')
            summary = normalize_neighbors(raw)
            report.update(status=summary['status'], observation={'raw': raw, 'summary': summary})
        elif command in NTP_COMMANDS:
            from .ntp_server import read_cli
            text = read_cli(manager, name, NTP_COMMANDS[command])
            report.update(status='observed', observation={'status': 'observed', 'text': text})
        elif command in BIRD_COMMANDS:
            from .ospf import read_cli
            text = read_cli(manager, name, BIRD_COMMANDS[command])
            available = isinstance(text, str) and bool(text.strip())
            report['observation'] = {'status': 'observed' if available else 'unavailable',
                                     'text': text if available else None,
                                     'error': None if available else 'BIRD control output unavailable or empty'}
            report['status'] = 'observed' if available else 'unknown'
        else:
            observation = _json_read(manager, index, *COMMANDS[command])
            report['observation'] = observation
            report['status'] = 'observed' if observation['status'] == 'observed' else 'unknown'
            if command == 'show mac address-table' and observation['status'] == 'observed':
                records = observation['records']
                # Keep the unfiltered kernel snapshot and exact query as evidence.
                # Interface filtering must use the same observed key as rendering.
                chosen = records if selection is None else [r for r in records if
                    (r.get('vlan') if selection['field'] == 'vlan' else fdb_interface(r)) == selection['value']]
                report['display_records'] = chosen
                report['rows_not_selected'] = len(records) - len(chosen)
    except (OSError, ValueError, RuntimeFailure, subprocess.TimeoutExpired) as error:
        report['error'] = str(error)[:1000]
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    return report


def fdb_interface(row):
    # iproute2 bridge/fdb.c emits ifname, unlike ip neighbour's dev.
    value = row.get('ifname')
    if value is None:
        value = row.get('dev')
    return value if isinstance(value, str) and value else None


def _cell(value):
    # Escape control/non-ASCII text from observed names without terminal effects.
    if value is None:
        return '?'
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)[1:-1]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return ', '.join(_cell(item) for item in value) or '-'
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))


def _table(headers, rows):
    if not rows:
        return ['Aucune entrée retournée par le kernel.']
    rows = [[_cell(value) for value in row] for row in rows]
    widths = [max(len(header), *(len(row[i]) for row in rows)) for i, header in enumerate(headers)]
    return ['  '.join(value.ljust(widths[i]) for i, value in enumerate(row)) for row in [headers, *rows]]


def render(report):
    lines = [report['node'] + '# ' + report.get('query', report['command']),
             ('Source : BIRD 2 — sortie réelle du daemon, adaptateur partiel.' if report['command'] in BIRD_COMMANDS
              else 'Source : lldpd — annonces LLDP reçues.' if report['command'] in LLDP_COMMANDS
              else 'Source : chronyc — état réel du daemon NTP.' if report['command'] in NTP_COMMANDS
              else 'Source : fichier du collecteur syslog.' if report['command'] in LOG_COMMANDS
              else 'Source : Linux kernel — adaptateur partiel, noms Linux conservés.')]
    if report['command'] in LOG_COMMANDS and report['status'] == 'observed':
        lines.append(('Archive précédente' if report['command'] == LOG_ARCHIVE_COMMAND else 'Fichier courant') + ' : derniers 8192 octets au maximum ; première ligne potentiellement partielle.')
        lines.extend(_cell(line) for line in report['observation']['text'].splitlines())
        lines.append('Adresse source non authentifiée ; ce relevé ne prouve ni disponibilité ni livraison.')
        return '\n'.join(lines)
    if report['command'] == TREE_COMMAND and report['status'] in ('observed', 'partial'):
        tree = report['observation']['tree']
        lines.append('STP commun Linux, pas PVST/MSTP/RSTP. Relevés successifs, sans arbre calculé.')
        for key in ('protocol', 'bridge_id', 'root_id', 'root_port', 'root_port_number', 'root_path_cost', 'topology_change'):
            lines.append(key + ' : ' + _cell(tree.get(key)))
        if tree['protocol'] == 'stp':
            lines.append('Ce bridge est racine : ' + ('oui' if tree['is_root'] else 'non'))
        if report['status'] == 'partial':
            lines.append('Observation partielle : ports absents ou états indisponibles.')
        rows = [[name, p.get('state'), p.get('cost'), p.get('priority'), p.get('bpdu_guard'), p.get('root_guard')]
                for name, p in tree['ports'].items()]
        lines.extend(_table(['Port', 'State', 'Cost', 'Priority', 'BPDU guard', 'Root guard'], rows))
        lines.append('Un état local stabilisé ne certifie ni convergence globale ni livraison des paquets.')
        return '\n'.join(lines)
    if report['command'] in LLDP_COMMANDS and report['status'] in ('observed', 'partial'):
        summary = report['observation']['summary']
        lines.append('TTL annoncé en secondes, pas un compte à rebours. Identités annoncées, non authentifiées.')
        if report['status'] == 'partial':
            lines.append('Observation partielle : champs incomplets ou entrées non interprétées = ' + str(summary['unparsed_entries']))
        rows = []
        detailed = report['command'].endswith(' detail')
        for row in summary['neighbors']:
            values = [row['local_port'], row['system_name'] or row['chassis_id']['value'],
                      row['port_id']['type'] + ': ' + row['port_id']['value'], row['ttl_seconds']]
            if detailed:
                values += [row['chassis_id']['type'] + ': ' + row['chassis_id']['value'], row['age'], row['incomplete_fields']]
            rows.append(values)
        headers = ['Port local', 'Nom/chassis annoncé', 'Port distant (type: ID)', 'TTL annoncé']
        if detailed:
            headers += ['Chassis (type: ID)', 'Age (lldpd)', 'Champs incomplets']
        lines.extend(_table(headers, rows) if rows else ['Aucun voisin LLDP annoncé dans cette observation ; aucune conclusion de connectivité.'])
        return '\n'.join(lines)
    if report['status'] != 'observed':
        lines.append('Observation ' + report['status'] + ' : ' + _cell(report.get('error') or report.get('observation') or report.get('container_status')))
        return '\n'.join(lines)
    if report['command'] in NTP_COMMANDS:
        lines.extend(_cell(line) for line in report['observation']['text'].splitlines())
        lines.append('Sortie chronyc, pas firmware Cisco ; référence locale sans garantie de temps réel ou de livraison.')
        return '\n'.join(lines)
    if report['command'] in BIRD_COMMANDS:
        lines.extend(_cell(line) for line in report['observation']['text'].splitlines())
        lines.append('Observation du daemon ; ni convergence globale ni livraison des paquets certifiées.')
        return '\n'.join(lines)
    records = report['observation']['records']
    rows = []
    command = report['command']
    if command in ('show ip interface brief', 'show ipv6 interface brief'):
        family = 'inet6' if command == 'show ipv6 interface brief' else 'inet'
        headers = ['Interface', 'IPv6/prefix' if family == 'inet6' else 'IPv4/prefix', 'Admin', 'Operstate']
        for row in records:
            addresses = row.get('addr_info')
            if isinstance(addresses, list):
                values = [str(a.get('local', '?')) + '/' + str(a.get('prefixlen', '?')) for a in addresses if isinstance(a, dict) and a.get('family') == family]
                address = ', '.join(values) or 'unassigned'
            else:
                address = None
            flags = row.get('flags')
            admin = ('up' if 'UP' in flags else 'down') if isinstance(flags, list) else None
            rows.append([row.get('ifname'), address, admin, row.get('operstate')])
    elif command in ('show ip route', 'show ipv6 route'):
        headers = ['Destination', 'Via', 'Interface', 'Protocol', 'Metric', 'Type']
        rows = [[r.get('dst'), r.get('gateway'), r.get('dev'), r.get('protocol'), r.get('metric'), r.get('type')] for r in records]
        lines.append('Table main uniquement ; champs non retournés = ?. Détails avancés : --json.')
    elif command in ('show arp', 'show ipv6 neighbors'):
        headers = ['IPv6' if command == 'show ipv6 neighbors' else 'IPv4', 'MAC', 'Interface', 'State']
        rows = [[r.get('dst'), r.get('lladdr'), r.get('dev'), r.get('state')] for r in records]
        lines.append('Cache de voisinage kernel observé, y compris les entrées non résolues.')
    elif command == 'show vlan brief':
        headers = ['Interface', 'VLAN', 'Flags']
        for row in records:
            vlans = row.get('vlans')
            if not isinstance(vlans, list):
                rows.append([row.get('ifname'), None, None]); continue
            for vlan in vlans:
                if isinstance(vlan, dict):
                    rows.append([row.get('ifname'), vlan.get('vlan'), vlan.get('flags')])
                else:
                    rows.append([row.get('ifname'), None, None])
        lines.append('Memberships kernel : ports access/trunk et bridge self ; pas une base VLAN constructeur.')
    else:
        headers = ['MAC', 'VLAN', 'Interface', 'State', 'Flags']
        selected = report.get('display_records', records)
        rows = [[r.get('mac'), r.get('vlan'), fdb_interface(r),
                 'reachable' if r.get('state') == '' else r.get('state'), r.get('flags')] for r in selected]
        if report.get('selection'):
            lines.append(f"Filtre observé : {len(selected)} entrée(s) retenue(s), {report['rows_not_selected']} non retenue(s). Snapshot complet : --json.")
            if not selected:
                lines.append('Aucune entrée observée correspondant au filtre ; aucune conclusion de connectivité.')
                return '\n'.join(lines)
        lines.append('État FDB vide émis par iproute2 = reachable ; absence du champ = ?. Aucun VLAN absent n’est inventé.')
        lines.append('FDB de br0, entrées locales/permanentes incluses ; aucune classification constructeur inventée.')
    lines.extend(_table(headers, rows))
    return '\n'.join(lines)
