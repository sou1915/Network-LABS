"""Bounded IOS-style read commands backed by actual Linux JSON observations."""
from datetime import datetime, timezone
import json
import re
import subprocess

from .route_lookup import _json_read
from .runtime import RuntimeFailure

COMMANDS = {
    'show ip interface brief': ('ip', '-j', 'addr', 'show'),
    'show ip route': ('ip', '-j', '-4', 'route', 'show', 'table', 'main'),
    'show arp': ('ip', '-j', '-4', 'neigh', 'show', 'nud', 'all'),
    'show vlan brief': ('bridge', '-j', 'vlan', 'show'),
    'show mac address-table': ('bridge', '-j', 'fdb', 'show', 'br', 'br0'),
}


BIRD_COMMANDS = {
    'show ip ospf neighbor': 'show ospf neighbors',
    'show ip ospf interface': 'show ospf interface ospf4',
    'show ip ospf': 'show protocols all ospf4',
    'show ip route ospf': 'show route protocol ospf4 all',
}


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
    if command not in COMMANDS and command not in BIRD_COMMANDS:
        raise ValueError('Supported commands: ' + '; '.join([*COMMANDS, *BIRD_COMMANDS]))
    state = manager.read()
    if state['phase'] != 'running' or 'pending_spec' in state or 'pending_node' in state:
        raise RuntimeFailure('show requires a running lab without pending configuration.')
    match = next(((i, n) for i, n in enumerate(state['spec']['nodes']) if n['name'] == name), None)
    if match is None or match[1]['runtime'] != 'oci':
        raise ValueError('show requires an existing OCI node.')
    index, node = match
    if command in ('show vlan brief', 'show mac address-table') and (node['role'] != 'switch' or node.get('switch_backend') == 'ovs'):
        raise ValueError('This bridge show command requires a Linux switch; OVS has a separate observation backend.')
    if selection and selection['field'] == 'interface' and selection['value'] not in {*node['interfaces'], 'br0'}:
        raise ValueError('Select a declared Linux switch port or br0.')
    if command in BIRD_COMMANDS and node.get('ospf') is None:
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
              else 'Source : Linux kernel — adaptateur partiel, noms Linux conservés.')]
    if report['status'] != 'observed':
        lines.append('Observation ' + report['status'] + ' : ' + _cell(report.get('error') or report.get('observation') or report.get('container_status')))
        return '\n'.join(lines)
    if report['command'] in BIRD_COMMANDS:
        lines.extend(_cell(line) for line in report['observation']['text'].splitlines())
        lines.append('Observation du daemon ; ni convergence globale ni livraison des paquets certifiées.')
        return '\n'.join(lines)
    records = report['observation']['records']
    rows = []
    command = report['command']
    if command == 'show ip interface brief':
        headers = ['Interface', 'IPv4/prefix', 'Admin', 'Operstate']
        for row in records:
            addresses = row.get('addr_info')
            if isinstance(addresses, list):
                values = [str(a.get('local', '?')) + '/' + str(a.get('prefixlen', '?')) for a in addresses if isinstance(a, dict) and a.get('family') == 'inet']
                address = ', '.join(values) or 'unassigned'
            else:
                address = None
            flags = row.get('flags')
            admin = ('up' if 'UP' in flags else 'down') if isinstance(flags, list) else None
            rows.append([row.get('ifname'), address, admin, row.get('operstate')])
    elif command == 'show ip route':
        headers = ['Destination', 'Via', 'Interface', 'Protocol', 'Metric', 'Type']
        rows = [[r.get('dst'), r.get('gateway'), r.get('dev'), r.get('protocol'), r.get('metric'), r.get('type')] for r in records]
        lines.append('Table IPv4 main uniquement ; champs non retournés = ?. Détails avancés : --json.')
    elif command == 'show arp':
        headers = ['IPv4', 'MAC', 'Interface', 'State']
        rows = [[r.get('dst'), r.get('lladdr'), r.get('dev'), r.get('state')] for r in records]
        lines.append('Cache de voisinage IPv4 observé, y compris les entrées non résolues.')
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
