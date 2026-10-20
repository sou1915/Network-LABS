"""Linux 802.3ad port-channels; topology validation never invents negotiation."""
import json
import re

from .spec import integer, keys


def validate_channels(node):
    channels = node.setdefault('port_channels', {})
    if not isinstance(channels, dict) or len(channels) > 16:
        raise ValueError('port_channels: object with at most 16 bonds.')
    if channels and (node['runtime'] != 'oci' or node['role'] != 'switch'):
        raise ValueError('Port-channels currently require OCI switches.')
    members = set()
    for name, channel in channels.items():
        if not isinstance(name, str) or not re.fullmatch(r'bond(?:[1-9]|[12][0-9]|3[0-2])', name):
            raise ValueError('Port-channel names: bond1..bond32.')
        keys(channel, ('members', 'mode', 'min_links'), 'Port-channel')
        ports = channel.get('members')
        if not isinstance(ports, list) or not 2 <= len(ports) <= 8 or any(not isinstance(p, str) or p not in node['interfaces'] for p in ports):
            raise ValueError('Port-channel needs 2..8 known physical members.')
        if len(set(ports)) != len(ports) or members.intersection(ports):
            raise ValueError('Each physical member belongs to one port-channel only.')
        members.update(ports)
        if channel.setdefault('mode', 'active') not in ('active', 'passive'):
            raise ValueError('Port-channel mode: LACP active or passive; no static/PAgP fallback.')
        integer(channel.setdefault('min_links', 1), 1, len(ports), 'min_links')
    return members


def validate_links(spec):
    """Collapse complete, paired bundles into one edge before cycle detection."""
    byname = {n['name']: n for n in spec['nodes']}
    membership = {(n['name'], p): (n['name'], name) for n in spec['nodes']
                  for name, c in n['port_channels'].items() for p in c['members']}
    peers, connected, logical, seen = {}, set(), [], set()
    for link in spec['links']:
        a, b = map(tuple, link)
        ga, gb = membership.get(a), membership.get(b)
        if ga is not None or gb is not None:
            if ga is None or gb is None:
                raise ValueError('Both endpoints of an LACP link must be declared bundle members.')
            if (ga in peers and peers[ga] != gb) or (gb in peers and peers[gb] != ga):
                raise ValueError('All members must connect the same two port-channels; no MLAG.')
            peers[ga], peers[gb] = gb, ga
            connected.update((a, b))
            ca, cb = byname[ga[0]]['port_channels'][ga[1]], byname[gb[0]]['port_channels'][gb[1]]
            if ca['mode'] == cb['mode'] == 'passive':
                raise ValueError('LACP needs at least one active peer; passive/passive is refused.')
            edge = tuple(sorted((ga, gb)))
            if edge in seen:
                continue
            seen.add(edge)
        logical.append((a[0], b[0]))
    if connected != set(membership):
        raise ValueError('Every declared port-channel member must have a paired link.')
    return logical


def configure(manager, index, node, previous):
    ns = lambda *args, **kwargs: manager.ns(index, *args, **kwargs)
    channels = node['port_channels']
    old = previous.get('port_channels', {})
    recreated = set()
    for name, channel in old.items():
        if name not in channels or channel['members'] != channels[name]['members']:
            if ns('ip', 'link', 'show', 'dev', name, check=False).returncode == 0:
                ns('ip', 'link', 'set', 'dev', name, 'down')
                ns('ip', 'link', 'delete', 'dev', name)
    if not channels:
        return recreated
    links = {r['ifname']: r for r in json.loads(ns('ip', '-j', '-d', 'link', 'show').stdout)}
    for name, channel in channels.items():
        options = ['miimon', '100', 'lacp_rate', 'fast', 'lacp_active', 'on' if channel['mode'] == 'active' else 'off',
                   'min_links', str(channel['min_links']), 'xmit_hash_policy', 'layer2+3']
        if name not in links or (name in old and old[name]['members'] != channel['members']):
            ns('ip', 'link', 'add', 'name', name, 'type', 'bond', 'mode', '802.3ad', *options)
            recreated.add(name)
        elif channel != old.get(name):
            # Bonding options can require IFF_DOWN; only this logical bundle
            # is interrupted. The LAN apply restores its declared admin state.
            ns('ip', 'link', 'set', 'dev', name, 'down')
            ns('ip', 'link', 'set', 'dev', name, 'type', 'bond', *options)
        for member in channel['members']:
            # Enslaving requires DOWN. Unchanged members must not be flapped.
            if name not in recreated and links[member].get('master') in (name, links[name].get('ifindex')):
                continue
            ns('ip', 'link', 'set', 'dev', member, 'down')
            if links[member].get('master') is not None:
                ns('ip', 'link', 'set', 'dev', member, 'nomaster')
            ns('ip', 'link', 'set', 'dev', member, 'master', name)
    return recreated


