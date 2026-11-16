"""Local DNS through a real dnsmasq process inside OCI, without upstream forwarding."""
import ipaddress
import re
from pathlib import Path

from .lan import addresses
from .spec import integer, keys
from .service_config import observe_config

BINARY = '/usr/sbin/dnsmasq'


def name(value):
    if not isinstance(value, str):
        raise ValueError('DNS name must be ASCII text.')
    value = value.lower().removesuffix('.')
    if len(value) > 253 or '.' not in value or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in value.split('.')):
        raise ValueError('DNS names require valid ASCII hostname labels and a domain, without wildcards.')
    return value


def ipv4(value):
    if not isinstance(value, str):
        raise ValueError('DNS IPv4 address must be text.')
    address = ipaddress.IPv4Address(value)
    if address.is_unspecified or address.is_multicast or address.is_loopback or int(address) == 0xffffffff:
        raise ValueError('DNS requires a nonzero unicast IPv4 address.')
    return str(address)


def resolver_address(value):
    if not isinstance(value, str) or ':' not in value: return ipv4(value)
    if '%' in value: raise ValueError('IPv6 resolver must not have a zone.')
    address = ipaddress.IPv6Address(value)
    if address.is_unspecified or address.is_multicast or address.is_loopback or address.is_link_local or address.ipv4_mapped:
        raise ValueError('DNS resolver requires a remote unicast IPv6 address.')
    return str(address)


def validate_dns(node):
    resolvers = node.setdefault('resolvers', [])
    if not isinstance(resolvers, list) or len(resolvers) > 3:
        raise ValueError('resolvers must be an array of at most three literal IP addresses.')
    node['resolvers'] = [resolver_address(value) for value in resolvers]
    if any(':' in value for value in node['resolvers']) and (node['role'] != 'host' or set(node['interfaces']) != {'eth0'} or not node.get('ipv6', {}).get('eth0')):
        raise ValueError('IPv6 resolvers require a statically numbered single-interface OCI IPv6 host.')
    if len(set(node['resolvers'])) != len(resolvers):
        raise ValueError('Duplicate DNS resolver.')
    if resolvers and (node['runtime'] != 'oci' or node.get('dhcp_clients') or node['role'] == 'switch' or node.get('startup')):
        raise ValueError('Static resolvers require an OCI endpoint without DHCP clients or untracked startup; DHCP owns its own resolver file.')
    policy = node.setdefault('dns_server', None)
    if policy is None:
        return
    keys(policy, ('interface', 'zone', 'records', 'ttl', 'records_ipv6', 'listen_ipv6'), 'DNS server')
    if node['runtime'] != 'oci' or node['role'] == 'switch' or node.get('startup'):
        raise ValueError('DNS requires an OCI numbered endpoint without untracked startup commands.')
    interface = policy.get('interface')
    ipv6_only = (policy.get('listen_ipv6') is True and node['role']=='host' and
                 set(node['interfaces'])=={'eth0'} and interface=='eth0' and
                 node.get('ipv6',{}).get(interface) and not addresses(node).get(interface))
    if not isinstance(interface, str) or (not addresses(node).get(interface) and not ipv6_only):
        raise ValueError('DNS server requires a declared static numbered interface.')
    if not ipv6_only:
        local = ipaddress.IPv4Interface(addresses(node)[interface])
        ipv4(str(local.ip))
        if local.network.prefixlen < 31 and local.ip in (local.network.network_address, local.network.broadcast_address):
            raise ValueError('DNS listen address cannot be a subnet network/broadcast address.')
    policy['zone'] = zone = name(policy.get('zone'))
    integer(policy.setdefault('ttl', 60), 0, 86400, 'DNS record TTL')
    records = policy.get('records')
    if not isinstance(records, dict) or len(records) > 256:
        raise ValueError('DNS records requires an explicit map of at most 256 hostname/IPv4 records.')
    normalized = {}
    for host, address in records.items():
        host = name(host)
        if host != zone and not host.endswith('.' + zone):
            raise ValueError('DNS records must belong to the declared local zone.')
        if host in normalized:
            raise ValueError('Duplicate DNS name after normalization.')
        normalized[host] = ipv4(address)
    # One name per address gives deterministic automatic reverse PTR records.
    if len(set(normalized.values())) != len(normalized):
        raise ValueError('Initial DNS profile requires unique IPv4 addresses; CNAME/multiple PTRs are not exposed.')
    policy['records'] = dict(sorted(normalized.items()))
    records6 = policy.get('records_ipv6', {})
    if not isinstance(records6, dict) or len(records6) > 256:
        raise ValueError('DNS records_ipv6 requires at most 256 hostname/IPv6 records.')
    normalized6 = {}
    for host, value in records6.items():
        host = name(host)
        if host != zone and not host.endswith('.' + zone):
            raise ValueError('DNS AAAA records must belong to the local zone.')
        if host in normalized6 or not isinstance(value, str) or '%' in value:
            raise ValueError('Duplicate DNS AAAA name or invalid unscoped IPv6 address.')
        address = ipaddress.IPv6Address(value)
        if address.is_unspecified or address.is_loopback or address.is_multicast or address.is_link_local or address.ipv4_mapped:
            raise ValueError('DNS AAAA requires a nonlocal unicast IPv6 address.')
        normalized6[host] = str(address)
    if len(set(normalized6.values())) != len(normalized6):
        raise ValueError('DNS AAAA requires unique IPv6 addresses for deterministic PTRs.')
    if not normalized and not normalized6:
        raise ValueError('DNS requires at least one explicit A or AAAA record.')
    if 'records_ipv6' in policy: policy['records_ipv6'] = dict(sorted(normalized6.items()))
    listen6 = policy.get('listen_ipv6', False)
    if type(listen6) is not bool or (listen6 and (node['role'] != 'host' or set(node['interfaces']) != {'eth0'} or interface != 'eth0' or not node.get('ipv6', {}).get(interface))):
        raise ValueError('DNS listen_ipv6 requires a statically numbered single-interface OCI IPv6 host.')
    if len(server_config(node).encode('utf-8')) > 65536:
        raise ValueError('DNS configuration exceeds the 64 KiB observable file budget.')


