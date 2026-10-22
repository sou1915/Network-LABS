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
    planned = assets(daemon, destination=DAEMON, identity='BIRD version 2',
                     version_check=lambda result: result.returncode == 0 and re.match(r'^BIRD version 2\.\d', result.stderr.strip()) is not None)
    # birdc has no --version; its documented control-client usage exits 1.
    planned += assets(client, destination=CLIENT, identity='BIRD control client', version_args=('-h',),
                      version_check=lambda result: result.returncode == 1 and '[-s <control-socket>] [-v] [-r]' in result.stderr)
    return sorted(set(planned), key=lambda item: str(item[1]))


def validate_ospf(node):
    policy = node.setdefault('ospf', None)
    if policy is None:
        return
    keys(policy, ('router_id', 'interfaces', 'hello', 'dead', 'process_id', 'networks'), 'OSPF')
    integer(policy.setdefault('process_id', 1), 1, 65535, 'OSPF process ID')
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
    selectors = policy.setdefault('networks', [str(network) for network in networks])
    if not isinstance(selectors, list) or not 1 <= len(selectors) <= 64:
        raise ValueError('OSPF requires 1..64 IPv4 network selectors.')
    canonical = []
    for value in selectors:
        if not isinstance(value, str):
            raise ValueError('OSPF network selectors must be IPv4 prefix text.')
        selector = ipaddress.IPv4Network(value, strict=True)
        matches = {name for name, address in node['interfaces'].items() if address and ipaddress.IPv4Interface(address).ip in selector}
        if not matches or matches - set(ports):
            raise ValueError('OSPF network selector must match numbered interfaces with declared OSPF options.')
        canonical.append(str(selector))
    policy['networks'] = sorted(set(canonical))
    if all(ports[name]['passive'] for name in enabled_interfaces(node)):
        raise ValueError('OSPF requires at least one active transit interface.')
    integer(policy.setdefault('hello', 1), 1, 60, 'OSPF hello')
    integer(policy.setdefault('dead', 4), 2, 240, 'OSPF dead')
    if policy['dead'] <= policy['hello']:
        raise ValueError('OSPF dead must exceed hello.')
    policy['router_id'] = str(router_id)
    policy['interfaces'] = dict(sorted(ports.items()))


def enabled_interfaces(node):
    policy = node['ospf']
    selectors = [ipaddress.IPv4Network(value) for value in policy['networks']]
    return {name: port for name, port in policy['interfaces'].items()
            if any(ipaddress.IPv4Interface(node['interfaces'][name]).ip in selector for selector in selectors)}


def configure_network(node, address, wildcard, remove=False):
    # Accept contiguous IOS wildcard masks, including exact-host 0.0.0.0.
    address = ipaddress.IPv4Address(address)
    bits = int(ipaddress.IPv4Address(wildcard))
    if bits & (bits + 1):
        raise ValueError('OSPF adapter supports contiguous wildcard masks only.')
    prefix = ipaddress.IPv4Network((int(address) & (0xffffffff ^ bits), 32 - bits.bit_length()))
    policy = node['ospf']
    value = str(prefix)
    if remove:
        policy['networks'] = [entry for entry in policy['networks'] if entry != value]
        return
    matches = [name for name, local in node['interfaces'].items() if local and ipaddress.IPv4Interface(local).ip in prefix]
    if not matches:
        raise ValueError('OSPF network must match an existing numbered physical interface.')
    for name in matches:
        policy['interfaces'].setdefault(name, {'cost': 10, 'passive': False})
    if value not in policy['networks']:
        policy['networks'].append(value)


def config(node):
    policy = node['ospf']
    lines = [f'router id {policy["router_id"]};', 'log stderr all;', 'protocol device { scan time 1; }',
             'protocol kernel kernel4 { scan time 1; ipv4 { import none; export where source = RTS_OSPF; }; }',
             'protocol ospf v2 ospf4 {', '  ipv4 { import where source = RTS_OSPF; export none; };',
             '  ecmp no;', '  area 0.0.0.0 {']
    for name, port in enabled_interfaces(node).items():
        lines.append(f'    interface "{name}" {{ type ptp; cost {port["cost"]}; stub {"yes" if port["passive"] else "no"}; hello {policy["hello"]}; dead {policy["dead"]}; }};')
    return '\n'.join(lines + ['  };', '}']) + '\n'


