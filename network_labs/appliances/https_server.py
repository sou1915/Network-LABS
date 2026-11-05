"""Persistent fixed-response HTTPS inside one owned OCI host."""
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import ssl
import subprocess

BINARY='/usr/lib/network-labs/nginx'
BASE='/etc/network-labs/https'
CA=BASE+'/ca.pem'
CERT=BASE+'/certificate.pem'
KEY=BASE+'/private.key'
CONFIG='/lab/https.conf'
PID='/run/https.pid'
BODY='Network LABS HTTPS ready\\n'


def read_asset(path, private=False):
    path=Path(path)
    if path.is_symlink() or not path.is_file(): raise ValueError('HTTPS identity assets must be regular non-symlink files.')
    with path.open('rb') as source: data=source.read(65537)
    if not data or len(data)>65536: raise ValueError('HTTPS assets must be nonempty and at most 64 KiB.')
    if private:
        if path.stat().st_mode & 0o777 != 0o600 or b'ENCRYPTED' in data:
            raise ValueError('HTTPS key must be a matching unencrypted PEM key with mode 0600.')
    elif b'PRIVATE KEY' in data: raise ValueError('HTTPS public certificate assets must not contain private keys.')
    return data


def identity_assets(ca,certificate,key):
    values={CA:read_asset(ca),CERT:read_asset(certificate),KEY:read_asset(key,True)}
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_verify_locations(cafile=str(ca))
    context.load_cert_chain(str(certificate),str(key),password='')
    verify_identity(context,values[CA])
    return values


def verify_identity(server_context,ca_pem):
    """Validate offline server trust/time/purpose with no sockets or host roots.

    The manifest's address/name remains a separate real-client check. This
    self-check validates supplied local identity assets, not a live daemon.
    """
    client_context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_context.check_hostname=False
    client_context.load_verify_locations(cadata=ca_pem.decode('ascii'))
    client_context.minimum_version=ssl.TLSVersion.TLSv1_2
    from .tls_identity import handshake
    handshake(server_context,client_context)


def install(rootfs, values):
    directory=Path(rootfs)/BASE.lstrip('/');directory.mkdir(parents=True,mode=0o700)
    for name,data in values.items():
        fd=os.open(Path(rootfs)/name.lstrip('/'),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600 if name==KEY else 0o644)
        with os.fdopen(fd,'wb') as output:output.write(data)


def policy(rootfs):
    return {'interface':'eth0','ca_sha256':hashlib.sha256(read_asset(Path(rootfs)/CA.lstrip('/'))).hexdigest(),
            'certificate_sha256':hashlib.sha256(read_asset(Path(rootfs)/CERT.lstrip('/'))).hexdigest()}


def validate_node(node):
    from .spec import keys
    value=node.setdefault('https_server',None)
    if value is None:return
    keys(value,('interface','ca_sha256','certificate_sha256'),'HTTPS server')
    if (node['runtime']!='oci' or node['role']!='host' or set(node['interfaces'])!={'eth0'} or value.get('interface')!='eth0' or
        not node['interfaces']['eth0'] or 'eth0' in node['shutdown'] or node.get('startup') or node.get('ipv6') or node.get('dhcp_clients') or
        any(node.get(k) for k in ('management','syslog_server','radius_server','tftp_server','ntp_server','snmp_agent','snmp_receiver','dns_server'))):
        raise ValueError('HTTPS initially requires a standalone numbered UP single-interface OCI IPv4 host.')
    local=ipaddress.IPv4Interface(node['interfaces']['eth0'])
    if (local.ip.is_unspecified or local.ip.is_multicast or local.ip.is_loopback or local.ip.is_reserved or
        (local.network.prefixlen<31 and local.ip in (local.network.network_address,local.network.broadcast_address))):
        raise ValueError('HTTPS requires a usable IPv4 address.')
    for name in ('ca_sha256','certificate_sha256'):
        if not isinstance(value.get(name),str) or not re.fullmatch('[0-9a-f]{64}',value[name]):
            raise ValueError('HTTPS requires explicit public CA/local certificate file SHA-256 pins.')


def preflight(node):
    if not node.get('https_server'):return None
    from .runtime import RuntimeFailure
    root=Path(node['rootfs']);value=node['https_server']
    try:
        actual=identity_assets(*(root/p.lstrip('/') for p in (CA,CERT,KEY)))
        if hashlib.sha256(actual[CA]).hexdigest()!=value['ca_sha256'] or hashlib.sha256(actual[CERT]).hexdigest()!=value['certificate_sha256']:
            raise ValueError('Public HTTPS pins differ from offline identity assets.')
        if not (root/BINARY.lstrip('/')).is_file():raise ValueError('Rebuild this rootfs with --nginx and HTTPS identity assets.')
        return hashlib.sha256(actual[KEY]).hexdigest()
    except (OSError,ValueError,ssl.SSLError) as error:
        raise RuntimeFailure(node['name']+': HTTPS identity/assets invalid: '+str(error)) from error