def parse_members(text):
    parts = re.split(r'^Slave Interface: (\S+)\s*$', text, flags=re.MULTILINE)
    active = re.search(r'Active Aggregator Info:\s*\n\s*Aggregator ID:\s*(\d+)', parts[0])
    active_id = int(active[1]) if active else None
    result = []
    for index in range(1, len(parts), 2):
        name, block = parts[index], parts[index + 1]
        actor = re.search(r'details actor lacp pdu:(.*?)details partner lacp pdu:', block, re.DOTALL | re.IGNORECASE)
        partner = re.search(r'details partner lacp pdu:(.*)', block, re.DOTALL | re.IGNORECASE)
        state = lambda match: int(found[1]) if match and (found := re.search(r'port state:\s*(\d+)', match[1], re.IGNORECASE)) else None
        actor_state, partner_state = state(actor), state(partner)
        mii = re.search(r'^MII Status:\s*(\S+)', block, re.MULTILINE)
        aggregator = re.search(r'^Aggregator ID:\s*(\d+)', block, re.MULTILINE)
        member_id = int(aggregator[1]) if aggregator else None
        up = bool(mii and mii[1] == 'up')
        result.append({'name': name, 'actor_state': actor_state, 'partner_state': partner_state,
                       'mii_up': up, 'aggregator_id': member_id, 'active_aggregator_id': active_id,
                       'collecting_distributing': up and active_id is not None and member_id == active_id
                       and actor_state is not None and partner_state is not None
                       and actor_state & 56 == 56 and partner_state & 56 == 56})
    return result


def observe(manager, index, node, links):
    result = {}
    for name, channel in node['port_channels'].items():
        text = manager.ns(index, 'cat', '/proc/net/bonding/' + name).stdout
        members = parse_members(text)
        physical = {r['ifname']: r for r in links}
        for member in members:
            flags = physical.get(member['name'], {}).get('flags', [])
            member['operational'] = 'UP' in flags and 'LOWER_UP' in flags
            member['collecting_distributing'] = member['collecting_distributing'] and member['operational']
        negotiated = [p['name'] for p in members if p['collecting_distributing']]
        kernel = next((r for r in links if r['ifname'] == name), {})
        result[name] = {'source': 'Linux bonding /proc and netlink', 'members': members, 'kernel': kernel,
                        'negotiated_members': negotiated,
                        'ready': len(negotiated) >= channel['min_links'] and 'UP' in kernel.get('flags', []) and 'LOWER_UP' in kernel.get('flags', []),
                        'proc': text}
    return result


def drift(node, actual):
    errors = []
    links = {r['ifname']: r for r in actual['links']}
    expected_masters = {p: name for name, c in node['port_channels'].items() for p in c['members']}
    expected_masters.update({p: 'br0' for p in node['switchports']})
    for port, master in expected_masters.items():
        if port not in links or master not in links or links[port].get('master') not in (master, links[master]['ifindex']):
            errors.append(node['name'] + '/' + port + ': link master differs')
    for name, channel in node['port_channels'].items():
        info = links.get(name, {}).get('linkinfo', {})
        data = info.get('info_data', {})
        if (info.get('info_kind') != 'bond' or data.get('mode') != '802.3ad' or data.get('miimon') != 100
                or data.get('ad_lacp_rate', data.get('lacp_rate')) != 'fast' or data.get('min_links') != channel['min_links']
                or data.get('ad_lacp_active', data.get('lacp_active')) not in (('on', 1) if channel['mode'] == 'active' else ('off', 0))
                or data.get('xmit_hash_policy') != 'layer2+3'):
            errors.append(node['name'] + '/' + name + ': bonding configuration differs')
    return errors
