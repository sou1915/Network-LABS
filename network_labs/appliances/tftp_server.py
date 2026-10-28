"""Scoped read-only dnsmasq TFTP service with declared text or binary files."""
import ipaddress
import base64
import binascii
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess

from .service_config import observe_config

BINARY = '/usr/sbin/dnsmasq'
CONFIG = '/lab/tftp-server.conf'
ROOT = '/lab/tftp'
MAX_BINARY_BYTES = 65536


def validate_filename(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', name) or name in ('.', '..'):
        raise ValueError('TFTP filenames must be single ASCII names without directories.')


def import_files(entries):
    """Embed explicitly selected regular files; retain no host filesystem paths."""
    if not 1 <= len(entries) <= 8:
        raise ValueError('TFTP imports require 1..8 NAME=PATH entries.')
    paths = {}
    for entry in entries:
        name, separator, path = entry.partition('=')
        validate_filename(name)
        if not separator or not path: raise ValueError('TFTP import requires NAME=PATH.')
        if name in paths: raise ValueError('Duplicate TFTP import filename: ' + name)
        paths[name] = path
    files = {}
    for name, path in paths.items():
        # NONBLOCK avoids hanging on FIFOs before checking the opened object.
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError('TFTP imports require regular files.')
            with os.fdopen(descriptor, 'rb', closefd=False) as source:
                payload = source.read(MAX_BINARY_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(payload) > MAX_BINARY_BYTES:
            raise ValueError('TFTP binary file exceeds 65536 bytes.')
        files[name] = {'base64': base64.b64encode(payload).decode('ascii')}
    return files


def file_bytes(value):
    if isinstance(value, str):
        encoded = value.encode('utf-8')
        if len(encoded) > 4096: raise ValueError('TFTP text file exceeds 4096 UTF-8 bytes.')
        return encoded
    if not isinstance(value, dict) or set(value) != {'base64'} or not isinstance(value['base64'], str):
        raise ValueError('TFTP file must be UTF-8 text or an object containing base64.')
    encoded = value['base64']
    if len(encoded) > 4 * ((MAX_BINARY_BYTES + 2) // 3):
        raise ValueError('TFTP binary file exceeds 65536 bytes.')
    try:
        decoded = base64.b64decode(encoded.encode('ascii'), validate=True)
    except (UnicodeError, binascii.Error, ValueError) as error:
        raise ValueError('TFTP binary file requires canonical base64.') from error
    if len(decoded) > MAX_BINARY_BYTES or base64.b64encode(decoded).decode('ascii') != encoded:
        raise ValueError('TFTP binary file requires canonical base64 and at most 65536 bytes.')
    return decoded


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
        raise ValueError('TFTP requires 1..8 declared text or binary files.')
    for name, content in files.items():
        validate_filename(name)
        file_bytes(content)
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
        path = base / 'tftp' / name; path.write_bytes(file_bytes(content)); path.chmod(0o644)


def start_servers(manager):
    for node in manager.state['spec']['nodes']:
        if node.get('tftp_server') is None: continue
        log = manager.directory / node['name'] / 'tftp.log'
        manager.crun('exec', node['name'], BINARY, '--test', '--conf-file=' + CONFIG, log=log)
        manager.crun('exec', '--detach', node['name'], BINARY, '--keep-in-foreground', '--conf-file=' + CONFIG, log=log)


def observe_file(manager, node, name, expected):
    """Compare bounded-process SHA-256 without decoding or returning file data."""
    from .runtime import RuntimeFailure
    evidence = {'configuration_verified': False, 'configuration_available': False, 'detail': None}
    path = ROOT + '/' + name
    try:
        result = manager.crun('exec', node['name'], '/bin/busybox', 'sha256sum', path, check=False, timeout=3)
        match = re.fullmatch(r'([0-9a-f]{64})  ' + re.escape(path) + r'\n?', result.stdout)
        if result.returncode or not match:
            evidence['detail'] = 'File digest unavailable or malformed.'
            return evidence
        evidence['configuration_available'] = True
        evidence['configuration_verified'] = match.group(1) == hashlib.sha256(expected).hexdigest()
    except (OSError, RuntimeFailure, subprocess.TimeoutExpired, UnicodeError, ValueError) as error:
        evidence['detail'] = str(error)[:300]
    return evidence


def observe(manager, node):
    config = observe_config(manager, node['name'], CONFIG, config_text(node))
    files = {name: observe_file(manager, node, name, file_bytes(content))
             for name, content in node['tftp_server']['files'].items()}
    return {'configuration_verified': config['configuration_verified'] and all(item['configuration_verified'] for item in files.values()),
            'config': config, 'files': files,
            'note': 'File conformity only, not daemon liveness, delivery or authentication. Read-only TFTP exposes declared files to reachable clients.'}


def drift(manager, node):
    return [node['name'] + ': TFTP configuration or files differ or are unavailable'] if node.get('tftp_server') and not observe(manager, node)['configuration_verified'] else []
