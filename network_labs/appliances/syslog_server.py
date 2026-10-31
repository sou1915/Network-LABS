"""Explicit rsyslog UDP or plain TCP collector, isolated inside an OCI node."""
import ipaddress
from pathlib import Path
from .service_config import observe_config

# Distinct application path: do not attach the host service's pathname profile
# to an isolated guest with different configuration and log paths.
BINARY = '/usr/lib/network-labs/rsyslogd'
MODULES = '/usr/lib/network-labs/rsyslog'
CONFIG = '/lab/syslog-server.conf'
LOG = '/run/remote-syslog.log'
ROTATE = '/lab/rotate-syslog.sh'


def validate_node(node):
    from .lan import addresses
    from .spec import keys
    config = node.setdefault('syslog_server', None)
    if config is None: return
    keys(config, ('interface', 'senders', 'transport', 'tls'), 'Syslog server')
    if config.get('transport', 'udp') not in ('udp', 'tcp', 'tls'):
        raise ValueError('Syslog collector transport: udp, tcp or tls.')
    if config.get('transport') == 'tls':
        from .syslog_tls import validate_policy
        validate_policy(config.get('tls'))
        if node['role'] != 'host' or set(node['interfaces']) != {'eth0'}:
            raise ValueError('TLS syslog collector initially requires a single-interface OCI host.')
    elif 'tls' in config: raise ValueError('Syslog TLS policy requires transport tls.')
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
    if config.get('transport') == 'tls' and len(config['senders']) != 1:
        raise ValueError('TLS syslog collector initially requires one sender address and one peer identity.')


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
    tls = node['syslog_server'].get('transport') == 'tls'
    tcp = node['syslog_server'].get('transport', 'udp') == 'tcp'
    from .syslog_tls import global_options
    tls_input = ('input(type="imtcp" address="' + listen_address(node) + '" port="6514" ruleset="NetworkLabsRemote" SupportOctetCountedFraming="on" MaxFrameSize="1024" PermittedPeer="' + node['syslog_server']['tls']['peer'] + '")') if tls else ''
    allowed = ' or '.join('$fromhost-ip == "' + ip + '"' for ip in node['syslog_server']['senders'])
    config = '\n'.join([
        'global(workDirectory="/run" net.enableDNS="off" maxMessageSize="1k"' + (global_options() if tls else '') + ')',
        'main_queue(queue.size="256" queue.workerThreads="1" queue.dequeueBatchSize="1")',
        'module(load="imtcp" MaxSessions="16" StreamDriver.Name="gtls" StreamDriver.Mode="1" StreamDriver.AuthMode="x509/name" StreamDriver.CheckExtendedKeyPurpose="on" StreamDriver.PrioritizeSAN="on" gnutlsPriorityString="NORMAL:-VERS-ALL:+VERS-TLS1.2:+VERS-TLS1.3")' if tls else 'module(load="imptcp" threads="1" maxSessions="16")' if tcp else 'module(load="imudp" threads="1")',
        'template(name="NetworkLabsWire" type="string" string="%fromhost-ip% %rawmsg%\\n")',
        'ruleset(name="NetworkLabsRemote") {',
        '  if not (' + allowed + ') then stop',
        '  action(type="omfile" file="' + LOG + '" template="NetworkLabsWire"',
        '         fileCreateMode="0600" flushOnTXEnd="on" rotation.sizeLimit="65536"',
        '         rotation.sizeLimitCommand="/bin/sh ' + ROTATE + '")',
        '}',
        tls_input if tls else ('input(type="imptcp" address="' + listen_address(node) + '" port="514"'
         ' supportOctetCountedFraming="on" maxFrameSize="1024" ruleset="NetworkLabsRemote")') if tcp else
        ('input(type="imudp" address="' + listen_address(node) + '" port="514" ipFreeBind="0"\n'
         '      ruleset="NetworkLabsRemote" rateLimit.interval="5" rateLimit.burst="1000")'),
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
    from .syslog_tls import observe as observe_tls
    tls = observe_tls(manager, node)
    return {'configuration_verified': all(row['configuration_verified'] for row in checks.values()) and (tls is None or tls['configuration_verified']), 'tls': tls,
            'files': checks, 'address': listen_address(node), 'port': 6514 if node['syslog_server'].get('transport') == 'tls' else 514, 'transport': node['syslog_server'].get('transport', 'udp'),
            'allowed_senders': node['syslog_server']['senders'], 'log': LOG,
            'note': 'Managed file conformity only, not daemon liveness or message delivery. IP allowlist is not authentication. 64 KiB rotation threshold plus batch/message overshoot, one backup; volatile node logs, not saved/restored. TCP uses plain imptcp with octet-counted and LF framing, 16 sessions; TLS optionally uses mutually authenticated gtls with pinned public trust and explicit peer names on TCP/6514. No durable sender queue or application acknowledgement.'}


def drift(manager, node):
    return [node['name'] + ': syslog collector configuration differs or is unavailable'] if node.get('syslog_server') and not observe(manager, node)['configuration_verified'] else []


def rootfs_assets(binary, modules=None, *, tcp=False, forward=False, tls=False):
    from .dns_rootfs import assets, shared_library_assets
    planned = assets(binary, destination=BINARY, version_args=('-v',), identity='rsyslogd',
                     version_check=lambda r: r.returncode == 0 and r.stdout.lower().startswith('rsyslogd '))
    if modules is None:
        candidates = [p for p in [Path('/usr/lib/rsyslog'), *Path('/usr/lib').glob('*/rsyslog')] if (p / 'imudp.so').is_file()]
        if len(candidates) != 1:
            raise ValueError('Provide --rsyslog-modules with the trusted rsyslog module directory.')
        modules = candidates[0]
    modules = Path(modules).resolve()
    from .syslog_forward import REQUIRED_MODULES
    from .syslog_tls import MODULES as TLS_MODULES
    names = ['imudp.so', 'lmnet.so', *(['imptcp.so'] if tcp else []), *(REQUIRED_MODULES if forward or tls else []), *(TLS_MODULES if tls else [])]
    for name in dict.fromkeys(names):
        planned.extend(shared_library_assets(modules / name, Path(MODULES) / name))
    return planned