def prepare_files(bundle, node):
    if node.get('ospf') is not None:
        (Path(bundle) / 'files/bird.conf').write_text(config(node))


def _cli(manager, name, command, *, readonly=True):
    # All call sites use fixed show/configure commands. Bound output inside the container;
    # pipefail prevents a failed client from becoming an apparently empty RIB.
    try:
        result = manager.crun('exec', name, '/bin/sh', '-c',
            'set -o pipefail; /usr/sbin/birdc -v -s /run/bird.ctl "$@" | /bin/busybox head -c 65537',
            'bird-control', *(['-r'] if readonly else []), *command.split(), check=False, timeout=3)
        if result.returncode or len(result.stdout) > 65536 or re.search(r'(?m)^[89]\d{3}', result.stdout):
            return None
        return result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def read_cli(manager, name, command):
    return _cli(manager, name, command)


def start_one(manager, node):
    from .runtime import RuntimeFailure
    if processes(manager, node, managed=False):
        raise RuntimeFailure('Refusing to start OSPF while a BIRD process already exists.')
    manager.crun('exec', node['name'], DAEMON, '-p', '-c', '/lab/bird.conf', timeout=3)
    manager.crun('exec', '--detach', node['name'], DAEMON, '-f', '-c', '/lab/bird.conf',
                 '-s', '/run/bird.ctl', '-P', '/run/bird.pid', log=manager.directory / node['name'] / 'ospf.log')
    deadline = time.monotonic() + 5
    while len(processes(manager, node)) != 1 or read_cli(manager, node['name'], 'show status') is None:
        if time.monotonic() >= deadline:
            raise RuntimeFailure(node['name'] + ': managed BIRD process/control socket did not become available.')
        time.sleep(0.1)


def start_servers(manager):
    for node in manager.state['spec']['nodes']:
        if node.get('ospf') is not None:
            start_one(manager, node)


def observe(manager, node):
    result = observe_config(manager, node['name'], '/lab/bird.conf', config(node))
    return {**result, 'source': 'BIRD 2 control socket and managed config file',
            'neighbors': read_cli(manager, node['name'], 'show ospf neighbors'),
            'protocol': read_cli(manager, node['name'], 'show protocols all ospf4'),
            'routes': read_cli(manager, node['name'], 'show route protocol ospf4 all'),
            'note': 'Actual daemon text; file conformity does not prove loaded policy or convergence. Kernel routes are observed separately. Single area 0, IPv4 point-to-point/passive interfaces only.'}


def dynamic_route(node, route):
    return node.get('ospf') is not None and route.get('protocol') in ('bird', 192, '192')


def validate_change(node, previous):
    if {k: v for k, v in node.items() if k != 'ospf'} != {k: v for k, v in previous.items() if k != 'ospf'}:
        raise ValueError('OSPF service adapter accepts OSPF-only edits; recreate the lab for network changes.')
    if node.get('ospf') and previous.get('ospf') and any(
            node['ospf'][key] != previous['ospf'][key] for key in ('router_id', 'process_id', 'hello', 'dead')):
        raise ValueError('Live OSPF adapter supports selectors, passive interfaces and costs; delete/recreate the process to change ID/timers.')


# Never select a kill target from bird.pid. Inspect executable and exact config
# and control-socket argv in the container PID namespace. PID 1 may be listed
# to reject untracked BIRD-as-init, but must never be terminated here.
PROCESS_SCRIPT = r'''for proc in /proc/[0-9]*; do
    [ "$(/bin/busybox readlink "$proc/exe" 2>/dev/null)" = /usr/sbin/bird ] || continue
    if [ "$2" = managed ]; then
        /bin/busybox tr '\000' '\n' < "$proc/cmdline" | /bin/busybox grep -Fxq -- '/lab/bird.conf' || continue
        /bin/busybox tr '\000' '\n' < "$proc/cmdline" | /bin/busybox grep -Fxq -- '/run/bird.ctl' || continue
    fi
    pid=${proc##*/}
    if [ "$1" = stop ]; then
        [ "$pid" -gt 1 ] || exit 1
        /bin/busybox kill -TERM "$pid" || exit 1
    else echo "$pid"; fi
done
'''