def rootfs_assets(binary):
    from .dns_rootfs import assets
    return assets(binary,destination=BINARY,version_args=('-V',),identity='NGINX with HTTP SSL module',
                  version_check=lambda r:r.returncode==0 and 'nginx version:' in (r.stdout+r.stderr) and '--with-http_ssl_module' in (r.stdout+r.stderr))


def files(node):
    address=str(ipaddress.IPv4Interface(node['interfaces']['eth0']).ip)
    text='\n'.join([
        'daemon off;','master_process on;','worker_processes 1;','user https https;','pid '+PID+';',
        'error_log stderr warn;','events { worker_connections 16; }','http {','  access_log off;',
        *('  '+name+'_temp_path /run/https/'+name+';' for name in ('client_body','proxy','fastcgi','uwsgi','scgi')),
        '  server {','    listen '+address+':443 ssl;','    server_name _;',
        '    ssl_certificate '+CERT+';','    ssl_certificate_key '+KEY+';',
        '    ssl_protocols TLSv1.2 TLSv1.3;','    ssl_session_cache off;','    ssl_session_tickets off;',
        '    keepalive_timeout 0;','    client_header_timeout 3s;','    client_body_timeout 3s;','    send_timeout 3s;',
        '    client_max_body_size 1k;','    client_header_buffer_size 1k;','    large_client_header_buffers 2 1k;',
        '    if ($request_method !~ ^(GET|HEAD)$) { return 405; }',
        '    location = / { default_type text/plain; return 200 "'+BODY+'"; }',
        '    location / { return 404; }','  }','}',''])
    return {'https.conf':text}


def prepare_files(bundle,node):
    if node.get('https_server'):
        for name,text in files(node).items():
            path=Path(bundle)/'files'/name;path.write_text(text);path.chmod(0o644)


def command():return [BINARY,'-p','/run/https/','-c',CONFIG,'-e','stderr']


def start_server(manager,node):
    from .runtime import RuntimeFailure
    manager.crun('exec',node['name'],'/bin/busybox','mkdir','-p','/run/https')
    checked=manager.crun('exec',node['name'],*command(),'-t',check=False,timeout=5)
    if checked.returncode:raise RuntimeFailure(node['name']+': HTTPS configuration rejected: '+(checked.stdout+checked.stderr)[-2048:])
    manager.crun('exec','--detach',node['name'],*command(),log=manager.directory/node['name']/'https.log')


def start_servers(manager):
    for node in manager.state['spec']['nodes']:
        if node.get('https_server'):start_server(manager,node)


def observe(manager,node):
    from .service_config import observe_config
    from .runtime import RuntimeFailure
    check=observe_config(manager,node['name'],CONFIG,files(node)['https.conf'])
    identity=False
    try:
        result=manager.crun('exec',node['name'],'/bin/busybox','sha256sum',CA,CERT,KEY,check=False,timeout=3)
        sums={p.strip():h for row in result.stdout.splitlines() if len(parts:=row.split(None,1))==2 for h,p in [parts]}
        mode=manager.crun('exec',node['name'],'/bin/busybox','stat','-c','%a:%u:%g',KEY,check=False,timeout=3)
        expected=manager.read().get('https_key_hashes',{}).get(node['name']);value=node['https_server']
        identity=(result.returncode==0 and mode.returncode==0 and mode.stdout=='600:0:0\n' and sums.get(CA)==value['ca_sha256'] and
                  sums.get(CERT)==value['certificate_sha256'] and expected is not None and sums.get(KEY)==expected)
    except (OSError,ValueError,RuntimeFailure,subprocess.TimeoutExpired):pass
    return {'configuration_verified':check['configuration_verified'] and identity,'files':{'https.conf':check},'identity_verified':identity,
            'address':str(ipaddress.IPv4Interface(node['interfaces']['eth0']).ip),'port':443,
            'scope':'NGINX configuration and identity-asset conformity, not daemon liveness, certificate handshake or delivery. Fixed GET/HEAD / response; no application login, uploads, reverse proxy or runtime session snapshot.'}


def drift(manager,node):
    return [node['name']+': HTTPS configuration/identity differs or is unavailable'] if node.get('https_server') and not observe(manager,node)['configuration_verified'] else []
