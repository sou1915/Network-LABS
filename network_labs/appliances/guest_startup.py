"""Persist bounded observed guest IPv4 state and replay it into fresh guest disks."""
import copy
import ipaddress
import re
import time
from .guest_control import request


def guest_interfaces(node):
    """Every guest interface with its declared primary address: ports ('' when unnumbered), then subinterfaces."""
    return {**node['interfaces'], **{name: sub['address'] for name, sub in node.get('subinterfaces', {}).items()}}


def _port_networks(node, profile):
    """Every IPv4 network configured on each declared port, primary first."""
    extras = {'eth0': profile['addresses'], **profile.get('port_addresses', {})}
    # A DHCP client port has no declared primary; its leased address is never part of the profile.
    return {port: [ipaddress.IPv4Interface(a).network for a in [*([primary] if primary else []), *extras.get(port, [])]]
            for port, primary in guest_interfaces(node).items()}


def shut_interfaces(node):
    """The ports administratively down, and the subinterfaces riding them: no link, no route through them."""
    down = set(node.get('shutdown') or [])
    return down | {name for name, sub in (node.get('subinterfaces') or {}).items() if sub['parent'] in down}


def expected_profile(node):
    """What the guest reads back: the declared profile without the routes through a shut port (Linux drops them)."""
    profile = copy.deepcopy(node.get('guest_network') or {'addresses': [], 'routes': []})
    down = shut_interfaces(node)
    if down:
        profile['routes'] = [r for r in profile['routes'] if route_port(node, node.get('guest_network') or profile,
                                                                         r['gateway']) not in down]
    return profile


def route_port(node, profile, gateway):
    """Ports never share a subnet, so an on-link next hop identifies one port."""
    gateway = ipaddress.IPv4Address(gateway)
    ports = [port for port, nets in _port_networks(node, profile).items() if any(gateway in net for net in nets)]
    if len(ports) != 1:
        raise ValueError('Guest next hop must be on a configured subnet.')
    return ports[0]


def validate_profile(node):
    profile = node.get('guest_network')
    if 'guest_network' not in node:
        return
    if (node['runtime'] != 'firecracker' or not isinstance(profile, dict)
            or not {'addresses', 'routes'} <= set(profile) <= {'addresses', 'routes', 'port_addresses'}):
        raise ValueError('guest_network requires a Firecracker addresses/routes object.')
    routes, extra_ports = profile['routes'], profile.get('port_addresses', {})
    if not isinstance(extra_ports, dict) or set(extra_ports) - (set(node['interfaces']) - {'eth0'}):
        raise ValueError('port_addresses must map declared guest ports other than eth0 to address lists.')
    by_port = {'eth0': profile['addresses'], **extra_ports}
    if any(not isinstance(values, list) for values in by_port.values()) or sum(map(len, by_port.values())) > 32 or not isinstance(routes, list) or len(routes) > 32:
        raise ValueError('Guest startup supports at most 32 addresses and 32 routes.')
    for port, values in by_port.items():
        if not node['interfaces'][port]:
            if values:
                raise ValueError('An unnumbered port (DHCP client or subinterface parent) takes no extra static addresses.')
            continue
        primary = str(ipaddress.IPv4Interface(node['interfaces'][port]))
        normalized = [str(ipaddress.IPv4Interface(a)) for a in values if isinstance(a, str) and '/' in a]
        if len(normalized) != len(values) or len(set(normalized)) != len(normalized) or primary in normalized:
            raise ValueError('Guest extra addresses must be unique explicit IPv4 prefixes, excluding primary.')
        by_port[port] = sorted(normalized)
    profile['addresses'] = by_port.pop('eth0')
    profile.pop('port_addresses', None)
    if any(by_port.values()):
        profile['port_addresses'] = {port: values for port, values in sorted(by_port.items()) if values}
    networks = _port_networks(node, profile)
    ports = list(networks)
    if any(a.overlaps(b) for i, left in enumerate(ports) for right in ports[i+1:] for a in networks[left] for b in networks[right]):
        raise ValueError('Guest addresses on different ports must not share or overlap a subnet.')
    checked = []
    for route in routes:
        if not isinstance(route, dict) or set(route) != {'network', 'gateway'}:
            raise ValueError('Guest route requires network/gateway only.')
        if not isinstance(route['network'], str) or '/' not in route['network'] or not isinstance(route['gateway'], str):
            raise ValueError('Guest route network/prefix and gateway must be strings.')
        network = str(ipaddress.IPv4Network(route['network'], strict=True))
        gateway = str(ipaddress.IPv4Address(route['gateway']))
        route_port(node, profile, gateway)
        if network == '0.0.0.0/0' and node.get('gateway'):
            raise ValueError('Guest default route already supplied by primary gateway.')
        checked.append({'network': network, 'gateway': gateway})
    if len({r['network'] for r in checked}) != len(checked):
        raise ValueError('Guest static routes require unique prefixes.')
    profile['routes'] = sorted(checked, key=lambda r: r['network'])