def server_config(node):
    policy = node['dns_server']
    local = addresses(node).get(policy['interface'])
    lines = ['port=53', 'bind-interfaces',
             'no-resolv', 'no-hosts', 'no-poll', 'cache-size=0',
             'local=/' + policy['zone'] + '/', 'local-ttl=' + str(policy['ttl']),
             'pid-file=/run/dnsmasq.pid', 'user=root', 'group=root', 'log-facility=-']
    if local: lines.insert(2,'listen-address=' + str(ipaddress.IPv4Interface(local).ip))
    if policy.get('listen_ipv6'):
        lines.append('listen-address=' + str(ipaddress.IPv6Interface(node['ipv6'][policy['interface']]).ip))
    records6 = policy.get('records_ipv6', {})
    for host in sorted(set(policy['records']) | set(records6)):
        values = [host] + [records[host] for records in (policy['records'], records6) if host in records] + [str(policy['ttl'])]
        lines.append('host-record=' + ','.join(values))
    return '\n'.join(lines) + '\n'


def resolver_config(node):
    return ''.join('nameserver ' + address + '\n' for address in node['resolvers'])


def prepare_files(bundle, node):
    folder = Path(bundle) / 'files'
    if node.get('dns_server') is not None:
        (folder / 'dnsmasq.conf').write_text(server_config(node))
    if node.get('resolvers'):
        (folder / 'resolv.conf').write_text(resolver_config(node))


def start_servers(manager):
    for index, node in enumerate(manager.state['spec']['nodes']):
        if node.get('dns_server') is not None:
            if node['dns_server'].get('listen_ipv6'):
                from .ipv6 import wait_addresses
                wait_addresses(manager, index, node)
            manager.crun('exec', node['name'], BINARY, '--test', '--conf-file=/lab/dnsmasq.conf',
                         log=manager.directory / node['name'] / 'dns.log')
            manager.crun('exec', '--detach', node['name'], BINARY, '--keep-in-foreground', '--conf-file=/lab/dnsmasq.conf',
                         log=manager.directory / node['name'] / 'dns.log')


def observe_server(manager, index, node):
    observation = observe_config(manager, node['name'], '/lab/dnsmasq.conf', server_config(node))
    # ss observes sockets, not process health or successful name resolution.
    listeners = manager.ns(index, 'ss', '-H', '-lntu', '( sport = :53 )', check=False)
    return {**observation, 'source': 'Container dnsmasq config and kernel DNS listener snapshot',
            'zone': node['dns_server']['zone'], 'records': node['dns_server']['records'],
            'records_ipv6': node['dns_server'].get('records_ipv6', {}), 'listen_ipv6': node['dns_server'].get('listen_ipv6', False),
            'listener_snapshot': listeners.stdout.splitlines() if listeners.returncode == 0 else None,
            'note': 'File conformity/listening sockets do not prove DNS answers. Local static records only; no upstream, DNSSEC, dynamic registration, or cache snapshot.'}


def observe_resolver(manager, node):
    return {**observe_config(manager, node['name'], '/etc/resolv.conf', resolver_config(node)),
            'source': 'Managed static resolver file in container', 'nameservers': node['resolvers']}
