"""IPv4 client LANs relayed by a real in-container dnsmasq process."""
import ipaddress
from pathlib import Path

from .spec import keys
from .service_config import observe_config

BINARY = '/usr/sbin/dnsmasq'


def rules(node):
    policy = node.get('dhcp_relay')
    return [] if policy is None else (policy if isinstance(policy, list) else [policy])


def validate_relay(node):
    policy = node.setdefault('dhcp_relay', None)
    if policy is None:
        return
    entries = rules(node)
    if not 1 <= len(entries) <= 32:
        raise ValueError('DHCP relay requires 1..32 client-interface policies.')
    clients = set()
    for entry in entries:
        _validate_rule(node, entry)
        if entry['interface'] in clients:
            raise ValueError('Only one helper per client interface is supported.')
        clients.add(entry['interface'])
    if clients.intersection(entry['upstream_interface'] for entry in entries):
        raise ValueError('Relay client and upstream interfaces must be disjoint across policies.')
    if isinstance(policy, list):
        node['dhcp_relay'] = entries[0] if len(entries) == 1 else sorted(entries, key=lambda entry: entry['interface'])


def _validate_rule(node, policy):
    from .lan import addresses
    keys(policy, ('interface', 'server', 'upstream_interface'), 'DHCP relay')
    if node['runtime'] != 'oci' or node['role'] not in ('router', 'switch') or node.get('switch_backend', 'linux') != 'linux' or not node['forwarding']:
        raise ValueError('DHCP relay requires a forwarding OCI router or Linux L3 switch.')
    if any((node.get('startup'), node.get('dhcp_server'), node.get('dhcp_pools'), node.get('dhcp_clients'), node.get('dns_server'),
            (node.get('dhcp_snooping') or {}).get('enabled'), node.get('arp_inspection'), node.get('ip_source_guard'))):
        raise ValueError('Initial DHCP relay profile excludes untracked startup, DHCP/DNS services and DHCP snooping/ARP/IP source guards on the relay node.')
    local = addresses(node)
    interfaces = [policy.get('interface'), policy.get('upstream_interface')]
    if any(not isinstance(name, str) or not local.get(name) or name in node['shutdown'] or
           (node['role'] == 'switch' and name not in node['svis']) for name in interfaces) or interfaces[0] == interfaces[1]:
        raise ValueError('DHCP relay needs two distinct UP static routed interfaces or SVIs.')
    client, upstream = (ipaddress.IPv4Interface(local[name]) for name in interfaces)
    if client.network.overlaps(upstream.network):
        raise ValueError('DHCP relay client and upstream networks must be disjoint.')
    if client.network.prefixlen >= 31 or client.ip in (client.network.network_address, client.network.broadcast_address) or client.ip.is_multicast or client.ip.is_loopback or client.ip.is_unspecified:
        raise ValueError('DHCP relay client address must be usable on a broadcast IPv4 subnet.')
    if not isinstance(policy.get('server'), str):
        raise ValueError('DHCP relay server must be IPv4 text.')
    server = ipaddress.IPv4Address(policy['server'])
    if server.is_unspecified or server.is_multicast or server.is_loopback or server not in upstream.network or (upstream.network.prefixlen < 31 and server in (upstream.network.network_address, upstream.network.broadcast_address)) or any(value and server == ipaddress.IPv4Interface(value).ip for value in local.values()):
        raise ValueError('DHCP relay server must be a usable on-link upstream peer.')
    policy['server'] = str(server)


def server_config(node):
    from .lan import addresses
    lines = ['port=0', 'no-resolv', 'no-hosts', 'bind-interfaces']
    interfaces = sorted({entry[key] for entry in rules(node) for key in ('interface', 'upstream_interface')})
    lines += ['interface=' + name for name in interfaces]
    for policy in rules(node):
        local = str(ipaddress.IPv4Interface(addresses(node)[policy['interface']]).ip)
        lines.append(f'dhcp-relay={local},{policy["server"]},{policy["upstream_interface"]}')
    return '\n'.join(lines + ['pid-file=/run/dhcp-relay.pid', 'user=root', 'group=root', 'log-facility=-', 'log-dhcp']) + '\n'


def prepare_files(bundle, node):
    if node.get('dhcp_relay') is not None:
        (Path(bundle) / 'files' / 'dhcp-relay.conf').write_text(server_config(node))


def start_servers(manager):
    for node in manager.state['spec']['nodes']:
        if node.get('dhcp_relay') is not None:
            for args in (('--test',), ('--keep-in-foreground',)):
                command = ['exec'] + ([] if args == ('--test',) else ['--detach'])
                manager.crun(*command, node['name'], BINARY, *args, '--conf-file=/lab/dhcp-relay.conf',
                             log=manager.directory / node['name'] / 'dhcp-relay.log')


def observe(manager, index, node):
    result = observe_config(manager, node['name'], '/lab/dhcp-relay.conf', server_config(node))
    sockets = manager.ns(index, 'ss', '-H', '-lun', '( sport = :67 )', check=False)
    return {**result, 'source': 'Managed dnsmasq relay config and actual UDP socket snapshot',
            'policy': node['dhcp_relay'], 'listener_snapshot': sockets.stdout.splitlines() if sockets.returncode == 0 else None,
            'note': 'File/socket observations do not prove a running/loaded relay or successful leases. No DHCPv6, Option 82 or multiple servers per client interface. Live adapter supports helper-only edits.'}


