"""Real read-only Net-SNMP v2c or USM authPriv agents with a scoped view."""
import ipaddress
import hashlib
import secrets
from pathlib import Path
import re
from .service_config import observe_config

BINARY = '/usr/lib/network-labs/snmpd'
CONFIG = '/lab/snmpd.conf'
MODULES = 'system_mib,ifTable,ifXTable,interface,vacm_conf'
VIEW = ('.1.3.6.1.2.1.1.3', '.1.3.6.1.2.1.1.5', '.1.3.6.1.2.1.2', '.1.3.6.1.2.1.31.1.1')


def master_key(passphrase):
    """RFC 3414/7860 password-to-Ku for SHA-256; no engine localization here."""
    if not isinstance(passphrase, str) or not 8 <= len(passphrase) <= 128 or any(not 32 <= ord(c) <= 126 for c in passphrase):
        raise ValueError('SNMPv3 passphrase requires 8..128 printable ASCII characters.')
    raw = passphrase.encode('ascii')
    return hashlib.sha256((raw * ((1048576 + len(raw) - 1) // len(raw)))[:1048576]).hexdigest()


def validate_usm(user):
    from .spec import keys
    keys(user, ('username', 'auth_master_key', 'privacy_master_key'), 'SNMPv3 USM')
    name = user.get('username')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}', name):
        raise ValueError('SNMPv3 username requires 1..32 ASCII identifier characters, starting with a letter.')
    for field in ('auth_master_key', 'privacy_master_key'):
        value = user.get(field)
        if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', value):
            raise ValueError('SNMPv3 requires 32-byte SHA-256 master keys encoded as 64 hex characters.')
        user[field] = value.lower()


def usm_credentials(username, auth_passphrase, privacy_passphrase):
    user = {'username': username, 'auth_master_key': master_key(auth_passphrase),
            'privacy_master_key': master_key(privacy_passphrase)}
    validate_usm(user)
    return user


def client_config(user):
    """Protected Net-SNMP client config; keys are credential-equivalent secrets."""
    user = dict(user); validate_usm(user)
    return '\n'.join(['defVersion 3', 'defSecurityLevel authPriv', 'defSecurityName ' + user['username'],
                       'defAuthType SHA-256', 'defPrivType AES',
                       'defAuthMasterKey 0x' + user['auth_master_key'],
                       'defPrivMasterKey 0x' + user['privacy_master_key'], ''])


def validate_node(node):
    from .lan import addresses
    from .spec import keys
    config = node.setdefault('snmp_agent', None)
    if config is None: return
    keys(config, ('interface', 'community', 'managers', 'usm'), 'SNMP agent')
    port = config.get('interface'); values = addresses(node)
    if (node['runtime'] != 'oci' or not isinstance(port, str) or not values.get(port) or
            port in node['shutdown'] or node.get('startup')):
        raise ValueError('SNMP agent requires a numbered UP OCI IPv4 interface and no unmanaged startup.')
    interface = ipaddress.IPv4Interface(values[port]); local = interface.ip
    if (local.is_unspecified or local.is_multicast or local.is_loopback or local.is_reserved or
            (interface.network.prefixlen < 31 and local in (interface.network.network_address, interface.network.broadcast_address))):
        raise ValueError('SNMP agent requires a usable IPv4 address.')
    if 'usm' in config:
        if 'community' in config:
            raise ValueError('Choose one SNMP profile: v2c community or v3 USM, without fallback.')
        validate_usm(config['usm'])
    else:
        community = config.get('community')
        if not isinstance(community, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', community):
            raise ValueError('SNMP community requires 8..64 ASCII letters, digits, underscore or hyphen.')
    managers = config.get('managers')
    if not isinstance(managers, list) or not 1 <= len(managers) <= 16 or not all(isinstance(v, str) for v in managers):
        raise ValueError('SNMP requires 1..16 explicit IPv4 manager addresses.')
    canonical = []
    for value in managers:
        address = ipaddress.IPv4Address(value)
        if address.is_unspecified or address.is_multicast or address.is_loopback or address.is_reserved or address == local:
            raise ValueError('SNMP managers must be remote unicast IPv4 addresses.')
        canonical.append(str(address))
    config['managers'] = sorted(set(canonical))


def validate_lab(spec):
    from .lan import addresses
    for node in spec['nodes']:
        config = node.get('snmp_agent')
        if not config: continue
        for address in config['managers']:
            peers = [n['name'] for n in spec['nodes'] if any(v and str(ipaddress.IPv4Interface(v).ip) == address for v in addresses(n).values())]
            if len(peers) != 1 or peers[0] == node['name']:
                raise ValueError('SNMP manager must be one other uniquely numbered managed IPv4 node.')


def listen_address(node):
    from .lan import addresses
    return str(ipaddress.IPv4Interface(addresses(node)[node['snmp_agent']['interface']]).ip)


def config_text(node):
    config = node['snmp_agent']; user = config.get('usm')
    views = ['view NetworkLabsView included ' + oid for oid in VIEW]
    if user:
        policy = ['sourceFilterType acceptlist', *['sourceFilterAddress ' + ip for ip in config['managers']],
                  'createUser ' + user['username'] + ' SHA-256 -m 0x' + user['auth_master_key'] + ' AES -m 0x' + user['privacy_master_key'],
                  'group NetworkLabsGroup usm ' + user['username'], *views,
                  'access NetworkLabsGroup "" usm priv exact NetworkLabsView none none']
    else:
        policy = [*['com2sec NetworkLabsSecurity ' + ip + ' ' + config['community'] for ip in config['managers']],
                  'group NetworkLabsGroup v2c NetworkLabsSecurity', *views,
                  'access NetworkLabsGroup "" v2c noauth exact NetworkLabsView none none']
    return '\n'.join([
        'agentAddress udp:' + listen_address(node) + ':161', '[snmp] persistentDir /run/snmp',
        'dontLogTCPWrappersConnects yes', 'sysName ' + node['name'],
        'maxGetbulkRepeats 10', 'maxGetbulkResponses 32',
        *policy, '',
    ])


def prepare_files(bundle, node):
    if node.get('snmp_agent'):
        path = Path(bundle) / 'files/snmpd.conf'; path.write_text(config_text(node)); path.chmod(0o600)


def command(node=None, engine_id=None):
    # Each v3 daemon instance gets a fresh identity: -C skips old runtime state,
    # and Net-SNMP localizes supplied master keys against this new engine ID.
    v3 = bool(node and node['snmp_agent'].get('usm'))
    if v3 and (not isinstance(engine_id, str) or not re.fullmatch(r'[0-9a-f]{24}', engine_id)):
        raise ValueError('SNMPv3 startup requires a fresh runtime engine token.')
    return [BINARY, '-f', '-Lo', '-C', '-c', CONFIG, '-p', '/run/snmpd.pid', '-m', '', '-I',
            MODULES + (',usmConf' if v3 else '')] + (['--engineID=' + engine_id] if v3 else [])


def start_server(manager, node):
    manager.crun('exec', node['name'], '/bin/busybox', 'mkdir', '-p', '/run/snmp')
    manager.crun('exec', '--detach', node['name'], *command(node, secrets.token_hex(12)), log=manager.directory / node['name'] / 'snmp.log')


def start_servers(manager):
    for node in manager.state['spec']['nodes']:
        if node.get('snmp_agent'): start_server(manager, node)


def observe(manager, node):
    check = observe_config(manager, node['name'], CONFIG, config_text(node))
    user = node['snmp_agent'].get('usm')
    return {'configuration_verified': check['configuration_verified'], 'file': check,
            'address': listen_address(node), 'port': 161, 'transport': 'udp', 'version': '3' if user else '2c',
            'managers': node['snmp_agent']['managers'], 'view': list(VIEW), 'read_only': True,
            'security': {'level': 'authPriv', 'username': user['username'], 'authentication': 'SHA-256', 'privacy': 'AES-128',
                         'engine_identity': 'Fresh per daemon start; clients must rediscover.'} if user else {'level': 'community'},
            'note': 'Managed config conformity, not daemon liveness, loaded policy or a successful SNMP query. '
                    + ('USM master keys are credential-equivalent secrets in startup declarations. Fresh engine identity after restart/restore, not a runtime session snapshot. ' if user else 'Community is plaintext on the wire and in startup declarations. ')
                    + 'Source-IP policy is not anti-spoofing. sysUpTime is agent uptime; IF-MIB is node/kernel data, not vendor hardware. No SNMPv1 access, traps/informs or runtime counter snapshot.'}


def drift(manager, node):
    return [node['name'] + ': SNMP configuration differs or is unavailable'] if node.get('snmp_agent') and not observe(manager, node)['configuration_verified'] else []


def rootfs_assets(binary):
    from .dns_rootfs import assets
    return assets(binary, destination=BINARY, version_args=('-v',), identity='Net-SNMP',
                  version_check=lambda r: r.returncode == 0 and 'net-snmp version:' in (r.stdout + r.stderr).lower())