def query(socket, operation, **kwargs):
    result = request(socket, operation, **kwargs)
    if result['exit_code']:
        raise ValueError('Guest ' + operation + ' failed: ' + result['output'])
    return result['output']


def forwarding(socket):
    """True/False from the guest kernel; None for an image whose agent predates routers."""
    try:
        return query(socket, 'forwarding').strip() == '1'
    except ValueError as error:
        # Such an agent cannot have enabled forwarding either, so a host on it is still off.
        if 'unsupported operation' in str(error):
            return None
        raise


def check_forwarding(socket, node):
    state = forwarding(socket)
    if node.get('role') in ('router', 'firewall'):
        if state is not True:
            raise ValueError('Router or firewall guest is not forwarding IPv4; rebuild its image with the current agent.' if state is None
                             else 'Router or firewall guest is not forwarding IPv4.')
    elif state:
        raise ValueError('Host guest forwards IPv4 although its role is host; declare a router instead.')


def dhcp_pool(node):
    from .dhcp import pool_network  # the port's network, or the remote LAN of a relayed pool
    server = node['dhcp_server']
    return {'start': server['start'], 'end': server['end'], 'router': server['router'], 'dns': server['dns'],
            'lease_seconds': server['lease_seconds'], 'netmask': pool_network(node).prefixlen}


def leases(socket, interface):
    """The guest DHCP server's current leases as [{mac, address, hostname}]; fails if the server is not running."""
    rows = []
    for line in query(socket, 'dhcp-leases', interface=interface).splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2 and re.fullmatch(r'[0-9a-f]{2}(:[0-9a-f]{2}){5}', fields[0]):
            rows.append({'mac': fields[0], 'address': str(ipaddress.IPv4Address(fields[1])),
                         # "Expires in" may read "1 days 02:00:00": a lone number before "days" is not a hostname.
                         'hostname': fields[2] if len(fields) > 3 and fields[3] != 'days' else ''})
    return rows


def vlan_plan(node):
    """The bridge VLAN entries a switch guest must hold, as {(port, vid, 'pvid' | 'tagged')}; None for one untagged VLAN 1.

    An access port is untagged in its VLAN. A trunk carries every allowed VLAN tagged, and its
    native VLAN untagged. A plain switch (only VLAN 1, all access) keeps the bridge without
    VLAN filtering, so it also runs on a guest kernel without 802.1Q.
    """
    ports = node['switchports']
    if node['vlans'] == [1] and all(port == {'mode': 'access', 'vlan': 1} for port in ports.values()):
        return None
    plan = set()
    for name, port in ports.items():
        if port['mode'] == 'access':
            plan.add((name, port['vlan'], 'pvid'))
            continue
        allowed = node['vlans'] if port['allowed'] == 'all' else port['allowed']
        plan.add((name, port['native_vlan'], 'pvid'))
        plan.update((name, vid, 'tagged') for vid in allowed if vid != port['native_vlan'])
    return plan


def observed_vlans(socket, node):
    """The guest bridge's VLAN entries on the declared ports, in vlan_plan() form."""
    found = set()
    for line in query(socket, 'bridge-vlans').splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0] not in node['interfaces']:
            continue  # br0's own entries and other devices are not ports.
        pvid, untagged = 'pvid' in fields[2:], 'untagged' in fields[2:]
        if pvid != untagged:
            raise ValueError('Unmanaged bridge VLAN entry: ' + line)
        found.add((fields[0], int(fields[1]), 'pvid' if pvid else 'tagged'))
    return found


