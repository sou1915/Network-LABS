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
    keys(value, ('peer', 'ca_sha256', 'certificate_sha256','verify_peer_on_start'), 'Syslog TLS policy')
    if type(value.get('verify_peer_on_start',False)) is not bool:
        raise ValueError('Syslog TLS verify_peer_on_start must be a boolean.')
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


def paired_nodes(spec):
    """Opt-in proof describes exactly one declared sender/collector pair."""
    nodes=[n for n in spec['nodes'] if config(n) is not None]
    if not any(config(n).get('verify_peer_on_start',False) for n in nodes):return None
    servers=[n for n in nodes if (n.get('syslog_server') or {}).get('transport')=='tls']
    clients=[n for n in nodes if (n.get('management') or {}).get('syslog_transport')=='tls']
    if len(nodes)!=2 or len(servers)!=1 or len(clients)!=1 or servers[0] is clients[0] or not all(config(n).get('verify_peer_on_start',False) for n in nodes):
        raise ValueError('Syslog TLS peer preflight requires exactly one sender and one collector, both explicitly opted in.')
    import ipaddress
    server,client=servers[0],clients[0]
    from .syslog_server import listen_address
    local=str(ipaddress.IPv4Interface(client['interfaces'][client['management']['interface']]).ip)
    if client['management']['syslog_remote']!=listen_address(server) or server['syslog_server']['senders']!=[local]:
        raise ValueError('Syslog TLS peer preflight requires the declared sender and collector to target each other.')
    return server,client


def preflight_pair(spec):
    pair=paired_nodes(spec)
    if pair is None:return
    from .runtime import RuntimeFailure
    from .tls_identity import handshake
    server,client=pair
    try:
        contexts=[]
        for node,protocol in ((server,ssl.PROTOCOL_TLS_SERVER),(client,ssl.PROTOCOL_TLS_CLIENT)):
            root=Path(node['rootfs']);context=ssl.SSLContext(protocol)
            context.minimum_version=ssl.TLSVersion.TLSv1_2
            context.verify_mode=ssl.CERT_REQUIRED
            context.load_verify_locations(cadata=read_asset(root/CA.lstrip('/')).decode('ascii'))
            context.load_cert_chain(str(root/CERT.lstrip('/')),str(root/KEY.lstrip('/')),password='')
            contexts.append(context)
        peers=handshake(*contexts,server_hostname=config(client)['peer'])
        # This opted-in profile requires exact DNS SANs in both leaves. It
        # deliberately adds no wildcard or legacy CN matching implementation.
        for peer,node in zip(peers,(client,server)):
            expected=config(node)['peer']
            if not any(kind=='DNS' and name.lower()==expected for kind,name in peer.getpeercert().get('subjectAltName',())):
                raise ValueError(node['name']+': peer requires exact DNS SAN '+expected)
    except (OSError,ValueError,ssl.SSLError) as error:
        raise RuntimeFailure('Syslog TLS offline peer validation failed: '+str(error)) from error


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