def configure_helper(node, interface, server, remove=False):
    """Resolve this bounded helper profile from directly connected addresses."""
    from .lan import addresses
    server = str(ipaddress.IPv4Address(server))
    entries = rules(node)
    current = next((entry for entry in entries if entry['interface'] == interface), None)
    if remove:
        entries = [entry for entry in entries if not (entry['interface'] == interface and entry['server'] == server)]
        node['dhcp_relay'] = entries[0] if len(entries) == 1 else (entries or None)
        return
    if current and current['server'] != server:
        raise ValueError('Only one helper per interface is supported; remove the existing helper explicitly first.')
    upstream = [name for name, address in addresses(node).items()
                if address and name != interface and ipaddress.IPv4Address(server) in ipaddress.IPv4Interface(address).network
                and (node['role'] != 'switch' or name in node.get('svis', {}))]
    if len(upstream) != 1:
        raise ValueError('Helper requires exactly one directly connected upstream routed interface or SVI.')
    entries = [entry for entry in entries if entry['interface'] != interface]
    entries.append({'interface': interface, 'server': server, 'upstream_interface': upstream[0]})
    node['dhcp_relay'] = entries[0] if len(entries) == 1 else sorted(entries, key=lambda entry: entry['interface'])


def validate_change(node, previous):
    if {k: v for k, v in node.items() if k != 'dhcp_relay'} != {k: v for k, v in previous.items() if k != 'dhcp_relay'}:
        raise ValueError('DHCP relay service adapter accepts helper-only edits; recreate the lab for other network changes.')


# Identify by executable AND exact argv in the container PID namespace. A stale
# or tampered pidfile must never select an unrelated process, including PID 1.
PROCESS_SCRIPT = r'''for proc in /proc/[0-9]*; do
    [ "$(/bin/busybox readlink "$proc/exe" 2>/dev/null)" = /usr/sbin/dnsmasq ] || continue
    /bin/busybox tr '\000' '\n' < "$proc/cmdline" | /bin/busybox grep -Fxq -- '--conf-file=/lab/dhcp-relay.conf' || continue
    pid=${proc##*/}
    [ "$pid" -gt 1 ] || continue
    if [ "$1" = stop ]; then /bin/busybox kill -TERM "$pid" || exit 1; else echo "$pid"; fi
done
'''


def processes(manager, node, action='list'):
    return manager.crun('exec', node['name'], '/bin/sh', '-c', PROCESS_SCRIPT, 'relay-control', action, timeout=3).stdout.splitlines()


def preflight_change(manager, node, previous):
    from .runtime import RuntimeFailure
    validate_change(node, previous)
    if previous.get('dhcp_relay') and not observe_config(manager, node['name'], '/lab/dhcp-relay.conf', server_config(previous))['configuration_verified']:
        raise RuntimeFailure('DHCP relay configuration drift; refusing live change.')
    if node.get('dhcp_relay'):
        manager.crun('exec', node['name'], '/bin/busybox', 'test', '-x', BINARY, timeout=3)


def start_one(manager, node):
    from .runtime import RuntimeFailure
    import time
    manager.crun('exec', node['name'], BINARY, '--test', '--conf-file=/lab/dhcp-relay.conf', timeout=3)
    manager.crun('exec', '--detach', node['name'], BINARY, '--keep-in-foreground', '--conf-file=/lab/dhcp-relay.conf',
                 log=manager.directory / node['name'] / 'dhcp-relay.log')
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        # dnsmasq writes its pidfile after binding sockets. Cross-check it against
        # the observed executable/argv, never use its contents as a kill target.
        pids = processes(manager, node)
        pidfile = manager.crun('exec', node['name'], '/bin/cat', '/run/dhcp-relay.pid', check=False, timeout=3)
        if len(pids) == 1 and pidfile.returncode == 0 and pidfile.stdout.strip() == pids[0]:
            return
        time.sleep(0.05)
    raise RuntimeFailure('DHCP relay process did not become ready; inspect dhcp-relay.log.')


def apply_change(manager, index, node, previous):
    """Restart only the relay, preserving links, addresses and existing leases."""
    from .runtime import RuntimeFailure
    import time
    validate_change(node, previous)
    processes(manager, node, 'stop')
    deadline = time.monotonic() + 3
    while processes(manager, node):
        if time.monotonic() >= deadline:
            raise RuntimeFailure('DHCP relay did not stop.')
        time.sleep(0.05)
    # Remove stale pidfiles only after process identity checks/termination.
    manager.crun('exec', node['name'], '/bin/busybox', 'rm', '-f', '/run/dhcp-relay.pid', timeout=3)
    path = manager.directory / node['name'] / 'files' / 'dhcp-relay.conf'
    if node.get('dhcp_relay'):
        temporary = path.with_suffix('.conf.new')
        temporary.write_text(server_config(node))
        temporary.replace(path)
        start_one(manager, node)
    else:
        path.unlink(missing_ok=True)