def check_switch(socket, node):
    """A switch guest bridges exactly its declared ports, all up, holds no IPv4 and does not route."""
    ports = sorted(query(socket, 'bridge-ports').split())
    if ports != sorted(node['interfaces']):
        raise ValueError('Switch guest bridges ' + (', '.join(ports) or 'no port') + ' instead of its declared ports.')
    up = set(); interface = None; held = []
    for line in query(socket, 'addresses').splitlines():
        header = re.match(r'^\d+: ([^:@]+)[^:]*: <([^>]*)>', line)
        if header:
            interface = header[1]
            if interface not in ('lo', 'br0') and interface not in node['interfaces']:
                raise ValueError('Guest has an undeclared interface.')
            if 'UP' in header[2].split(','): up.add(interface)
        elif line.split()[:1] == ['inet'] and interface == 'br0':
            held.append(str(ipaddress.IPv4Interface(line.split()[1])))
        elif line.split()[:1] == ['inet'] and interface != 'lo':
            raise ValueError(f'Switch guest holds an IPv4 address on {interface}; switch ports stay unnumbered.')
    from .svi import management
    svi = management(node)
    if held != ([svi['address']] if svi else []):
        raise ValueError('Switch guest bridge holds ' + (', '.join(held) or 'no address') + ' instead of its management SVI.')
    if svi and svi['gateway'] and not any(line.split()[:5] == ['default', 'via', svi['gateway'], 'dev', 'br0']
                                          for line in query(socket, 'routes').splitlines()):
        raise ValueError('Switch guest lacks its ip default-gateway route.')
    down = set(node.get('shutdown') or [])
    if not {'br0', *(set(node['interfaces']) - down)} <= up or down & up:
        raise ValueError('Switch guest bridge and its ports must be up, its shut ports down.')
    plan = vlan_plan(node)
    if plan is not None and observed_vlans(socket, node) != plan:
        raise ValueError('Switch guest VLAN membership differs from its declared switchports.')
    check_forwarding(socket, node)


def observe(socket, node):
    """Fail closed on unrepresentable state; never save shell output as commands."""
    text = query(socket, 'addresses')
    declared = guest_interfaces(node)
    by_port = {port: [] for port in declared}
    interface = None; active = set()
    for line in text.splitlines():
        header = re.match(r'^\d+: ([^:@]+)(?:@[^:]+)?: <([^>]*)>', line)  # a subinterface reads "eth0.10@eth0
        if header:
            interface = header[1]
            if interface != 'lo' and interface not in by_port:
                raise ValueError('Guest has an undeclared interface.')
            if 'UP' in header[2].split(','): active.add(interface)
        fields = line.split()
        if fields and fields[0] == 'inet' and interface in by_port:
            by_port[interface].append(str(ipaddress.IPv4Interface(fields[1])))
    dynamic = set(node.get('dhcp_clients', []))
    down = shut_interfaces(node)
    for port, primary_address in declared.items():
        if (port in active) == (port in down):
            raise ValueError(f'Guest interface {port} must be ' + ('down (shutdown).' if port in down else 'up.'))
        if port in dynamic or not primary_address:
            continue
        primary_address = str(ipaddress.IPv4Interface(primary_address))
        if primary_address not in by_port[port]:
            raise ValueError('Save requires all declared guest interfaces with their primary IPv4 addresses.')
    # Leased addresses come from the DHCP server on every boot; they are never saved as static ones.
    def unexpected(port, values):
        primary = str(ipaddress.IPv4Interface(declared[port])) if declared[port] else None
        return [] if port in dynamic else [a for a in values if a != primary]
    extras = {port: unexpected(port, values) for port, values in by_port.items()}
    from .ios_nat import public_addresses
    for port, values in public_addresses(node).items():  # held for IOS static NAT and pools: checked, never saved
        missing = sorted(set(values) - set(extras[port]))
        if missing:
            raise ValueError(f'Guest {port} lacks the NAT address(es) {", ".join(missing)}.')
        extras[port] = [a for a in extras[port] if a not in values]
    for name in node.get('subinterfaces', {}):
        if extras.pop(name):
            raise ValueError(f'Extra addresses on subinterface {name} cannot be saved; only its declared address is.')
    from .ios_routes import port_routes
    through_ports = {(str(n), p) for n, p in port_routes(node)}
    routes = []; devices = {}
    connected = {(port, str(ipaddress.IPv4Interface(a).network), str(ipaddress.IPv4Interface(a).ip)) for port, values in by_port.items() for a in values}
    default_seen = False
    for line in query(socket, 'routes').splitlines():
        fields = line.split()
        if not fields: continue
        if (node.get('ospf') or node.get('bgp') or _runs_rip(node) or _runs_eigrp(node)) and learned(fields):
            continue  # Routes learned by OSPF or BGP come back from the neighbours on every boot; they are never saved.
        network = str(ipaddress.IPv4Network('0.0.0.0/0' if fields[0] == 'default' else fields[0]))
        if 'via' not in fields:
            if (network, fields[2]) in through_ports:
                continue  # « ip route NET MASK PORT »: kept as IOS lines, checked by check_port_routing
            if len(fields) != 7 or fields[1] != 'dev' or fields[3:6] != ['scope', 'link', 'src'] or (fields[2], network, fields[6]) not in connected:
                raise ValueError('Unmanaged guest route cannot be saved: ' + line)
            continue
        if len(fields) != 5 or fields[1] != 'via' or fields[3] != 'dev' or fields[4] not in by_port:
            raise ValueError('Unsupported guest static route: ' + line)
        gateway = str(ipaddress.IPv4Address(fields[2]))
        if network == '0.0.0.0/0' and fields[4] in dynamic:
            continue  # Installed by the DHCP client from the lease's router option.
        if network == '0.0.0.0/0' and node.get('gateway'):
            if gateway != node['gateway'] or fields[4] != 'eth0': raise ValueError('Guest primary gateway differs.')
            default_seen = True
        else:
            routes.append({'network': network, 'gateway': gateway}); devices[network] = fields[4]
    if node.get('gateway') and not default_seen and 'eth0' not in down:
        raise ValueError('Guest primary gateway missing.')
    candidate = copy.deepcopy(node)
    candidate['guest_network'] = {'addresses': extras.pop('eth0'), 'routes': routes, 'port_addresses': extras}
    validate_profile(candidate)
    for route in candidate['guest_network']['routes']:
        # A next hop reached through another port than its own subnet cannot be replayed.
        if route_port(candidate, candidate['guest_network'], route['gateway']) != devices[route['network']]:
            raise ValueError('Unsupported guest static route device for ' + route['network'])
    check_forwarding(socket, node)
    if node.get('role') == 'router':
        check_port_routing(socket, node)
    if node.get('role') == 'firewall':
        from .guest_firewall import check
        check(socket, node)
    elif node.get('acl_ports'):
        from .acl import policy
        from .guest_firewall import check
        check(socket, {'firewall': policy(node)})
    if node.get('dhcp_server'):
        leases(socket, node['dhcp_server']['interface'])  # Fails closed if the declared server is not running.
    if node.get('ospf'):
        check_ospf(socket, node)
    if node.get('bgp'):
        check_bgp(socket, node)
    return candidate['guest_network']


