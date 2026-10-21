"""ARP source admission from explicit/static or short-lived DHCP observations."""
import copy
import ctypes
import os
import ipaddress
import json
import subprocess
import time

from .spec import integer, keys
from .port_security import mac_address

TABLE = 'network_labs_arp_inspection'
LIFETIME_MS = 2000


def valid_ip(value):
    address = ipaddress.IPv4Address(value)
    if address.is_unspecified or address.is_multicast or address.is_loopback or int(address) == 0xffffffff:
        raise ValueError('ARP binding requires a nonzero usable unicast IPv4 address.')
    return str(address)


def validate_inspection(node):
    policy = node.setdefault('arp_inspection', None)
    if policy is None:
        return
    keys(policy, ('vlans', 'trusted', 'bindings'), 'ARP inspection')
    if node['runtime'] != 'oci' or node['role'] != 'switch' or node.get('startup'):
        raise ValueError('ARP inspection requires an OCI switch without untracked startup commands.')
    vlans, trusted, bindings = (policy.setdefault(k, []) for k in ('vlans', 'trusted', 'bindings'))
    if not isinstance(vlans, list) or len(vlans) > 256:
        raise ValueError('ARP inspection VLANs must be an array.')
    for vid in vlans:
        integer(vid, 1, 4094, 'ARP inspection VLAN')
    if len(set(vlans)) != len(vlans) or set(vlans) - set(node['vlans']):
        raise ValueError('ARP inspection VLANs must be unique and declared.')
    if not isinstance(trusted, list) or any(not isinstance(p, str) or p not in node['switchports'] for p in trusted) or len(set(trusted)) != len(trusted):
        raise ValueError('ARP trusted ports must be unique switch ports.')
    snoop = node.get('dhcp_snooping')
    if vlans and (not snoop or not snoop['enabled'] or set(vlans) - set(snoop['vlans'])):
        raise ValueError('ARP inspection requires DHCP snooping active on every inspected VLAN.')
    if not isinstance(bindings, list) or len(bindings) > 256:
        raise ValueError('At most 256 explicit ARP bindings are supported.')
    macs, ips = set(), set()
    for entry in bindings:
        keys(entry, ('port', 'vlan', 'mac', 'address'), 'ARP binding')
        port, vlan = entry.get('port'), integer(entry.get('vlan'), 1, 4094, 'ARP binding VLAN')
        if not isinstance(port, str):
            raise ValueError('ARP binding port must be text.')
        setting = node['switchports'].get(port, {})
        if port not in node['interfaces'] or setting.get('mode') != 'access' or setting.get('vlan') != vlan:
            raise ValueError('Static ARP binding must match a physical access port and its VLAN.')
        entry['mac'], entry['address'] = mac_address(entry.get('mac')), valid_ip(entry.get('address'))
        if (vlan, entry['mac']) in macs or (vlan, entry['address']) in ips:
            raise ValueError('Ambiguous/duplicate static ARP MAC or IP within a VLAN.')
        macs.add((vlan, entry['mac'])); ips.add((vlan, entry['address']))
    policy['vlans'], policy['trusted'] = sorted(vlans), sorted(trusted)
    policy['bindings'] = sorted(bindings, key=lambda b: (b['vlan'], b['port'], b['mac'], b['address']))


def effective(node):
    policy = node.get('arp_inspection')
    if not policy or not policy['vlans']:
        return None
    return {'ports': {p: v['vlan'] for p, v in node['switchports'].items() if v['vlan'] in policy['vlans']},
            'trusted': policy['trusted'], 'bindings': [b for b in policy['bindings'] if b['vlan'] in policy['vlans']]}


def dynamic_ports(policy):
    return sorted(set(policy['ports']) - set(policy['trusted']))


