"""Real Net-SNMP v2c read-only agent with a bounded system/interface view."""
import ipaddress
from pathlib import Path
import re
from .service_config import observe_config

BINARY = '/usr/lib/network-labs/snmpd'
CONFIG = '/lab/snmpd.conf'
MODULES = 'system_mib,ifTable,ifXTable,interface,vacm_conf'
VIEW = ('.1.3.6.1.2.1.1.3', '.1.3.6.1.2.1.1.5', '.1.3.6.1.2.1.2', '.1.3.6.1.2.1.31.1.1')


def validate_node(node):
    from .lan import addresses
    from .spec import keys
    config = node.setdefault('snmp_agent', None)
    if config is None: return
    keys(config, ('interface', 'community', 'managers'), 'SNMP agent')
    port = config.get('interface'); values = addresses(node)
    if (node['runtime'] != 'oci' or not isinstance(port, str) or not values.get(port) or
            port in node['shutdown'] or node.get('startup')):
        raise ValueError('SNMP agent requires a numbered UP OCI IPv4 interface and no unmanaged startup.')
    interface = ipaddress.IPv4Interface(values[port]); local = interface.ip
    if (local.is_unspecified or local.is_multicast or local.is_loopback or local.is_reserved or
            (interface.network.prefixlen < 31 and local in (interface.network.network_address, interface.network.broadcast_address))):
        raise ValueError('SNMP agent requires a usable IPv4 address.')
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
    config = node['snmp_agent']
    return '\n'.join([
        'agentAddress udp:' + listen_address(node) + ':161',
        '[snmp] persistentDir /run/snmp',
        'dontLogTCPWrappersConnects yes',
        'sysName ' + node['name'],
        'maxGetbulkRepeats 10', 'maxGetbulkResponses 32',
        *['com2sec NetworkLabsSecurity ' + ip + ' ' + config['community'] for ip in config['managers']],
        'group NetworkLabsGroup v2c NetworkLabsSecurity',
        *['view NetworkLabsView included ' + oid for oid in VIEW],
        'access NetworkLabsGroup "" v2c noauth exact NetworkLabsView none none',
        '',
    ])


def prepare_files(bundle, node):
    if node.get('snmp_agent'):
        path = Path(bundle) / 'files/snmpd.conf'; path.write_text(config_text(node)); path.chmod(0o600)


def command():
    # No host config/persistent state, textual MIB files, AgentX or host-resource
    # modules. The selected interface modules read this node's network namespace.
    return [BINARY, '-f', '-Lo', '-C', '-c', CONFIG, '-p', '/run/snmpd.pid', '-m', '', '-I', MODULES]


def start_server(manager, node):
    manager.crun('exec', node['name'], '/bin/busybox', 'mkdir', '-p', '/run/snmp')
    manager.crun('exec', '--detach', node['name'], *command(), log=manager.directory / node['name'] / 'snmp.log')


def start_servers(manager):
    for node in manager.state['spec']['nodes']:
        if node.get('snmp_agent'): start_server(manager, node)


def observe(manager, node):
    check = observe_config(manager, node['name'], CONFIG, config_text(node))
    return {'configuration_verified': check['configuration_verified'], 'file': check,
            'address': listen_address(node), 'port': 161, 'transport': 'udp', 'version': '2c',
            'managers': node['snmp_agent']['managers'], 'view': list(VIEW), 'read_only': True,
            'note': 'Managed config conformity, not daemon liveness or a successful SNMP query. Community is plaintext on the wire and in startup declarations. Source-IP policy is not authentication or anti-spoofing. sysUpTime is agent uptime; IF-MIB is node/kernel data, not vendor hardware. No SNMPv1 access, v3 credentials, traps/informs or runtime counter snapshot.'}


def drift(manager, node):
    return [node['name'] + ': SNMP configuration differs or is unavailable'] if node.get('snmp_agent') and not observe(manager, node)['configuration_verified'] else []


def rootfs_assets(binary):
    from .dns_rootfs import assets
    return assets(binary, destination=BINARY, version_args=('-v',), identity='Net-SNMP',
                  version_check=lambda r: r.returncode == 0 and 'net-snmp version:' in (r.stdout + r.stderr).lower())