BIRD_METRIC = '32'  # BIRD 2's kernel protocol installs its routes with metric 32 (its default; config() keeps it)
FRR_METRIC = '20'  # FRR's zebra installs BGP and EIGRP routes with metric 20


def learned(fields):
    """A route BIRD installed. BusyBox's 'ip route' never prints the protocol, so BIRD's routes are told apart by
    their metric; static routes the agent adds and connected routes carry none. iproute2 also prints 'proto bird'."""
    pairs = {fields[i]: fields[i + 1] for i in range(len(fields) - 1)}
    return pairs.get('proto') in ('bird', '12', 'bgp', '186', 'eigrp', '192') or pairs.get('metric') in (BIRD_METRIC, FRR_METRIC)


def check_ospf(socket, node):
    """The guest's BIRD runs the configuration the lab declares, byte for byte."""
    from .ospf import config
    try:
        running = query(socket, 'ospf-show', state='config')
    except ValueError as error:
        raise ValueError(f'{node["name"]}: OSPF is not running in the guest ({error}).') from error
    if running != config(node):
        raise ValueError(f'{node["name"]}: the guest OSPF configuration differs from the lab.')


def start_ospf(socket, node, timeout=5):
    """Start BIRD from the typed process, then wait for its control socket to answer."""
    from .ospf import guest_process
    query(socket, 'ospf-start', ospf=guest_process(node))
    deadline = time.monotonic() + timeout
    while True:
        try:
            query(socket, 'ospf-show', state='neighbors')
            break
        except ValueError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.1)
    check_ospf(socket, node)


def relay_command(relay):
    """The command line the guest's relay runs for RELAY (what DHCP_RELAY_SHOW reads back)."""
    return f'network-labs-agent --dhcp-relay {relay["server"]} ' + ','.join(relay['clients'])


def start_relay(socket, node, timeout=3):
    """Start the guest's DHCP relay for the router's « ip helper-address » ports, then read it back."""
    from .ios_relay import process
    wanted = process(node)
    query(socket, 'dhcp-relay-start', relay=wanted)
    deadline = time.monotonic() + timeout
    while True:  # the relay writes its pid file just after the request returns
        try:
            running = query(socket, 'dhcp-relay-show')
            break
        except ValueError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.1)
    if running != relay_command(wanted):
        raise ValueError(f'{node["name"]}: the guest DHCP relay differs from its helper addresses ({running}).')


def _runs_rip(node):
    from .rip import process
    return process(node) is not None


