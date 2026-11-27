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
    guest = node['runtime'] == 'firecracker' and node['role'] == 'switch'
    if svis and guest and len(svis) > (8 if layer3(node) else 1):
        raise ValueError('Switch micro-VM: one management SVI (interface vlan N) on a Layer 2 Catalyst (2960), '
                         'eight on a Layer 3 one (9200L, with ip routing).')
    if svis and not guest and (node['runtime'] != 'oci' or node['role'] != 'switch' or node.get('switch_backend', 'linux') != 'linux'
                               or node.get('startup') or node.get('dhcp_clients')):
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
            if interface.network.prefixlen == 0:
                raise ValueError('SVI prefix length must be 1..32; use an explicit gateway for a default route.')
            ip = interface.ip
            if ip.is_unspecified or ip.is_multicast or ip.is_loopback or int(ip) == 0xffffffff or (interface.network.prefixlen < 31 and ip in (interface.network.network_address, interface.network.broadcast_address)):
                raise ValueError('SVI IPv4 requires a usable unicast address.')
            if any(interface.network.overlaps(existing) for existing in networks):
                raise ValueError('Overlapping SVI subnets require VRF support, which is not implemented.')
            policy['address'] = str(interface)
            networks.append(interface.network)


L3_MODELS = ('cisco-9200l',)  # Catalysts that route between their SVIs once « ip routing » is typed (a 2960 does not)


def layer3(node):
    return node.get('role') == 'switch' and node.get('runtime') == 'firecracker' and node.get('model') in L3_MODELS


def routing(node):
    """True when a Layer 3 switch micro-VM routes: « ip routing » is in its configuration."""
    if not layer3(node) or not node.get('cli_config'):
        return False
    from . import ios_store
    return any(line.strip().lower() == 'ip routing' for line in ios_store.config(node)['global'])


def routed(node):
    """A routing switch's SVIs as router interfaces: [{'name', 'vlan', 'address', 'device'}], in VLAN order; the guest
    device is the bridge's VLAN interface br0.N (br0 itself on a bridge without VLAN filtering, which carries VLAN 1
    only). Shut or unaddressed SVIs are left out, as their connected networks are on IOS."""
    if not routing(node):
        return []
    from .guest_startup import vlan_plan
    plan = vlan_plan(node)
    found = []
    for name, policy in sorted((node.get('svis') or {}).items(), key=lambda item: item[1]['vlan']):
        if not policy.get('address') or name in (node.get('shutdown') or []) or (plan is None and policy['vlan'] != 1):
            continue
        found.append({'name': name, 'vlan': policy['vlan'], 'address': str(ipaddress.IPv4Interface(policy['address'])),
                      'device': 'br0' if plan is None else f'br0.{policy["vlan"]}'})
    return found


SWITCH_ROUTE = re.compile(r'ip route (\d+\.\d+\.\d+\.\d+) (\d+\.\d+\.\d+\.\d+) (\d+\.\d+\.\d+\.\d+)', re.IGNORECASE)


def static_routes(node):
    """A routing switch's « ip route NET MASK NEXT-HOP » lines in use: [(network, gateway, device, svi)] for each next hop
    that lies in one of its routed SVIs' networks (IOS keeps the others, unused)."""
    held = [(ipaddress.IPv4Interface(svi['address']).network, svi['device'], svi['name']) for svi in routed(node)]
    if not held:
        return []
    from . import ios_store
    found = []
    for line in ios_store.config(node)['global']:
        match = SWITCH_ROUTE.fullmatch(line.strip())
        if not match:
            continue
        network, gateway = ipaddress.IPv4Network(f'{match[1]}/{match[2]}'), ipaddress.IPv4Address(match[3])
        through = next(((device, name) for subnet, device, name in held if gateway in subnet), None)
        if through:
            found.append((network, gateway, *through))
    return found


def store_route(node, network, gateway=None, remove=False):
    """Keep (or drop) a Layer 3 switch's « ip route NET MASK NEXT-HOP » line; one route per network, as typed last."""
    from . import ios_store
    current = ios_store.config(node)
    kept = [line for line in current['global'] if not ((match := SWITCH_ROUTE.fullmatch(line.strip()))
                                                     and ipaddress.IPv4Network(f'{match[1]}/{match[2]}') == network
                                                     and (gateway is None or ipaddress.IPv4Address(match[3]) == gateway or not remove))]
    if not remove:
        kept.append(f'ip route {network.network_address} {network.netmask} {gateway}')
    current['global'] = kept
    node['cli_config'] = current


def management(node):
    """A switch micro-VM's management SVI as it runs: {'name', 'vlan', 'address', 'gateway'}, or None when it has none,
    it is shut, it has no address, or (on a bridge without VLANs) it is not VLAN 1. The gateway is the stored
    « ip default-gateway » when it lies in the SVI's subnet (IOS keeps the line either way)."""
    if node.get('role') != 'switch' or node.get('runtime') != 'firecracker' or not node.get('svis') or routing(node):
        return None  # a routing switch's SVIs are router interfaces (routed), and IOS then ignores ip default-gateway
    name, policy = next(iter(node['svis'].items()))
    if not policy.get('address') or name in (node.get('shutdown') or []):
        return None
    from .guest_startup import vlan_plan
    if vlan_plan(node) is None and policy['vlan'] != 1:
        return None  # an unfiltered bridge carries VLAN 1 only: no port in the SVI's VLAN, line protocol down
    address = ipaddress.IPv4Interface(policy['address'])
    gateway = None
    from . import ios_store
    for line in ios_store.config(node)['global'] if node.get('cli_config') else []:
        match = re.fullmatch(r'ip default-gateway (\S+)', line.strip(), re.IGNORECASE)
        if match and ipaddress.IPv4Address(match[1]) in address.network:
            gateway = match[1]
    return {'name': name, 'vlan': policy['vlan'], 'address': str(address), 'gateway': gateway}


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
