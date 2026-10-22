"""Bounded OSPFv2 area-zero profile backed by a real BIRD 2 daemon."""
import ipaddress
import re
import subprocess
import time
from pathlib import Path

from .spec import keys, integer
from .service_config import observe_config

DAEMON = '/usr/sbin/bird'
CLIENT = '/usr/sbin/birdc'


def rootfs_assets(daemon, client):
    from .dns_rootfs import assets
    planned = assets(daemon, destination=DAEMON, identity='bird version 2.')
    # birdc has no --version; its documented control-client usage exits 1.
    planned += assets(client, destination=CLIENT, identity='BIRD control client', version_args=('-h',),
                      version_check=lambda result: result.returncode == 1 and '[-s <control-socket>] [-v] [-r]' in result.stderr)
    return sorted(set(planned), key=lambda item: str(item[1]))


def validate_ospf(node):
    policy = node.setdefault('ospf', None)
    if policy is None:
        return
    keys(policy, ('router_id', 'interfaces', 'hello', 'dead'), 'OSPF')
    if node['runtime'] != 'oci' or node['role'] != 'router' or not node['forwarding']:
        raise ValueError('OSPF requires a forwarding OCI router.')
    if any(node.get(key) for key in ('startup', 'routes', 'gateway', 'subinterfaces', 'port_channels', 'dhcp_clients',
                                     'dhcp_server', 'dhcp_pools', 'dhcp_relay', 'dns_server', 'lldp', 'firewall')):
        raise ValueError('Initial OSPF profile excludes static/default routes, subinterfaces, bundles and other managed services.')
    value = policy.get('router_id')
    if not isinstance(value, str):
        raise ValueError('OSPF router_id must be IPv4 text.')
    router_id = ipaddress.IPv4Address(value)
    if router_id.is_unspecified or router_id.is_multicast or router_id.is_reserved or router_id.is_loopback:
        raise ValueError('OSPF router_id must be usable unicast IPv4.')
    ports = policy.get('interfaces')
    if not isinstance(ports, dict) or not 1 <= len(ports) <= 16:
        raise ValueError('OSPF requires 1..16 physical interfaces.')
    networks = []
    for name, port in ports.items():
        keys(port, ('cost', 'passive'), 'OSPF interface')
        if name not in node['interfaces'] or not node['interfaces'][name] or name in node['shutdown']:
            raise ValueError('OSPF interfaces must be UP and statically numbered.')
        local = ipaddress.IPv4Interface(node['interfaces'][name])
        if not 1 <= local.network.prefixlen <= 30 or local.ip in (local.network.network_address, local.network.broadcast_address) or local.ip.is_multicast or local.ip.is_reserved or local.ip.is_loopback or local.ip.is_unspecified:
            raise ValueError('OSPF interface needs usable IPv4 on a prefix 1..30 subnet.')
        if any(local.network.overlaps(network) for network in networks):
            raise ValueError('OSPF interface subnets must not overlap.')
        networks.append(local.network)
        integer(port.setdefault('cost', 10), 1, 65535, 'OSPF cost')
        if type(port.setdefault('passive', False)) is not bool:
            raise ValueError('OSPF passive must be boolean.')
    if all(port['passive'] for port in ports.values()):
        raise ValueError('OSPF requires at least one active transit interface.')
    integer(policy.setdefault('hello', 1), 1, 60, 'OSPF hello')
    integer(policy.setdefault('dead', 4), 2, 240, 'OSPF dead')
    if policy['dead'] <= policy['hello']:
        raise ValueError('OSPF dead must exceed hello.')
    policy['router_id'] = str(router_id)
    policy['interfaces'] = dict(sorted(ports.items()))


def config(node):
    policy = node['ospf']
    lines = [f'router id {policy["router_id"]};', 'log stderr all;', 'protocol device { scan time 1; }',
             'protocol kernel kernel4 { scan time 1; ipv4 { import none; export where source = RTS_OSPF; }; }',
             'protocol ospf v2 ospf4 {', '  ipv4 { import where source = RTS_OSPF; export none; };',
             '  ecmp no;', '  area 0.0.0.0 {']
    for name, port in policy['interfaces'].items():
        lines.append(f'    interface "{name}" {{ type ptp; cost {port["cost"]}; stub {"yes" if port["passive"] else "no"}; hello {policy["hello"]}; dead {policy["dead"]}; }};')
    return '\n'.join(lines + ['  };', '}']) + '\n'


def prepare_files(bundle, node):
    if node.get('ospf') is not None:
        (Path(bundle) / 'files/bird.conf').write_text(config(node))


def read_cli(manager, name, command):
    # All call sites use fixed show commands. Bound output inside the container;
    # pipefail prevents a failed client from becoming an apparently empty RIB.
    try:
        result = manager.crun('exec', name, '/bin/sh', '-c',
            'set -o pipefail; /usr/sbin/birdc -v -r -s /run/bird.ctl "$@" | /bin/busybox head -c 65537',
            'bird-observer', *command.split(), check=False, timeout=3)
        if result.returncode or len(result.stdout) > 65536 or re.search(r'(?m)^[89]\d{3}', result.stdout):
            return None
        return result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def start_servers(manager):
    from .runtime import RuntimeFailure
    for node in manager.state['spec']['nodes']:
        if node.get('ospf') is None:
            continue
        manager.crun('exec', node['name'], DAEMON, '-p', '-c', '/lab/bird.conf', timeout=3)
        manager.crun('exec', '--detach', node['name'], DAEMON, '-f', '-c', '/lab/bird.conf',
                     '-s', '/run/bird.ctl', '-P', '/run/bird.pid', log=manager.directory / node['name'] / 'ospf.log')
        deadline = time.monotonic() + 5
        while read_cli(manager, node['name'], 'show status') is None:
            if time.monotonic() >= deadline:
                raise RuntimeFailure(node['name'] + ': BIRD control socket did not become available.')
            time.sleep(0.1)


def observe(manager, node):
    result = observe_config(manager, node['name'], '/lab/bird.conf', config(node))
    return {**result, 'source': 'BIRD 2 control socket and managed config file',
            'neighbors': read_cli(manager, node['name'], 'show ospf neighbors'),
            'protocol': read_cli(manager, node['name'], 'show protocols all ospf4'),
            'routes': read_cli(manager, node['name'], 'show route protocol ospf4 all'),
            'note': 'Actual daemon text; file conformity does not prove loaded policy or convergence. Kernel routes are observed separately. Single area 0, IPv4 point-to-point/passive interfaces only.'}


def dynamic_route(node, route):
    return node.get('ospf') is not None and route.get('protocol') in ('bird', 192, '192')