def check_rip(socket, node):
    """The guest's BIRD runs the RIP configuration the lab declares (rendered by the agent from the same fields)."""
    from .rip import guest_process
    wanted = query(socket, 'rip-render', rip=guest_process(node))
    try:
        running = query(socket, 'rip-show', state='config')
    except ValueError as error:
        raise ValueError(f'{node["name"]}: RIP is not running in the guest ({error}).') from error
    if running != wanted:
        raise ValueError(f'{node["name"]}: the guest RIP configuration differs from the lab.')


def start_rip(socket, node, timeout=8):
    """Start BIRD's RIP from the typed process, then wait for birdc to answer."""
    from .rip import guest_process
    query(socket, 'rip-start', rip=guest_process(node))
    deadline = time.monotonic() + timeout
    while True:
        try:
            query(socket, 'rip-show', state='routes')
            break
        except ValueError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.1)
    check_rip(socket, node)


def check_eigrp(socket, node):
    """The guest's eigrpd runs the EIGRP configuration the lab declares (rendered by the agent from the same fields)."""
    from .eigrp import process
    wanted = query(socket, 'eigrp-render', eigrp=process(node))
    try:
        running = query(socket, 'eigrp-show', state='config')
    except ValueError as error:
        raise ValueError(f'{node["name"]}: EIGRP is not running in the guest ({error}).') from error
    if running != wanted:
        raise ValueError(f'{node["name"]}: the guest EIGRP configuration differs from the lab.')


def start_eigrp(socket, node, timeout=8):
    """Start zebra and eigrpd from the typed process, then wait for vtysh to answer."""
    from .eigrp import process
    query(socket, 'eigrp-start', eigrp=process(node))
    deadline = time.monotonic() + timeout
    while True:
        try:
            query(socket, 'eigrp-show', state='neighbors')
            break
        except ValueError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.2)
    check_eigrp(socket, node)


def _runs_eigrp(node):
    from .eigrp import process
    return process(node) is not None


LIVE_SWITCH = ('vlans', 'switchports', 'shutdown', 'cli_config', 'svis')


def _svi(socket, node, plan, add):
    """Put a switch's management SVI on its guest bridge (address, ip default-gateway route, and with VLAN filtering
    the bridge's own membership of the SVI's VLAN), or take it off."""
    from .svi import management
    svi = management(node)
    if svi is None:
        return
    moved = plan is not None and svi['vlan'] != 1  # the bridge's own untagged VLAN: 1 by default
    if add:
        if moved:
            query(socket, 'bridge-vlan-add', interface='br0', vlan=svi['vlan'], state='pvid')
            query(socket, 'bridge-vlan-delete', interface='br0', vlan=1)
        query(socket, 'address-add', interface='br0', cidr=svi['address'])
        if svi['gateway']:
            query(socket, 'route-add', network='0.0.0.0/0', gateway=svi['gateway'], interface='br0')
        return
    if svi['gateway']:
        query(socket, 'route-delete', network='0.0.0.0/0', gateway=svi['gateway'], interface='br0')
    query(socket, 'address-delete', interface='br0', cidr=svi['address'])
    if moved:
        query(socket, 'bridge-vlan-add', interface='br0', vlan=1, state='pvid')
        query(socket, 'bridge-vlan-delete', interface='br0', vlan=svi['vlan'])


def change_switch(socket, old, new):
    """Bring a running switch guest from OLD's VLANs, access/trunk ports, shut ports and management SVI to NEW's:
    only what differs."""
    from .svi import management
    before, after = vlan_plan(old), vlan_plan(new)
    svi_changed = management(old) != management(new) or before != after
    if svi_changed:
        _svi(socket, old, before, add=False)
    if before != after:
        if before is None:
            try:
                query(socket, 'bridge-vlan-filtering')
            except ValueError as error:
                raise ValueError(str(error) + ' (VLANs need the Network LABS guest kernel, tools/guest_kernel)') from error
            before = {(port, 1, 'pvid') for port in old['interfaces']}  # every port's default entry once filtering is on
        wanted = after if after is not None else {(port, 1, 'pvid') for port in new['interfaces']}
        for port, vid, _ in sorted(before - wanted):
            if not any(p == port and v == vid for p, v, _ in wanted):
                query(socket, 'bridge-vlan-delete', interface=port, vlan=vid)
        # Untagged (pvid) entries last: each one replaces the port's default VLAN.
        for port, vid, mode in sorted(wanted - before, key=lambda entry: (entry[2] == 'pvid', entry)):
            query(socket, 'bridge-vlan-add', interface=port, vlan=vid, state=mode)
    for port in sorted(set(new.get('shutdown') or []) ^ set(old.get('shutdown') or [])):
        if port in new['interfaces']:  # a shut interface vlan only takes the SVI off the bridge (below)
            query(socket, 'link', interface=port, state='down' if port in (new.get('shutdown') or []) else 'up')
    if svi_changed:
        _svi(socket, new, after, add=True)
    check_switch(socket, new)


