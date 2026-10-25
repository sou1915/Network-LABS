"""Kernel RA clients and real dnsmasq RA-only/stateful advertisements on physical LANs."""
from pathlib import Path
import json

from .service_config import observe_config

BINARY = '/usr/sbin/dnsmasq'
CLIENT_SYSCTLS = {'disable_ipv6': 0, 'forwarding': 0, 'accept_ra': 1, 'autoconf': 1,
                 'accept_ra_defrtr': 1, 'accept_ra_pinfo': 1, 'use_tempaddr': 0,
                 'addr_gen_mode': 0, 'accept_dad': 1, 'router_solicitations': 3,
                 'router_solicitation_interval': 1}


def validate_node(node):
    clients = node.setdefault('slaac', [])
    advertisers = node.setdefault('router_advertisements', [])
    for values in (clients, advertisers):
        if not isinstance(values, list) or len(values) > 16 or any(not isinstance(p, str) or p not in node['interfaces'] for p in values) or len(values) != len(set(values)):
            raise ValueError('SLAAC/RA requires unique declared physical interface names, at most 16.')
    if clients and (node['runtime'] != 'oci' or node['role'] != 'host' or len(clients) != 1 or set(node['interfaces']) != set(clients) or node['ipv6'] or node['ipv6_routes'] or node['ipv6_forwarding']):
        raise ValueError('Initial SLAAC client requires one physical OCI host interface without static IPv6 or routes.')
    if advertisers and (node['runtime'] != 'oci' or node['role'] != 'router' or not node['ipv6_forwarding'] or any(p not in node['ipv6'] for p in advertisers)):
        raise ValueError('RA requires an IPv6-forwarding OCI router with numbered physical /64 interfaces.')
    if any(p in node.get('shutdown', []) for p in clients + advertisers):
        raise ValueError('SLAAC and RA interfaces must be administratively UP.')


def client_settings(node):
    return {**CLIENT_SYSCTLS, 'autoconf': 0} if node['dhcpv6_clients'] else CLIENT_SYSCTLS


def configure_client(manager, index, node):
    if not (node['slaac'] or node['dhcpv6_clients']):
        return
    manager.ns(index, 'sysctl', '-w', 'net/ipv6/conf/all/forwarding=0')
    for port in node['slaac'] + node['dhcpv6_clients']:
        for key, value in client_settings(node).items():
            manager.ns(index, 'sysctl', '-w', 'net/ipv6/conf/' + port + '/' + key + '=' + str(value))


def server_config(node):
    lines = ['port=0', 'no-resolv', 'no-hosts', 'bind-interfaces', 'enable-ra',
             'dhcp-option=option6:dns-server', 'pid-file=/run/ra.pid', 'user=root', 'group=root',
             'log-facility=-', 'log-dhcp']
    for port in sorted(node['router_advertisements']):
        pool = node['dhcpv6_server']
        address_range = (pool['start'] + ',' + pool['end'] + ',64,' + str(pool['lease_seconds']) + 's'
                         if pool and pool['interface'] == port else '::,constructor:' + port + ',ra-only,64,2h')
        lines += ['interface=' + port, 'dhcp-range=' + address_range, 'ra-param=' + port + ',5,15']
    if node['dhcpv6_server']:
        lines.append('dhcp-leasefile=/run/dhcpv6.leases')
    return '\n'.join(lines) + '\n'


def prepare_files(bundle, node):
    if node['router_advertisements']:
        (Path(bundle) / 'files/ra.conf').write_text(server_config(node))


def start_servers(manager):
    for node in manager.state['spec']['nodes']:
        if not node['router_advertisements']:
            continue
        for args in (('--test',), ('--keep-in-foreground',)):
            command = ['exec'] + ([] if args == ('--test',) else ['--detach'])
            manager.crun(*command, node['name'], BINARY, *args, '--conf-file=/lab/ra.conf',
                         log=manager.directory / node['name'] / 'ra.log')


def observe_server(manager, node):
    return {**observe_config(manager, node['name'], '/lab/ra.conf', server_config(node)),
            'interfaces': node['router_advertisements'], 'source': 'Managed dnsmasq RA/DHCPv6 config file',
            'note': 'File conformity does not prove a loaded policy, actual advertisements or client readiness. No DNS service; DHCPv6 only when an explicit pool is declared.'}


def drift(manager, index, node):
    errors = []
    for port in node['slaac'] + node['dhcpv6_clients']:
        for key, expected in client_settings(node).items():
            value = manager.ns(index, 'sysctl', '-n', 'net/ipv6/conf/' + port + '/' + key, timeout=3).stdout.strip()
            if value != str(expected):
                errors.append(node['name'] + '/' + port + ': IPv6 RA client ' + key + ' differs')
    if node['slaac'] or node['dhcpv6_clients']:
        value = manager.ns(index, 'sysctl', '-n', 'net/ipv6/conf/all/forwarding', timeout=3).stdout.strip()
        if value != '0':
            errors.append(node['name'] + ': IPv6 RA client global forwarding differs')
        routes = json.loads(manager.ns(index, 'ip', '-j', '-6', 'route', 'show', 'table', 'main', timeout=3).stdout)
        if any(r.get('protocol') not in ('kernel', 'ra') for r in routes):
            errors.append(node['name'] + ': unmanaged non-RA IPv6 client route')
    if node['router_advertisements'] and not observe_server(manager, node)['configuration_verified']:
        errors.append(node['name'] + ': RA configuration differs or is unavailable')
    return errors