def processes(manager, node, action='list', *, managed=True):
    return manager.crun('exec', node['name'], '/bin/sh', '-c', PROCESS_SCRIPT, 'ospf-control',
                        action, 'managed' if managed else 'all', timeout=3).stdout.splitlines()


def stop_one(manager, node):
    from .runtime import RuntimeFailure
    owned = processes(manager, node)
    if owned != processes(manager, node, managed=False):
        raise RuntimeFailure('Unmanaged BIRD process detected; refusing OSPF service removal.')
    processes(manager, node, 'stop')
    deadline = time.monotonic() + 5
    while processes(manager, node, managed=False):
        if time.monotonic() >= deadline:
            raise RuntimeFailure('Managed BIRD process did not stop.')
        time.sleep(0.1)
    manager.crun('exec', node['name'], '/bin/busybox', 'rm', '-f', '/run/bird.ctl', '/run/bird.pid', timeout=3)


def _done(text):
    return (text is not None and re.search(r'(?m)^0003[ -]', text) is not None
            and re.search(r'(?m)^(000[456]|0022)[ -]', text) is None)


def preflight_change(manager, node, previous):
    from .runtime import RuntimeFailure
    validate_change(node, previous)
    if previous.get('ospf'):
        if not observe_config(manager, node['name'], '/lab/bird.conf', config(previous))['configuration_verified']:
            raise RuntimeFailure('OSPF configuration drift; refusing live change.')
        if not _done(_cli(manager, node['name'], 'configure status', readonly=False)):
            raise RuntimeFailure('OSPF control unavailable or reconfiguration pending; refusing live change.')
        owned = processes(manager, node)
        if len(owned) != 1 or owned != processes(manager, node, managed=False) or owned == ['1']:
            raise RuntimeFailure('OSPF requires exactly one managed non-init BIRD process.')
    else:
        if processes(manager, node, managed=False):
            raise RuntimeFailure('Unmanaged BIRD process detected; refusing OSPF creation.')
        for path in ('/lab/bird.conf', '/run/bird.ctl'):
            if manager.crun('exec', node['name'], '/bin/busybox', 'test', '-e', path, check=False, timeout=3).returncode == 0:
                raise RuntimeFailure('Unmanaged OSPF config/control path exists; refusing creation.')
    if node.get('ospf'):
        for binary in (DAEMON, CLIENT):
            manager.crun('exec', node['name'], '/bin/busybox', 'test', '-x', binary, timeout=3)


def apply_change(manager, index, node, previous):
    """Reconcile the journal target service; never change links or addresses."""
    from .runtime import RuntimeFailure
    validate_change(node, previous)
    path = manager.directory / node['name'] / 'files/bird.conf'
    temporary = path.with_suffix('.conf.new')
    if node.get('ospf') is None:
        stop_one(manager, node)
        path.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
        return
    try:
        temporary.write_text(config(node))
        manager.crun('exec', node['name'], DAEMON, '-p', '-c', '/lab/bird.conf.new', timeout=3)
        temporary.replace(path)
        owned = processes(manager, node)
        if owned != processes(manager, node, managed=False) or len(owned) > 1 or owned == ['1']:
            raise RuntimeFailure('Unmanaged or ambiguous BIRD process; refusing OSPF apply.')
        if not owned:
            manager.crun('exec', node['name'], '/bin/busybox', 'rm', '-f', '/run/bird.ctl', '/run/bird.pid', timeout=3)
            start_one(manager, node)
            return
        response = _cli(manager, node['name'], 'configure', readonly=False)
        if response is None or re.search(r'(?m)^000[34][ -]', response) is None:
            raise RuntimeFailure('BIRD did not accept OSPF reconfiguration.')
        deadline = time.monotonic() + 5
        while not _done(_cli(manager, node['name'], 'configure status', readonly=False)):
            if time.monotonic() >= deadline:
                raise RuntimeFailure('BIRD reconfiguration did not complete; adjacency convergence is separate.')
            time.sleep(0.1)
    finally:
        temporary.unlink(missing_ok=True)