LIVE_ROUTING = ('interfaces', 'shutdown', 'gateway', 'guest_network', 'ospf', 'acls', 'acl_ports', 'bgp', 'cli_config')


def _route(socket, node, operation, network, gateway):
    profile = node.get('guest_network') or {'addresses': [], 'routes': []}
    port = route_port(node, profile, gateway)
    # eth0 keeps the original request, as at boot.
    query(socket, operation, network=network, gateway=gateway, **({} if port == 'eth0' else {'interface': port}))


def _port(node, gateway):
    """The interface a next hop is reached through (None when no interface holds its network)."""
    try:
        return route_port(node, node.get('guest_network') or {'addresses': [], 'routes': []}, gateway)
    except ValueError:
        return None


def _port_routing(socket, old, new):
    """Proxy ARP on a router's ports and its routes through a port (ios_routes), from OLD's to NEW's."""
    from .ios_routes import port_routes, proxy_arp
    before, after = proxy_arp(old), proxy_arp(new)
    for port, on in sorted(after.items()):
        if before.get(port) != on:
            query(socket, 'proxy-arp', interface=port, state='on' if on else 'off')
    down = shut_interfaces(new)
    held = lambda node: {(str(n), p) for n, p in port_routes(node) if p not in shut_interfaces(node)}
    for network, port in sorted(held(old) - held(new)):
        query(socket, 'dev-route-delete', interface=port, network=network)
    for network, port in sorted(held(new) - held(old)):
        if port not in down:
            query(socket, 'dev-route-add', interface=port, network=network)


def check_port_routing(socket, node):
    """The guest's proxy ARP and routes through a port are the router's."""
    from .ios_routes import port_routes, proxy_arp
    observed = dict(line.split() for line in query(socket, 'proxy-arps').splitlines() if len(line.split()) == 2)
    for port, on in proxy_arp(node).items():
        if observed.get(port) != ('1' if on else '0'):
            raise ValueError(f'{node["name"]}: proxy ARP on {port} differs from the router\'s ip proxy-arp.')
    listed = query(socket, 'routes').splitlines()
    for network, port in port_routes(node):
        if port in shut_interfaces(node):
            continue
        shown = 'default' if network.prefixlen == 0 else str(network)
        if not any(l.split()[:3] == [shown, 'dev', port] for l in listed):
            raise ValueError(f'{node["name"]}: the route {network} through {port} is missing in the guest.')


def change_routing(socket, old, new):
    """Bring a running guest from OLD's port addresses, static routes, gateway, OSPF, BGP and access lists to NEW's:
    only what differs changes."""
    from .vendor_config import routes
    before, after = set(routes(old)), set(routes(new))
    readdressed = sorted(p for p in new['interfaces'] if old['interfaces'].get(p) != new['interfaces'][p])
    # The routing daemons bind to addresses: a new address on a port restarts them with the new configuration.
    ospf_changed = old.get('ospf') != new.get('ospf') or bool(readdressed and new.get('ospf'))
    bgp_changed = old.get('bgp') != new.get('bgp') or bool(readdressed and new.get('bgp'))
    from .rip import process as rip_process
    rip_changed = rip_process(old) != rip_process(new)
    if rip_changed and rip_process(old):
        query(socket, 'rip-stop')  # BIRD withdraws the routes RIP installed as it stops
    from .eigrp import process as eigrp_process
    eigrp_changed = eigrp_process(old) != eigrp_process(new) or bool(readdressed and eigrp_process(new))
    if eigrp_changed and eigrp_process(old):
        query(socket, 'eigrp-stop')  # zebra withdraws EIGRP's routes as eigrpd stops
    if ospf_changed and old.get('ospf'):
        query(socket, 'ospf-stop')  # BIRD withdraws the routes it installed as it stops
    if bgp_changed and old.get('bgp'):
        query(socket, 'bgp-stop')  # zebra withdraws BGP's routes when bgpd stops
    old_down, new_down = shut_interfaces(old), shut_interfaces(new)
    for network, gateway in sorted(before - after):
        if _port(old, gateway) not in old_down:  # a route through a shut port is not in the guest
            _route(socket, old, 'route-delete', network, gateway)
    for port in sorted(set(new.get('shutdown') or []) - set(old.get('shutdown') or [])):
        query(socket, 'link', interface=port, state='down')  # Linux drops the routes through it
    for port in readdressed:  # after the routes through the old address are gone, before those through the new one
        if old['interfaces'].get(port):
            query(socket, 'address-delete', interface=port, cidr=old['interfaces'][port])
        if new['interfaces'][port]:
            query(socket, 'address-add', interface=port, cidr=new['interfaces'][port])
    from .ios_nat import public_addresses
    held = lambda node: {(port, a) for port, values in public_addresses(node).items() for a in values}
    for port, address in sorted(held(old) - held(new)):  # static NAT and pool addresses follow the IOS lines
        query(socket, 'address-delete', interface=port, cidr=address)
    for port, address in sorted(held(new) - held(old)):
        query(socket, 'address-add', interface=port, cidr=address)
    for port in sorted(set(old.get('shutdown') or []) - set(new.get('shutdown') or [])):
        query(socket, 'link', interface=port, state='up')  # « no shutdown »: the port and its routes come back
    _port_routing(socket, old, new)
    for network, gateway in sorted(after):
        port = _port(new, gateway)
        if port not in new_down and ((network, gateway) not in before or port in old_down):
            _route(socket, new, 'route-add', network, gateway)
    if ospf_changed and new.get('ospf'):
        start_ospf(socket, new)
    if bgp_changed and new.get('bgp'):
        start_bgp(socket, new)
    if rip_changed and rip_process(new):
        start_rip(socket, new)
    if eigrp_changed and eigrp_process(new):
        start_eigrp(socket, new)
    from .ios_relay import process as relay_process
    if relay_process(old) != relay_process(new):  # « ip helper-address » typed or removed
        if relay_process(old):
            query(socket, 'dhcp-relay-stop')
        if relay_process(new):
            start_relay(socket, new)
    from .acl import policy
    if old.get('role') == 'router' and policy(old) != policy(new):  # access lists or IOS NAT changed
        from .guest_firewall import apply as apply_firewall
        # No list left: an open chain (accept, no rule but the invalid-state drop every guest chain starts with).
        apply_firewall(socket, {'firewall': policy(new)})
    if observe(socket, new) != expected_profile(new):
        raise ValueError('Guest routing readback differs from the declared routes.')


