"""Persist declared startup configuration only after checking managed kernel state."""
import ipaddress
from pathlib import Path

from .lan import addresses, memberships
from .spec import identifier, load


def _memberships(records, name):
    result = set()
    for record in records:
        if record['ifname'] == name:
            for entry in record.get('vlans', []):
                for vid in range(entry['vlan'], entry.get('vlanEnd', entry['vlan']) + 1):
                    flags = entry.get('flags', [])
                    result.add((vid, 'PVID' in flags, 'Egress Untagged' in flags))
    return result


def drift(manager):
    errors = []
    for node in manager.read()['spec']['nodes']:
        if node['runtime'] != 'oci':
            continue
        actual = manager.inspect(node['name'])
        if node.get('firewall') is not None:
            from .firewall import fingerprint
            if fingerprint(actual['firewall']) != manager.read().get('firewall_fingerprints', {}).get(node['name']):
                errors.append(node['name'] + ': firewall rules differ')
        if node.get('port_security') and actual.get('port_security', {}).get('fingerprint_matches') is not True:
            errors.append(node['name'] + ': port security rules differ or are unavailable')
        expected = addresses(node)
        active = {name for name in expected if name not in node['subinterfaces'] or node['subinterfaces'][name]['vlan'] is not None}
        allowed = active | {'lo'} | ({'br0'} if node['role'] == 'switch' else set())
        links = {item['ifname']: item for item in actual['links']}
        if set(links) != allowed:
            errors.append(node['name'] + ': unexpected/missing interfaces')
        for interface in active:
            if interface not in links:
                continue
            if interface in node.get('interface_macs', {}) and links[interface].get('address', '').lower() != node['interface_macs'][interface]:
                errors.append(node['name'] + '/' + interface + ': MAC address differs')
            if ('UP' in links[interface].get('flags', [])) != (interface not in node['shutdown']):
                errors.append(node['name'] + '/' + interface + ': administrative state differs')
            if interface not in node['dhcp_clients']:
                ips = {f'{a["local"]}/{a["prefixlen"]}' for item in actual['addresses'] if item['ifname'] == interface
                       for a in item.get('addr_info', []) if a.get('scope') == 'global'}
                desired = {str(ipaddress.IPv4Interface(expected[interface]))} if expected[interface] else set()
                if ips != desired:
                    errors.append(node['name'] + '/' + interface + ': IPv4 address differs')
        if actual['forwarding'] != node['forwarding']:
            errors.append(node['name'] + ': forwarding differs')
        if not node['dhcp_clients']:
            gateways = [r.get('gateway') for r in actual['routes'] if r.get('dst') == 'default']
            if gateways != ([node['gateway']] if node.get('gateway') else []):
                errors.append(node['name'] + ': default route differs')
        configured = {(r['destination'], r['gateway'], r['interface']) for r in node['routes']}
        observed = {(str(ipaddress.IPv4Network(r['dst'], strict=False)), r.get('gateway'), r.get('dev')) for r in actual['routes']
                    if r.get('dst') != 'default' and r.get('protocol') != 'kernel'}
        if observed != configured:
            errors.append(node['name'] + ': static routes differ')
        if node['role'] == 'switch':
            from .lacp import drift as channel_drift
            from .spanning_tree import drift as tree_drift
            errors.extend(tree_drift(node, actual['links']))
            errors.extend(channel_drift(node, actual))
            for name, port in node['switchports'].items():
                if _memberships(actual['vlans'], name) != set(memberships(node, port)):
                    errors.append(node['name'] + '/' + name + ': VLAN membership differs')
    return errors


def startup_path(name):
    from .runtime import CONFIG_ROOT
    return CONFIG_ROOT / identifier(name) / 'startup.json'


def save_startup(name, spec):
    from .runtime import CONFIG_ROOT, RuntimeFailure, write_json
    if CONFIG_ROOT.is_symlink():
        raise RuntimeFailure('Refusing symlink startup configuration root.')
    CONFIG_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    stat = CONFIG_ROOT.stat()
    if stat.st_uid != 0 or stat.st_mode & 0o022:
        raise RuntimeFailure('Startup directory must be root-owned and not writable by other users.')
    target = startup_path(name)
    if target.parent.is_symlink():
        raise RuntimeFailure('Refusing symlink startup lab directory.')
    target.parent.mkdir(mode=0o700, exist_ok=True)
    write_json(target, spec)
    target.chmod(0o600)


def load_startup(name):
    return load(startup_path(name))
