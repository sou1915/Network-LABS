"""Scoped read-only dnsmasq TFTP service with declared text files."""
import ipaddress
from pathlib import Path
import re

from .service_config import observe_config

BINARY = '/usr/sbin/dnsmasq'
CONFIG = '/lab/tftp-server.conf'
ROOT = '/lab/tftp'


def validate_node(node):
    from .lan import addresses
    from .spec import keys
    policy = node.setdefault('tftp_server', None)
    if policy is None: return
    keys(policy, ('interface', 'files'), 'TFTP server')
    port = policy.get('interface'); known = addresses(node)
    if (node['runtime'] != 'oci' or node['role'] != 'host' or not isinstance(port, str) or
            port not in node['interfaces'] or not known.get(port) or port in node['shutdown'] or node.get('startup')):
        raise ValueError('TFTP requires an UP, numbered physical OCI host interface and no unmanaged startup.')
    local = ipaddress.IPv4Interface(known[port])
    if (local.ip.is_unspecified or local.ip.is_multicast or local.ip.is_loopback or local.ip.is_reserved or
            (local.network.prefixlen < 31 and local.ip in (local.network.network_address, local.network.broadcast_address))):
        raise ValueError('TFTP requires a usable unicast IPv4 address.')
    if any(node.get(key) for key in ('dns_server', 'dhcp_server', 'dhcp_pools', 'dhcp_relay', 'dhcpv6_server',
                                     'router_advertisements', 'management', 'ntp_server', 'snmp_agent', 'snmp_receiver', 'syslog_server')):
        raise ValueError('Initial TFTP server profile requires a separate service node.')
    files = policy.get('files')
    if not isinstance(files, dict) or not 1 <= len(files) <= 8:
        raise ValueError('TFTP requires 1..8 declared text files.')
    for name, content in files.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', name) or name in ('.', '..'):
            raise ValueError('TFTP filenames must be single ASCII names without directories.')
        if not isinstance(content, str) or len(content.encode('utf-8')) > 4096:
            raise ValueError('Each TFTP text file must be at most 4096 UTF-8 bytes.')
    policy['files'] = dict(sorted(files.items()))


def config_text(node):
    policy = node['tftp_server']
    return '\n'.join(['port=0', 'interface=' + policy['interface'], 'bind-interfaces',
                      'enable-tftp=' + policy['interface'], 'tftp-root=' + ROOT,
                      'tftp-secure', 'tftp-max=4', 'pid-file=/run/tftp-dnsmasq.pid',
                      'user=root', 'group=root', 'log-facility=-', ''])


def prepare_files(bundle, node):
    if node.get('tftp_server') is None: return
    base = Path(bundle) / 'files'; (base / 'tftp').mkdir(mode=0o755)
    (base / 'tftp-server.conf').write_text(config_text(node), encoding='utf-8')
    for name, content in node['tftp_server']['files'].items():
        path = base / 'tftp' / name; path.write_text(content, encoding='utf-8'); path.chmod(0o644)


def start_servers(manager):
    for node in manager.state['spec']['nodes']:
        if node.get('tftp_server') is None: continue
        log = manager.directory / node['name'] / 'tftp.log'
        manager.crun('exec', node['name'], BINARY, '--test', '--conf-file=' + CONFIG, log=log)
        manager.crun('exec', '--detach', node['name'], BINARY, '--keep-in-foreground', '--conf-file=' + CONFIG, log=log)


def observe(manager, node):
    config = observe_config(manager, node['name'], CONFIG, config_text(node))
    files = {name: observe_config(manager, node['name'], ROOT + '/' + name, content)
             for name, content in node['tftp_server']['files'].items()}
    return {'configuration_verified': config['configuration_verified'] and all(item['configuration_verified'] for item in files.values()),
            'config': config, 'files': files,
            'note': 'File conformity only, not daemon liveness, delivery or authentication. Read-only TFTP exposes declared files to reachable clients.'}


def drift(manager, node):
    return [node['name'] + ': TFTP configuration or files differ or are unavailable'] if node.get('tftp_server') and not observe(manager, node)['configuration_verified'] else []