def check_bgp(socket, node):
    """The guest's FRR runs the BGP configuration the lab declares, byte for byte."""
    from .bgp import config
    try:
        running = query(socket, 'bgp-show', state='config')
    except ValueError as error:
        raise ValueError(f'{node["name"]}: BGP is not running in the guest ({error}).') from error
    if running != config(node):
        raise ValueError(f'{node["name"]}: the guest BGP configuration differs from the lab.')


def start_bgp(socket, node, timeout=8):
    """Start zebra and bgpd from the typed process, then wait for vtysh to answer."""
    from .bgp import guest_process
    query(socket, 'bgp-start', bgp=guest_process(node))
    deadline = time.monotonic() + timeout
    while True:
        try:
            query(socket, 'bgp-show', state='summary')
            break
        except ValueError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.2)
    check_bgp(socket, node)


def apply(socket, node, timeout=40, alive=None):
    """Fresh boot only: wait for agent, then apply once; failures abort lab startup."""
    deadline = time.monotonic() + timeout
    while True:
        if alive is not None and not alive():
            raise ValueError('Guest VMM exited before its agent answered.')
        try:
            query(socket, 'ready')
            break
        except (OSError, ValueError):
            if time.monotonic() >= deadline: raise
            time.sleep(.1)
    if node.get('role') == 'switch':
        for port in node['interfaces']:
            # A shut port is still in the bridge (its VLANs are kept), with its link down, as « shutdown » on a Catalyst.
            query(socket, 'link', interface=port, state='down' if port in (node.get('shutdown') or []) else 'up')
            query(socket, 'bridge-add', interface=port)
        plan = vlan_plan(node)
        if plan is not None:
            try:
                query(socket, 'bridge-vlan-filtering')
            except ValueError as error:
                raise ValueError(str(error) + ' (VLANs need the Network LABS guest kernel, tools/guest_kernel)') from error
            for port in node['interfaces']:
                query(socket, 'bridge-vlan-delete', interface=port, vlan=1)  # Ports join VLAN 1 untagged by default.
            # Untagged (pvid) entries last: each one replaces the port's default VLAN.
            for port, vid, mode in sorted(plan, key=lambda entry: (entry[2] == 'pvid', entry)):
                query(socket, 'bridge-vlan-add', interface=port, vlan=vid, state=mode)
        _svi(socket, node, plan, add=True)  # interface vlan N: the management address on the bridge
        check_switch(socket, node)
        return
    for port, address in node['interfaces'].items():
        if port != 'eth0' and address:
            query(socket, 'address-add', interface=port, cidr=address)
        if port != 'eth0' or not address:
            query(socket, 'link', interface=port, state='up')
    for name, sub in node.get('subinterfaces', {}).items():
        # Router-on-a-stick: each 802.1Q subinterface rides its (already up) parent port.
        query(socket, 'vlan-add', interface=sub['parent'], vlan=sub['vlan'])
        query(socket, 'address-add', interface=name, cidr=sub['address'])
        query(socket, 'link', interface=name, state='up')
    profile = node.get('guest_network', {'addresses': [], 'routes': []})
    for address in profile['addresses']:
        query(socket, 'address-add', cidr=address)
    for port, values in profile.get('port_addresses', {}).items():
        for address in values:
            query(socket, 'address-add', interface=port, cidr=address)
    from .ios_nat import public_addresses
    for port, values in public_addresses(node).items():  # the router answers ARP for its static NAT and pool addresses
        for address in values:
            query(socket, 'address-add', interface=port, cidr=address)
    down = shut_interfaces(node)
    for port in sorted(set(node.get('shutdown') or [])):
        query(socket, 'link', interface=port, state='down')  # « shutdown »: the port stays down, its routes absent
    for route in profile['routes']:
        port = route_port(node, profile, route['gateway'])
        if port in down:
            continue
        # eth0 keeps the original request so guest images built before multi-port routes still restore.
        query(socket, 'route-add', **route, **({} if port == 'eth0' else {'interface': port}))
    _port_routing(socket, {'role': node.get('role'), 'interfaces': {}}, node)  # proxy ARP and « ip route NET MASK PORT »
    if node.get('role') == 'firewall':
        # Filter first: forwarding is never switched on before the declared policy is in place.
        from .guest_firewall import apply as apply_firewall
        apply_firewall(socket, node)
    from .acl import policy
    if node.get('role') == 'router' and (policy(node)['rules'] or policy(node)['nat']):
        # A router's access lists and IOS NAT run in its firewall chains, installed before forwarding starts.
        from .guest_firewall import apply as apply_firewall
        apply_firewall(socket, {'firewall': policy(node)})
    if node.get('role') in ('router', 'firewall'):
        query(socket, 'forward', state='on')
    if node.get('dhcp_server'):
        port = node['dhcp_server']['interface']
        query(socket, 'dhcp-serve', interface=port, dhcp=dhcp_pool(node))
        # The daemon writes its pid file just after the request returns: wait for it before reading back.
        started = time.monotonic() + 5
        while True:
            try: leases(socket, port); break
            except ValueError:
                if time.monotonic() >= started: raise
                time.sleep(.1)
    if node.get('ospf'):
        start_ospf(socket, node)
    if node.get('bgp'):
        start_bgp(socket, node)
    from .rip import process as rip_process
    if rip_process(node):
        start_rip(socket, node)
    if _runs_eigrp(node):
        start_eigrp(socket, node)
    from .ios_relay import process as relay_process
    if relay_process(node):  # « ip helper-address »: relays even before the server's guest boots
        start_relay(socket, node)
    for port in node.get('dhcp_clients', []):
        # Started, not awaited: the server may be a guest that boots later in this lab.
        query(socket, 'dhcp-client', interface=port)
    if observe(socket, node) != expected_profile(node):
        raise ValueError('Guest startup readback differs from saved configuration.')


