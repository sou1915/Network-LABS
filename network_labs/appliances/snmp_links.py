"""Net-SNMP DisMan polling of selected real IF-MIB up/down instances."""
import json
import re
import subprocess
import os
import tempfile
from .service_config import observe_config

CONFIG = '/lab/snmp-link-events.conf'
EXTRA_MODULES = 'iquery,mteTrigger,mteTriggerConf,mteEvent,mteEventConf,mteObjects'
TABLE = '.1.3.6.1.2.1.2.2.1.'
INTERNAL = '_network_labs_links'
FILTER = 'nlab_snmp_links'
UP = '.1.3.6.1.6.3.1.1.5.4'
DOWN = '.1.3.6.1.6.3.1.1.5.3'


def validate_node(node):
    from .spec import keys, integer
    agent = node.get('snmp_agent') or {}
    if 'link_events' not in agent: return
    config = agent['link_events']; keys(config, ('interfaces', 'interval'), 'SNMP link events')
    if not agent.get('usm') or not (agent.get('notifications') or {}).get('usm'):
        raise ValueError('Link events require a USM agent and declared authPriv notifications.')
    if any(node.get(key) for key in ('firewall', 'port_security', 'dhcp_snooping', 'arp_inspection', 'ip_source_guard')):
        raise ValueError('Link-event source filtering does not yet compose with firewall or bridge security profiles.')
    ports = config.get('interfaces')
    if (not isinstance(ports, list) or not 1 <= len(ports) <= 16 or not all(isinstance(p, str) for p in ports) or
            len(set(ports)) != len(ports) or any(p not in node['interfaces'] or p == agent['interface'] for p in ports)):
        raise ValueError('Choose 1..16 distinct physical interfaces, excluding the notification management interface.')
    config['interfaces'] = sorted(ports)
    integer(config.get('interval'), 2, 60, 'Link observation interval')


def indices(manager, node):
    from .runtime import RuntimeFailure
    index = next(i for i, n in enumerate(manager.state['spec']['nodes']) if n['name'] == node['name'])
    result = {}
    for port in node['snmp_agent']['link_events']['interfaces']:
        rows = json.loads(manager.ns(index, 'ip', '-j', 'link', 'show', 'dev', port, timeout=3).stdout)
        if len(rows) != 1 or rows[0].get('ifname') != port or type(rows[0].get('ifindex')) is not int or rows[0]['ifindex'] <= 0:
            raise RuntimeFailure('Observed IF-MIB index unavailable for ' + node['name'] + ':' + port)
        result[port] = rows[0]['ifindex']
    return result


def config_text(node, observed):
    from .runtime import RuntimeFailure
    config = node['snmp_agent']['link_events']
    if (not isinstance(observed, dict) or set(observed) != set(config['interfaces']) or
            any(type(v) is not int or v <= 0 for v in observed.values()) or len(set(observed.values())) != len(observed)):
        raise RuntimeFailure('Selected link-event interface bindings are missing or ambiguous.')
    lines = ['createUser ' + INTERNAL, 'group NetworkLabsLinks usm ' + INTERNAL]
    for i in observed.values():
        lines += ['view NetworkLabsLinks included ' + TABLE + column + '.' + str(i) for column in ('1', '7', '8')]
    lines += ['access NetworkLabsLinks \"\" usm auth exact NetworkLabsLinks none none', 'iquerySecName ' + INTERNAL]
    for port in config['interfaces']:
        i = str(observed[port])
        payload = ' '.join('-i ' + TABLE + column + '.' + i for column in ('1', '7', '8'))
        for suffix, oid, state in (('Up', UP, '1'), ('Down', DOWN, '2')):
            name = 'NL' + suffix + i
            lines += ['notificationEvent ' + name + ' ' + oid + ' ' + payload,
                      'monitor -I -S -r ' + str(config['interval']) + ' -e ' + name + ' "' + name + '" ' + TABLE + '8.' + i + ' == ' + state]
    return '\n'.join(lines) + '\n'


