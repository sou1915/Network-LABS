"""Single-area OSPFv3 on static physical IPv6 routers, using BIRD 2."""
import ipaddress
from pathlib import Path

from .spec import integer, keys
from .ospf import read_cli, start_one
from .service_config import observe_config


def validate_node(node):
    policy = node.setdefault('ospfv3', None)
    if policy is None:
        return
    keys(policy, ('router_id', 'interfaces', 'hello', 'dead'), 'OSPFv3')
    if (node['runtime'] != 'oci' or node['role'] != 'router' or not node['ipv6_forwarding'] or
            node.get('ospf') or node['ipv6_routes'] or node['forwarding'] or
            any(node['interfaces'].values()) or node.get('slaac') or node.get('router_advertisements') or
            node.get('dhcpv6_clients') or node.get('dhcpv6_server')):
        raise ValueError('OSPFv3 requires a static IPv6-only physical OCI router without other routing services.')
    value = policy.get('router_id')
    if not isinstance(value, str):
        raise ValueError('OSPFv3 router_id requires usable IPv4 text.')
    router_id = ipaddress.IPv4Address(value)
    if (router_id.is_unspecified or router_id.is_multicast or router_id.is_reserved or
            router_id.is_loopback or int(router_id) == 0xffffffff):
        raise ValueError('OSPFv3 router_id requires usable IPv4 text.')
    integer(policy.setdefault('hello', 1), 1, 60, 'OSPFv3 hello')
    integer(policy.setdefault('dead', 4), 2, 240, 'OSPFv3 dead')
    if policy['dead'] <= policy['hello']:
        raise ValueError('OSPFv3 dead must exceed hello.')
    ports = policy.get('interfaces')
    if not isinstance(ports, dict) or not 1 <= len(ports) <= 16:
        raise ValueError('OSPFv3 requires 1..16 numbered physical interfaces.')
    for name, options in ports.items():
        keys(options, ('cost', 'passive'), 'OSPFv3 interface')
        if name not in node['ipv6'] or name in node['shutdown']:
            raise ValueError('OSPFv3 interfaces must be UP and statically numbered with IPv6.')
        integer(options.setdefault('cost', 10), 1, 65535, 'OSPFv3 cost')
        if type(options.setdefault('passive', False)) is not bool:
            raise ValueError('OSPFv3 passive must be boolean.')
    if all(options['passive'] for options in ports.values()):
        raise ValueError('OSPFv3 requires at least one active transit interface.')
    policy['router_id'] = str(router_id)
    policy['interfaces'] = dict(sorted(ports.items()))


def config(node):
    policy = node['ospfv3']
    lines = [f'router id {policy["router_id"]};', 'log stderr all;',
             'protocol device { scan time 1; }',
             'protocol kernel kernel6 { scan time 1; ipv6 { import none; export where source = RTS_OSPF; }; }',
             'protocol ospf v3 ospf6 {',
             '  ipv6 { import where source = RTS_OSPF; export none; };',
             '  ecmp no;', '  area 0.0.0.0 {']
    for name, port in policy['interfaces'].items():
        lines.append(f'    interface "{name}" {{ type ptp; cost {port["cost"]}; '
                     f'stub {"yes" if port["passive"] else "no"}; hello {policy["hello"]}; dead {policy["dead"]}; }};')
    return '\n'.join(lines + ['  };', '}']) + '\n'


def prepare_files(bundle, node):
    if node.get('ospfv3') is not None:
        (Path(bundle) / 'files/bird.conf').write_text(config(node))


def start_servers(manager):
    from .ipv6 import wait_addresses
    for index, node in enumerate(manager.state['spec']['nodes']):
        if node.get('ospfv3') is not None:
            wait_addresses(manager, index, node)
            # Same executable, config, socket and process-ownership checks as v2.
            # Validation excludes running v2 and v3 on the same node.
            start_one(manager, node)


def observe(manager, node):
    result = observe_config(manager, node['name'], '/lab/bird.conf', config(node))
    return {**result, 'source': 'BIRD 2 control socket and managed config file',
            'neighbors': read_cli(manager, node['name'], 'show ospf neighbors ospf6'),
            'interfaces': read_cli(manager, node['name'], 'show ospf interface ospf6'),
            'protocol': read_cli(manager, node['name'], 'show protocols all ospf6'),
            'routes': read_cli(manager, node['name'], 'show route protocol ospf6 all'),
            'note': 'Actual OSPFv3 daemon text. Single area 0, physical point-to-point and passive ports. '
                    'File conformity does not prove loaded policy, adjacency or delivery. Kernel routes are observed separately.'}


def dynamic_route(node, route):
    return node.get('ospfv3') is not None and route.get('protocol') in ('bird', 192, '192')