def save_observed(manager):
    """Explicit capture for VM-only labs; existing general save remains declarative."""
    from .spec import validate
    from .persistence import save_startup, startup_path
    manager.state = None
    state = manager.read()
    if state['phase'] != 'running' or any(n['runtime'] != 'firecracker' for n in state['spec']['nodes']):
        raise ValueError('microvm-save requires a running VM-only lab.')
    candidate = copy.deepcopy(state['spec'])
    for node in candidate['nodes']:
        if node['role'] == 'switch':  # Nothing to capture: the bridge is rebuilt from the declared ports.
            check_switch(manager.directory / node['name'] / 'guest.vsock', node); continue
        node['guest_network'] = observe(manager.directory / node['name'] / 'guest.vsock', node)
    candidate = validate(candidate)
    # Re-read before publishing: do not accept drift across the capture window.
    for node in candidate['nodes']:
        if node['role'] == 'switch':
            check_switch(manager.directory / node['name'] / 'guest.vsock', node); continue
        if observe(manager.directory / node['name'] / 'guest.vsock', node) != node['guest_network']:
            raise ValueError('Guest changed during save; no startup configuration written.')
    save_startup(manager.name, candidate)
    return {'saved': str(startup_path(manager.name)), 'scope': 'Observed extra IPv4 addresses and on-link static routes on every declared port, plus declared primary addresses; interfaces up. No disk snapshot or IPv6 persistence.'}
