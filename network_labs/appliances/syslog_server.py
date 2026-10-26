"""Explicit rsyslog UDP collector, isolated inside an OCI node."""
import ipaddress
from pathlib import Path
from .service_config import observe_config

BINARY = '/usr/sbin/rsyslogd'
MODULES = '/usr/lib/network-labs/rsyslog'
CONFIG = '/lab/syslog-server.conf'
LOG = '/run/remote-syslog.log'
ROTATE = '/lab/rotate-syslog.sh'


def validate_node(node):
    from .lan import addresses
    from .spec import keys
    config = node.setdefault('syslog_server', None)
    if config is None: return
    keys(config, ('interface', 'senders'), 'Syslog server')
    values = addresses(node); port = config.get('interface')
    if (node['runtime'] != 'oci' or not isinstance(port, str) or not values.get(port) or
            port in node['shutdown'] or node.get('startup')):
        raise ValueError('Syslog collector requires a numbered UP OCI IPv4 interface and no unmanaged startup.')
    local = ipaddress.IPv4Interface(values[port])
    if (local.ip.is_unspecified or local.ip.is_multicast or local.ip.is_loopback or local.ip.is_reserved or
            (local.network.prefixlen < 31 and local.ip in (local.network.network_address, local.network.broadcast_address))):
        raise ValueError('Syslog collector requires a usable IPv4 address.')
    senders = config.get('senders')
    if not isinstance(senders, list) or not 1 <= len(senders) <= 64 or not all(isinstance(v, str) for v in senders):
        raise ValueError('Syslog collector requires 1..64 explicit IPv4 sender addresses.')
    canonical = []
    for value in senders:
        address = ipaddress.IPv4Address(value)
        if address.is_unspecified or address.is_multicast or address.is_loopback or address.is_reserved or address == local.ip:
            raise ValueError('Syslog collector requires remote unicast IPv4 senders.')
        canonical.append(str(address))
    config['senders'] = sorted(set(canonical))


def validate_lab(spec):
    from .lan import addresses
    for node in spec['nodes']:
        config = node.get('syslog_server')
        if not config: continue
        for address in config['senders']:
            peers = [n for n in spec['nodes'] if any(v and str(ipaddress.IPv4Interface(v).ip) == address for v in addresses(n).values())]
            if len(peers) != 1 or peers[0]['name'] == node['name']:
                raise ValueError('Syslog sender must be one other uniquely numbered managed IPv4 node.')


def listen_address(node):
    from .lan import addresses
    return str(ipaddress.IPv4Interface(addresses(node)[node['syslog_server']['interface']]).ip)


def files(node):
    allowed = ' or '.join('$fromhost-ip == "' + ip + '"' for ip in node['syslog_server']['senders'])
    config = '\n'.join([
        'global(workDirectory="/run" net.enableDNS="off" maxMessageSize="1k")',
        'main_queue(queue.size="256" queue.workerThreads="1" queue.dequeueBatchSize="1")',
        'module(load="imudp" threads="1")',
        'template(name="NetworkLabsWire" type="string" string="%fromhost-ip% %rawmsg%\\n")',
        'ruleset(name="NetworkLabsRemote") {',
        '  if not (' + allowed + ') then stop',
        '  action(type="omfile" file="' + LOG + '" template="NetworkLabsWire"',
        '         fileCreateMode="0600" flushOnTXEnd="on" rotation.sizeLimit="65536"',
        '         rotation.sizeLimitCommand="/bin/sh ' + ROTATE + '")',
        '}',
        'input(type="imudp" address="' + listen_address(node) + '" port="514" ipFreeBind="0"',
        '      ruleset="NetworkLabsRemote" rateLimit.interval="5" rateLimit.burst="1000")',
        '',
    ])
    return {'syslog-server.conf': config,
            'rotate-syslog.sh': '#!/bin/sh\nexec /bin/busybox mv -f ' + LOG + ' ' + LOG + '.1\n'}


def prepare_files(bundle, node):
    if node.get('syslog_server'):
        for name, value in files(node).items():
            path = Path(bundle) / 'files' / name; path.write_text(value); path.chmod(0o644)


def command():
    return [BINARY, '-n', '-i', '/run/rsyslogd.pid', '-M', MODULES, '-f', CONFIG]


def start_server(manager, node):
    from .runtime import RuntimeFailure
    result = manager.crun('exec', node['name'], BINARY, '-N1', '-M', MODULES, '-f', CONFIG, check=False, timeout=5)
    if result.returncode:
        raise RuntimeFailure(node['name'] + ': rsyslog collector configuration rejected: ' + (result.stdout + result.stderr)[-2048:])
    manager.crun('exec', '--detach', node['name'], *command(), log=manager.directory / node['name'] / 'syslog-server.log')


def start_servers(manager):
    for node in manager.state['spec']['nodes']:
        if node.get('syslog_server'): start_server(manager, node)


def observe(manager, node):
    checks = {name: observe_config(manager, node['name'], '/lab/' + name, value) for name, value in files(node).items()}
    return {'configuration_verified': all(row['configuration_verified'] for row in checks.values()),
            'files': checks, 'address': listen_address(node), 'port': 514, 'transport': 'udp',
            'allowed_senders': node['syslog_server']['senders'], 'log': LOG,
            'note': 'Managed file conformity only, not daemon liveness or message delivery. IP allowlist is not authentication. 64 KiB rotation threshold plus batch/message overshoot, one backup; volatile node logs, not saved/restored. No TCP/TLS collector.'}


def drift(manager, node):
    return [node['name'] + ': syslog collector configuration differs or is unavailable'] if node.get('syslog_server') and not observe(manager, node)['configuration_verified'] else []


def rootfs_assets(binary, modules=None):
    from .dns_rootfs import assets, shared_library_assets
    planned = assets(binary, destination=BINARY, version_args=('-v',), identity='rsyslogd',
                     version_check=lambda r: r.returncode == 0 and r.stdout.lower().startswith('rsyslogd '))
    if modules is None:
        candidates = [p for p in [Path('/usr/lib/rsyslog'), *Path('/usr/lib').glob('*/rsyslog')] if (p / 'imudp.so').is_file()]
        if len(candidates) != 1:
            raise ValueError('Provide --rsyslog-modules with the trusted rsyslog module directory.')
        modules = candidates[0]
    modules = Path(modules).resolve()
    for name in ('imudp.so', 'lmnet.so'):
        planned.extend(shared_library_assets(modules / name, Path(MODULES) / name))
    return planned