def render(policy, replace=False):
    lines = [f'delete table bridge {TABLE}'] if replace else []
    if policy is None:
        return '\n'.join(lines) + '\n'
    lines.append(f'table bridge {TABLE} {{')
    for port in dynamic_ports(policy):
        lines += [f'set dhcp_{port} {{', 'type ether_addr . ether_addr . ipv4_addr;',
                  f'flags timeout; timeout {LIFETIME_MS}ms; size 2048;', '}']
    lines += ['chain ingress {', 'type filter hook prerouting priority -290; policy accept;']
    for port in dynamic_ports(policy):
        lines.append(f'iifname "{port}" ether type arp jump inspect_{port};')
    lines.append('}')
    for port in dynamic_ports(policy):
        # Bridge prerouting skb length excludes the 14-byte Ethernet header.
        lines += [f'chain inspect_{port} {{', f'meta length < 28 counter drop comment "format:{port}";']
        for field, value in (('htype', '1'), ('ptype', 'ip'), ('hlen', '6'), ('plen', '4')):
            lines.append(f'arp {field} != {value} counter drop comment "format:{port}";')
        lines.append(f'arp operation != {{ request, reply }} counter drop comment "operation:{port}";')
        # Zero-source probes must be requests by an already authorized MAC, with
        # broadcast Ethernet destination and empty target hardware address.
        for condition in ('arp operation != request', 'ether daddr != ff:ff:ff:ff:ff:ff',
                          'arp daddr ether != 00:00:00:00:00:00',
                          'arp daddr ip { 0.0.0.0, 255.255.255.255, 224.0.0.0/4 }'):
            lines.append(f'arp saddr ip 0.0.0.0 {condition} counter drop comment "probe:{port}";')
        for entry in policy['bindings']:
            if entry['port'] != port:
                continue
            for address in (entry['address'], '0.0.0.0'):
                lines.append(f'ether saddr {entry["mac"]} arp saddr ether {entry["mac"]} arp saddr ip {address} counter accept comment "static:{port}";')
        lines += [f'ether saddr . arp saddr ether . arp saddr ip @dhcp_{port} counter accept comment "dynamic:{port}";',
                  f'counter drop comment "deny:{port}";', '}']
    lines.append('}')
    return '\n'.join(lines) + '\n'


def fingerprint(raw):
    from .firewall import fingerprint as base
    raw = copy.deepcopy(raw)
    for entry in (raw or {}).get('nftables', []):
        setting = entry.get('set', {})
        if setting.get('name', '').startswith('dhcp_'):
            setting.pop('elem', None); setting.pop('elements', None)
    return base(raw)


def read_table(manager, index):
    tables = json.loads(manager.ns(index, 'nft', '-j', 'list', 'tables').stdout)
    if any(e.get('table', {}).get('family') == 'bridge' and e['table'].get('name') == TABLE for e in tables['nftables']):
        return json.loads(manager.ns(index, 'nft', '-j', '-n', 'list', 'table', 'bridge', TABLE).stdout)
    return None


def apply(manager, index, node, previous=None):
    policy, old = effective(node), effective(previous) if previous else None
    if (previous is not None and policy == old) or (policy is None and old is None):
        return
    current = read_table(manager, index)
    if policy is not None or current is not None:
        target = manager.directory / (node['name'] + '.arp-inspection.nft')
        target.write_text(render(policy, replace=current is not None)); target.chmod(0o600)
        manager.ns(index, 'nft', '-c', '-f', str(target)); manager.ns(index, 'nft', '-f', str(target))
    baselines = manager.state.setdefault('arp_inspection_fingerprints', {})
    if policy is not None:
        baselines[node['name']] = fingerprint(read_table(manager, index))
    else:
        baselines.pop(node['name'], None)