def observe(manager, node):
    from .runtime import RuntimeFailure
    try:
        observed = manager.read().get('snmp_link_indices', {}).get(node['name'])
        expected = config_text(node, observed)
        file = observe_config(manager, node['name'], CONFIG, expected)
        current = indices(manager, node)
        match = current == observed
        source = observe_config(manager, node['name'], '/lab/snmp-link-source.nft', source_text(node))
        actual_filter = filter_fingerprint(manager, node)
        guard = actual_filter == manager.state.get('snmp_link_filters', {}).get(node['name'])
        return {'configuration_verified': file['configuration_verified'] and match and source['configuration_verified'] and guard, 'file': file, 'source_file': source, 'source_filter_verified': guard,
                'interface_indices_match': match, 'provisioned_indices': observed,
                'interval_seconds': node['snmp_agent']['link_events']['interval'],
                'note': 'File and current ifIndex conformity, not daemon/monitor liveness or delivery. DisMan samples IF-MIB up(1)/down(2); short changes and other states can be missed. Initial state is a baseline; no event history is restored.'}
    except (RuntimeFailure, OSError, ValueError, KeyError, TypeError, StopIteration, subprocess.TimeoutExpired) as error:
        return {'configuration_verified': False, 'detail': str(error)[:512], 'note': 'No declared-index or event-delivery fallback.'}


def prepare(manager, node):
    if not (node.get('snmp_agent') or {}).get('link_events'): return
    from .snmp import BINARY, MODULES
    from .runtime import RuntimeFailure
    snapshot = manager.state.get('snmp_link_indices', {}).get(node['name'])
    if snapshot is not None and not observe(manager, node)['configuration_verified']:
        raise RuntimeFailure('Link-event config or interface-index drift requires lab recreation.')
    result = manager.crun('exec', node['name'], BINARY, '-H', '-C', '-c', '/dev/null', '-m', '',
                          '-I', MODULES + ',usmConf,' + EXTRA_MODULES, check=False, timeout=5)
    text = result.stdout + result.stderr
    if result.returncode or any(not re.search(r'^\s*' + token + r'\s', text, re.M) for token in ('iquerySecName', 'iquerySecLevel', 'monitor', 'notificationEvent')):
        raise RuntimeFailure('Required native Net-SNMP DisMan modules are unavailable; no simulated link events.')
    observed = indices(manager, node); content = config_text(node, observed)
    install_source_filter(manager, node)
    path = manager.directory / node['name'] / 'files/snmp-link-events.conf'
    # Publish a complete private file before recording the binding. A failed write
    # must not leave a state entry that makes a subsequent start report drift.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix=path.name + '.', delete=False) as output:
            temporary = output.name
            output.write(content)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)
    manager.state.setdefault('snmp_link_indices', {})[node['name']] = observed; manager.save()


def source_text(node):
    from .snmp import listen_address
    return ('table inet ' + FILTER + ' {\n chain input {\n  type filter hook input priority -5; policy accept;\n  ip daddr '
            + listen_address(node) + ' udp dport 161 ip saddr != { ' + ', '.join(node['snmp_agent']['managers'])
            + ' } drop\n }\n}\n')


def filter_fingerprint(manager, node):
    from .firewall import fingerprint
    index = next(i for i, n in enumerate(manager.state['spec']['nodes']) if n['name'] == node['name'])
    return fingerprint(json.loads(manager.ns(index, 'nft', '-j', '-n', 'list', 'table', 'inet', FILTER, timeout=3).stdout))


def install_source_filter(manager, node):
    from .runtime import RuntimeFailure
    expected = manager.state.get('snmp_link_filters', {}).get(node['name'])
    if expected is not None:
        if filter_fingerprint(manager, node) != expected: raise RuntimeFailure('Managed SNMP source filter differs.')
        return
    index = next(i for i, n in enumerate(manager.state['spec']['nodes']) if n['name'] == node['name'])
    tables = json.loads(manager.ns(index, 'nft', '-j', 'list', 'tables', timeout=3).stdout)
    if any(row.get('table', {}).get('name') == FILTER and row['table'].get('family') == 'inet' for row in tables['nftables']):
        raise RuntimeFailure('Refusing to adopt an existing SNMP link-event source table.')
    path = manager.directory / node['name'] / 'files/snmp-link-source.nft'
    path.write_text(source_text(node)); path.chmod(0o600)
    manager.ns(index, 'nft', '-c', '-f', str(path)); manager.ns(index, 'nft', '-f', str(path))
    manager.state.setdefault('snmp_link_filters', {})[node['name']] = filter_fingerprint(manager, node); manager.save()


def check_restart(manager, node):
    from .runtime import RuntimeFailure
    if not (node.get('snmp_agent') or {}).get('link_events'): return
    previous = manager.state.get('snmp_link_indices', {}).get(node['name'])
    if (previous is not None or manager.state.get('phase') == 'running') and not observe(manager, node)['configuration_verified']:
        raise RuntimeFailure('Link-event configuration, source policy or interface-index drift requires lab recreation.')
