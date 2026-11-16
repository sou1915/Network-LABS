"""Explicit public trust pins and offline private identity for mutual syslog TLS."""
import hashlib
import os
from pathlib import Path
import re
import ssl

BASE = '/etc/network-labs/syslog-tls'
CA = BASE + '/ca.pem'
CERT = BASE + '/certificate.pem'
KEY = BASE + '/private.key'
MODULES = ('imtcp.so', 'lmtcpsrv.so', 'lmnsd_gtls.so')


def config(node):
    server = node.get('syslog_server') or {}
    if server.get('transport') == 'tls': return server['tls']
    management = node.get('management') or {}
    if management.get('syslog_transport') == 'tls': return management['syslog_tls']
    return None


def validate_policy(value):
    from .spec import keys
    keys(value, ('peer', 'ca_sha256', 'certificate_sha256'), 'Syslog TLS policy')
    peer = value.get('peer')
    if not isinstance(peer, str) or len(peer) > 253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+', peer):
        raise ValueError('Syslog TLS peer must be an explicit lowercase DNS certificate name, without wildcards.')
    for field in ('ca_sha256', 'certificate_sha256'):
        if not isinstance(value.get(field), str) or not re.fullmatch('[0-9a-f]{64}', value[field]):
            raise ValueError('Syslog TLS requires explicit public CA and certificate SHA-256 pins.')


def read_asset(path, private=False):
    path = Path(path)
    if path.is_symlink(): raise ValueError('Syslog TLS assets must be regular files, not symlinks.')
    with path.open('rb') as source: data = source.read(65537)
    if len(data) > 65536 or not data: raise ValueError('Syslog TLS assets must be nonempty files of at most 64 KiB.')
    if private:
        if path.stat().st_mode & 0o777 != 0o600 or b'ENCRYPTED' in data:
            raise ValueError('Syslog TLS private key requires mode 0600 and an unencrypted matching PEM key.')
    elif b'PRIVATE KEY' in data:
        raise ValueError('Public syslog TLS certificate assets must not contain private keys.')
    return data


def assets(ca, certificate, key):
    values = {CA: read_asset(ca), CERT: read_asset(certificate), KEY: read_asset(key, True)}
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_verify_locations(cafile=str(ca))
    context.load_cert_chain(str(certificate), str(key), password='')
    return values


def install(rootfs, values):
    directory = Path(rootfs) / BASE.lstrip('/'); directory.mkdir(parents=True, mode=0o700)
    for name, data in values.items():
        path = Path(rootfs) / name.lstrip('/')
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600 if name == KEY else 0o644)
        with os.fdopen(fd, 'wb') as output: output.write(data)


def policy(rootfs, peer):
    value = {'peer': peer, 'ca_sha256': hashlib.sha256(read_asset(Path(rootfs) / CA.lstrip('/'))).hexdigest(),
             'certificate_sha256': hashlib.sha256(read_asset(Path(rootfs) / CERT.lstrip('/'))).hexdigest()}
    validate_policy(value); return value


def preflight(node):
    value = config(node)
    if value is None: return None
    from .runtime import RuntimeFailure
    root = Path(node['rootfs'])
    try:
        actual = assets(*(root / p.lstrip('/') for p in (CA, CERT, KEY)))
        if hashlib.sha256(actual[CA]).hexdigest() != value['ca_sha256'] or hashlib.sha256(actual[CERT]).hexdigest() != value['certificate_sha256']:
            raise ValueError('Public CA/certificate pins differ from offline TLS assets.')
        return hashlib.sha256(actual[KEY]).hexdigest()
    except (OSError, ValueError, ssl.SSLError) as error:
        raise RuntimeFailure(node['name'] + ': syslog TLS identity/trust assets unavailable or invalid: ' + str(error)) from error


def global_options():
    return ' defaultNetstreamDriver="gtls" defaultNetstreamDriverCAFile="' + CA + '" defaultNetstreamDriverCertFile="' + CERT + '" defaultNetstreamDriverKeyFile="' + KEY + '"'


def observe(manager, node):
    from .runtime import RuntimeFailure
    import subprocess
    value = config(node)
    if value is None: return None
    verified = False
    try:
        result = manager.crun('exec', node['name'], '/bin/busybox', 'sha256sum', CA, CERT, KEY, check=False, timeout=3)
        rows = result.stdout.splitlines()
        sums = {row.split(None, 1)[1].strip(): row.split(None, 1)[0] for row in rows if len(row.split(None, 1)) == 2}
        mode = manager.crun('exec', node['name'], '/bin/busybox', 'stat', '-c', '%a', KEY, check=False, timeout=3)
        expected_key = manager.read().get('syslog_tls_key_hashes', {}).get(node['name'])
        verified = (result.returncode == 0 and mode.returncode == 0 and mode.stdout == '600\n' and
                    sums.get(CA) == value['ca_sha256'] and sums.get(CERT) == value['certificate_sha256'] and
                    expected_key is not None and sums.get(KEY) == expected_key)
    except (OSError, ValueError, RuntimeFailure, subprocess.TimeoutExpired): pass
    return {'configuration_verified': verified, 'peer': value['peer'],
            'scope': 'Pinned public assets, runtime private-key conformity and permissions; not a handshake or delivery verdict.'}