def authorization_script(policy, bindings, now):
    """Refuse ambiguous dynamic owners and any conflict with an explicit binding."""
    from collections import defaultdict
    owners = defaultdict(set)
    static_macs = {(b['vlan'], b['mac']): (b['port'], b['address']) for b in policy['bindings']}
    for b in policy['bindings'] + bindings:
        if b.get('until', now + 1) > now:
            owners[(b['vlan'], b['address'])].add((b['port'], b['mac']))
    entries = {p: [] for p in dynamic_ports(policy)}
    count = 0
    for binding in bindings:
        port, vlan, mac, address = (binding[k] for k in ('port', 'vlan', 'mac', 'address'))
        remaining = int(min(LIFETIME_MS, (binding['until'] - now - 2) * 1000))
        if remaining <= 0 or port not in entries or policy['ports'][port] != vlan:
            continue
        if len(owners[(vlan, address)]) != 1 or (vlan, mac) in static_macs:
            continue
        mac, address = mac_address(mac), valid_ip(address)
        for ip in (address, '0.0.0.0'):
            entries[port].append(f'{mac} . {mac} . {ip} timeout {remaining}ms')
        count += 1
    lines = []
    for port, values in entries.items():
        lines.append(f'flush set bridge {TABLE} dhcp_{port}')
        if values:
            lines.append(f'add element bridge {TABLE} dhcp_{port} {{ ' + ', '.join(values) + ' }')
    return '\n'.join(lines) + '\n', count


def refresh(config, bindings, now, clear=False):
    policy = config.get('arp_inspection')
    if policy is None:
        return None
    # Only invoked by the single-threaded observer. Kill an in-flight nft child
    # if that observer is killed, rather than leaving a late refresh process.
    parent = os.getpid()
    death_signal = ctypes.CDLL(None).prctl
    def guard_parent():
        if death_signal(1, 9) or os.getppid() != parent:  # PR_SET_PDEATHSIG, SIGKILL
            os._exit(127)
    def nft(*args, **kwargs):
        result = subprocess.run(['nft', *args], capture_output=True, text=True, timeout=2, preexec_fn=guard_parent, **kwargs)
        if result.returncode:
            raise RuntimeError('ARP authorization update: ' + result.stderr.strip())
        return result.stdout
    if not clear:
        from .firewall import fingerprint as snoop_fingerprint
        from .snooping import TABLE as SNOOP_TABLE
        raw = json.loads(nft('-j', '-n', 'list', 'table', 'bridge', TABLE))
        snoop = json.loads(nft('-j', '-n', 'list', 'table', 'bridge', SNOOP_TABLE))
        if fingerprint(raw) != config['arp_fingerprint'] or snoop_fingerprint(snoop) != config['snoop_fingerprint']:
            raise RuntimeError('Managed DHCP/ARP policy drift; dynamic authorizations not refreshed.')
    now = max(now, time.monotonic())
    script, count = authorization_script(policy, [] if clear else bindings, now)
    if script.strip():
        nft('-f', '-', input=script)
    return {'last_refresh_monotonic': now, 'dynamic_bindings': count, 'maximum_grant_ms': LIFETIME_MS}


def observe(manager, index, node):
    raw = read_table(manager, index)
    baseline = manager.read().get('arp_inspection_fingerprints', {}).get(node['name'])
    result = {'source': 'Linux nftables ARP source admission', 'policy_verified': raw is not None and baseline is not None and fingerprint(raw) == baseline,
              'ruleset': raw, 'counters': [], 'dynamic_sets': [], 'maximum_dynamic_grant_ms': LIFETIME_MS,
              'note': 'ARP only, not IPv4 Source Guard. Static/trusted rules persist; dynamic grants expire within 2 s without refresh. A trusted DHCP assignment is not proof of client installation.'}
    for entry in (raw or {}).get('nftables', []):
        if 'set' in entry:
            result['dynamic_sets'].append(entry['set'])
        rule = entry.get('rule', {})
        for expression in rule.get('expr', []):
            if isinstance(expression, dict) and isinstance(expression.get('counter'), dict):
                result['counters'].append({'rule': rule.get('comment'), **expression['counter']})
    return result
