"""Linux bridge VLAN termination and routed SVIs, without a synthetic autostate."""
import ipaddress
import json
import re
import subprocess

from .spec import integer, keys

ARP = {'arp_ignore': 1, 'arp_announce': 2}


def validate_svis(node):
    svis = node.setdefault('svis', {})
    if not isinstance(svis, dict) or len(svis) > 32:
        raise ValueError('svis must be an object with at most 32 entries.')
    if svis and (node['runtime'] != 'oci' or node['role'] != 'switch' or node.get('switch_backend', 'linux') != 'linux' or node.get('startup') or node.get('dhcp_clients')):
        raise ValueError('SVIs require an OCI Linux-bridge switch without untracked startup or DHCP clients.')
    networks = []
    for name, policy in svis.items():
        if not isinstance(name, str) or not re.fullmatch(r'vlan[1-9][0-9]{0,3}', name):
            raise ValueError('SVI names must be canonical vlan1..vlan4094.')
        keys(policy, ('vlan', 'address'), 'SVI')
        vid = integer(policy.get('vlan'), 1, 4094, 'SVI VLAN')
        if name != 'vlan' + str(vid) or vid not in node['vlans']:
            raise ValueError('SVI name/VLAN must match a declared switch VLAN.')
        address = policy.setdefault('address', '')
        if not isinstance(address, str):
            raise ValueError('SVI address must be IPv4 CIDR text, or empty.')
        if address:
            interface = ipaddress.IPv4Interface(address)
            ip = interface.ip
            if ip.is_unspecified or ip.is_multicast or ip.is_loopback or int(ip) == 0xffffffff or (interface.network.prefixlen < 31 and ip in (interface.network.network_address, interface.network.broadcast_address)):
                raise ValueError('SVI IPv4 requires a usable unicast address.')
            if any(interface.network.overlaps(existing) for existing in networks):
                raise ValueError('Overlapping SVI subnets require VRF support, which is not implemented.')
            policy['address'] = str(interface)
            networks.append(interface.network)


def _self_has(records, vid):
    return any(r['ifname'] == 'br0' and any(v['vlan'] <= vid <= v.get('vlanEnd', v['vlan']) for v in r.get('vlans', [])) for r in records)


def configure(manager, index, node, previous):
    current, old = node.get('svis', {}), previous.get('svis', {})
    if not current and not old:
        return set()
    created = set()
    for name, settings in old.items():
        if name not in current:
            if manager.ns(index, 'ip', 'link', 'show', 'dev', name, check=False).returncode == 0:
                manager.ns(index, 'ip', 'link', 'delete', 'dev', name)
            records = json.loads(manager.ns(index, 'bridge', '-j', 'vlan', 'show', 'dev', 'br0').stdout)
            if _self_has(records, settings['vlan']):
                manager.ns(index, 'bridge', 'vlan', 'del', 'dev', 'br0', 'vid', str(settings['vlan']), 'self')
    for name, settings in current.items():
        if manager.ns(index, 'ip', 'link', 'show', 'dev', name, check=False).returncode:
            manager.ns(index, 'ip', 'link', 'add', 'link', 'br0', 'name', name, 'type', 'vlan', 'id', str(settings['vlan']))
            created.add(name)
        if name not in old or name in created:
            manager.ns(index, 'bridge', 'vlan', 'add', 'dev', 'br0', 'vid', str(settings['vlan']), 'self')
    return created


def configure_arp(manager, index, node):
    # ip_forward changes can reset interface settings; apply these afterwards.
    if node.get('svis'):
        manager.ns(index, 'sysctl', '-w', *[f'net.ipv4.conf.{name}.{key}={value}'
                   for name in sorted(node['svis']) for key, value in ARP.items()])


def observe(manager, index, node, links):
    names = sorted(node['svis'])
    observed = None
    try:
        result = manager.ns(index, 'sysctl', '-n', *[f'net.ipv4.conf.{name}.{key}' for name in names for key in ARP], check=False)
        values = result.stdout.splitlines()
        if result.returncode == 0 and len(values) == len(names) * len(ARP):
            observed = [int(value) for value in values]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    records = {row['ifname']: row for row in links}
    bridge = records.get('br0', {})
    result = {}
    for i, name in enumerate(names):
        actual = records.get(name, {})
        info = actual.get('linkinfo', {})
        parent = actual.get('link')
        parent_ok = parent == 'br0' or (bridge.get('ifindex') is not None and
                    (parent == bridge['ifindex'] or actual.get('link_index') == bridge['ifindex']))
        params = {key: observed[i * len(ARP) + j] if observed is not None else None for j, key in enumerate(ARP)}
        result[name] = {'source': 'Actual Linux VLAN link and per-interface ARP sysctls',
                        'vlan': info.get('info_data', {}).get('id'), 'parent': parent, 'parent_ifindex': actual.get('link_index'),
                        'encapsulation_verified': bool(parent_ok and info.get('info_kind') == 'vlan' and
                                                       info.get('info_data', {}).get('protocol') == '802.1Q' and
                                                       info.get('info_data', {}).get('id') == node['svis'][name]['vlan']),
                        'flags': actual.get('flags'), 'operstate': actual.get('operstate'),
                        'arp': params, 'arp_verified': params == ARP,
                        'note': 'Linux carrier/admin state, not Catalyst per-VLAN autostate, forwarding or gateway reachability proof.'}
    return result


def drift(node, actual):
    from .persistence import _memberships
    errors = []
    if node.get('svis'):
        expected = {(s['vlan'], False, False) for s in node['svis'].values()}
        if _memberships(actual['vlans'], 'br0') != expected:
            errors.append(node['name'] + ': SVI bridge self VLAN membership differs')
        for name in node['svis']:
            observed = actual.get('svis', {}).get(name, {})
            if observed.get('encapsulation_verified') is not True or observed.get('arp_verified') is not True:
                errors.append(node['name'] + '/' + name + ': SVI encapsulation/ARP settings differ or are unavailable')
    return errors
