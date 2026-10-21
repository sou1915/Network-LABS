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


def validate_dns(node):
    resolvers = node.setdefault('resolvers', [])
    if not isinstance(resolvers, list) or len(resolvers) > 3:
        raise ValueError('resolvers must be an array of at most three IPv4 addresses.')
    node['resolvers'] = [ipv4(value) for value in resolvers]
    if len(set(node['resolvers'])) != len(resolvers):
        raise ValueError('Duplicate DNS resolver.')
    if resolvers and (node['runtime'] != 'oci' or node.get('dhcp_clients') or node['role'] == 'switch' or node.get('startup')):
        raise ValueError('Static resolvers require an OCI endpoint without DHCP clients or untracked startup; DHCP owns its own resolver file.')
    policy = node.setdefault('dns_server', None)
    if policy is None:
        return
    keys(policy, ('interface', 'zone', 'records', 'ttl'), 'DNS server')
    if node['runtime'] != 'oci' or node['role'] == 'switch' or node.get('startup'):
        raise ValueError('DNS requires an OCI numbered endpoint without untracked startup commands.')
    interface = policy.get('interface')
    if not isinstance(interface, str) or not addresses(node).get(interface):
        raise ValueError('DNS server requires a declared static numbered interface.')
    local = ipaddress.IPv4Interface(addresses(node)[interface])
    ipv4(str(local.ip))
    if local.network.prefixlen < 31 and local.ip in (local.network.network_address, local.network.broadcast_address):
        raise ValueError('DNS listen address cannot be a subnet network/broadcast address.')
    policy['zone'] = zone = name(policy.get('zone'))
    integer(policy.setdefault('ttl', 60), 0, 86400, 'DNS record TTL')
    records = policy.get('records')
    if not isinstance(records, dict) or not 1 <= len(records) <= 256:
        raise ValueError('DNS requires 1..256 explicit hostname/IPv4 records.')
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


def server_config(node):
    policy = node['dns_server']
    local = str(ipaddress.IPv4Interface(addresses(node)[policy['interface']]).ip)
    lines = ['port=53', 'bind-interfaces', 'listen-address=' + local,
             'no-resolv', 'no-hosts', 'no-poll', 'cache-size=0',
             'local=/' + policy['zone'] + '/', 'local-ttl=' + str(policy['ttl']),
             'pid-file=/run/dnsmasq.pid', 'user=root', 'group=root', 'log-facility=-']
    for host, address in policy['records'].items():
        lines.append(f'host-record={host},{address},{policy["ttl"]}')
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
    for node in manager.state['spec']['nodes']:
        if node.get('dns_server') is not None:
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
            'listener_snapshot': listeners.stdout.splitlines() if listeners.returncode == 0 else None,
            'note': 'File conformity/listening sockets do not prove DNS answers. Local static records only; no upstream, DNSSEC, dynamic registration, or cache snapshot.'}


def observe_resolver(manager, node):
    return {**observe_config(manager, node['name'], '/etc/resolv.conf', resolver_config(node)),
            'source': 'Managed static resolver file in container', 'nameservers': node['resolvers']}
