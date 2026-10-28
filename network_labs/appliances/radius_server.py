"""Separate-node, bounded FreeRADIUS 3 PAP server; no access enforcement."""
import ipaddress
from pathlib import Path
import re
import subprocess
import time

from .radius_accounting_writer import SCRIPT, WRITER

BINARY = '/usr/lib/network-labs/freeradius/server'
MODULES = '/usr/lib/network-labs/freeradius/modules'
DICTIONARY = '/usr/lib/network-labs/freeradius/dictionary'
DIRECTORY = '/lab/radius'
CONFIG = DIRECTORY + '/radiusd.conf'
ACCOUNTING_DIRECTORY = '/run/network-labs-radius-accounting'
ACCOUNTING_FILE = ACCOUNTING_DIRECTORY + '/sessions'


def validate_node(node):
    from .spec import keys
    policy = node.setdefault('radius_server', None)
    if policy is None: return
    keys(policy, ('interface', 'clients', 'users', 'accounting'), 'RADIUS server')
    if type(policy.setdefault('accounting', False)) is not bool:
        raise ValueError('RADIUS server accounting must be boolean.')
    port = policy.get('interface')
    if (node['runtime'] != 'oci' or node['role'] != 'host' or set(node['interfaces']) != {'eth0'} or
            port != 'eth0' or not node['interfaces']['eth0'] or port in node['shutdown'] or node.get('startup') or
            node.get('subinterfaces') or node.get('port_channels') or node.get('interface_aliases')):
        raise ValueError('RADIUS requires a numbered UP single-interface OCI host without unmanaged startup.')
    local = ipaddress.IPv4Interface(node['interfaces'][port])
    if (local.ip.is_unspecified or local.ip.is_multicast or local.ip.is_loopback or local.ip.is_reserved or
            (local.network.prefixlen < 31 and local.ip in (local.network.network_address, local.network.broadcast_address))):
        raise ValueError('RADIUS requires a usable unicast IPv4 address.')
    if any(node.get(key) for key in ('tftp_server', 'ntp_server', 'snmp_agent', 'snmp_receiver', 'syslog_server',
            'management', 'dns_server', 'dhcp_server', 'dhcp_pools', 'dhcp_clients', 'dhcp_relay', 'firewall',
            'dhcpv6_server', 'router_advertisements', 'lldp', 'ospf')):
        raise ValueError('Initial RADIUS profile requires a separate service node.')
    clients = policy.get('clients')
    if not isinstance(clients, list) or not 1 <= len(clients) <= 8:
        raise ValueError('RADIUS requires 1..8 explicit IPv4 clients.')
    seen = set()
    for client in clients:
        keys(client, ('address', 'secret'), 'RADIUS client')
        if not isinstance(client.get('address'), str): raise ValueError('RADIUS client address must be IPv4.')
        address = ipaddress.IPv4Address(client['address'])
        if (address.is_unspecified or address.is_multicast or address.is_loopback or address.is_reserved or
                address == local.ip or str(address) in seen):
            raise ValueError('RADIUS clients must be distinct remote unicast IPv4 addresses.')
        seen.add(str(address)); client['address'] = str(address)
        if not isinstance(client.get('secret'), str) or not re.fullmatch(r'[A-Za-z0-9_.~-]{16,128}', client['secret']):
            raise ValueError('Managed RADIUS secrets require 16..128 ASCII letters, digits, _, ., ~ or -.')
    users = policy.get('users')
    if not isinstance(users, dict) or not 1 <= len(users) <= 16:
        raise ValueError('RADIUS requires 1..16 declared users.')
    for username, user in users.items():
        if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}', username):
            raise ValueError('RADIUS usernames require 1..64 ASCII login characters.')
        keys(user, ('password_sha256',), 'RADIUS user')
        if not isinstance(user.get('password_sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', user['password_sha256']):
            raise ValueError('RADIUS users require a lowercase SHA-256 password digest.')
    policy['clients'] = sorted(clients, key=lambda value: value['address'])
    policy['users'] = dict(sorted(users.items()))


def validate_lab(spec):
    for node in spec['nodes']:
        if not node.get('radius_server'): continue
        for client in node['radius_server']['clients']:
            matches = [other for other in spec['nodes'] if any(value and str(ipaddress.IPv4Interface(value).ip) == client['address']
                       for value in other['interfaces'].values())]
            if (len(matches) != 1 or matches[0]['name'] == node['name'] or matches[0]['runtime'] != 'oci' or
                    matches[0]['role'] != 'host' or set(matches[0]['interfaces']) != {'eth0'}):
                raise ValueError('Each RADIUS client must identify exactly one other managed OCI host.')


def config_text(node, *, modules=MODULES, run_directory='/run', port=1812, accounting_port=1813, accounting_writer=SCRIPT):
    policy = node['radius_server']; address = str(ipaddress.IPv4Interface(node['interfaces'][policy['interface']]).ip)
    clients = '\n'.join('''client lab_%d {
    ipaddr = %s
    secret = "%s"
    require_message_authenticator = yes
}''' % (index, client['address'], client['secret']) for index, client in enumerate(policy['clients']))
    users = '\n'.join('''        if (&User-Name == "%s") {
            update control {
                SHA2-Password := 0x%s
            }
        }''' % (name, user['password_sha256']) for name, user in policy['users'].items())
    accounting_module = accounting_server = ''
    if policy.get('accounting'):
        accounting_module = '''
    exec session_accounting {
        wait = yes
        program = "/bin/busybox sh '%s' '%s/network-labs-radius-accounting/sessions'"
        input_pairs = request
        shell_escape = yes
        timeout = 2
    }''' % (accounting_writer, run_directory)
        accounting_server = '''
    listen {
        type = acct
        ipaddr = %s
        port = %d
    }
    accounting {
        session_accounting
    }''' % (address, accounting_port)
    return '''prefix = /usr
logdir = "%(run)s"
run_dir = "%(run)s"
libdir = "%(modules)s"
pidfile = "%(run)s/network-labs-radius.pid"
max_request_time = 5
cleanup_delay = 0
max_requests = 32
log {
    destination = stdout
    auth = no
    auth_goodpass = no
    auth_badpass = no
}
security {
    max_attributes = 32
    reject_delay = 0
    status_server = no
}
%(clients)s
modules {
    pap {
        normalise = no
    }%(accounting_module)s
}
server lab {
    listen {
        type = auth
        ipaddr = %(address)s
        port = %(port)s
    }
    authorize {
        update reply {
            Message-Authenticator := 0x00000000000000000000000000000000
        }
%(users)s
        pap
    }
    authenticate {
        Auth-Type PAP {
            pap
        }
    }
    post-auth {
        Post-Auth-Type REJECT {
            update reply {
                Message-Authenticator := 0x00000000000000000000000000000000
            }
        }
    }%(accounting_server)s
}
''' % dict(run=run_directory, modules=modules, address=address, port=port, clients=clients, users=users,
           accounting_module=accounting_module, accounting_server=accounting_server)


def prepare_files(bundle, node):
    if not node.get('radius_server'): return
    root = Path(bundle) / 'files/radius'; root.mkdir(mode=0o700)
    path = root / 'radiusd.conf'; path.write_text(config_text(node)); path.chmod(0o600)
    if node['radius_server'].get('accounting'):
        writer = root / 'accounting-write.sh'; writer.write_text(WRITER); writer.chmod(0o700)
    (root / 'dictionary').write_text('# Installed base dictionary selected with -D.\n')


def command():
    return [BINARY, '-f', '-s', '-P', '-d', DIRECTORY, '-D', DICTIONARY]


def start_servers(manager):
    from .runtime import RuntimeFailure
    for node in manager.state['spec']['nodes']:
        if not node.get('radius_server'): continue
        if node['radius_server'].get('accounting'):
            applets = manager.crun('exec', node['name'], '/bin/busybox', '--list', check=False, timeout=3)
            if applets.returncode or not {'sh', 'stat', 'printf', 'tail', 'truncate'} <= set(applets.stdout.splitlines()):
                raise RuntimeFailure(node['name'] + ': RADIUS accounting requires BusyBox writer applets.')
            manager.crun('exec', node['name'], '/bin/busybox', 'mkdir', '-p', '-m', '700', ACCOUNTING_DIRECTORY)
        args = command()
        checked = manager.crun('exec', node['name'], *args, '-C', check=False, timeout=5)
        if checked.returncode:
            # Parser output may quote credential-bearing configuration lines.
            raise RuntimeFailure(node['name'] + ': FreeRADIUS configuration rejected; private configuration not echoed.')
        log = manager.directory / node['name'] / 'radius.log'
        log.touch(mode=0o600, exist_ok=True)
        launched = manager.crun('exec', '--detach', node['name'], *args, log=log, check=False)
        if launched.returncode:
            raise RuntimeFailure(node['name'] + ': FreeRADIUS launch failed; private log not echoed.')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with log.open('rb') as source:
                source.seek(max(0, log.stat().st_size - 65536))
                ready = b'Ready to process requests' in source.read(65536)
            if ready: break
            time.sleep(.05)
        else:
            raise RuntimeFailure(node['name'] + ': FreeRADIUS did not report readiness; private log not echoed.')


def redact(value):
    """Normal CLI results omit RADIUS credentials; explicit export is separate."""
    if isinstance(value, list): return [redact(item) for item in value]
    if not isinstance(value, dict): return value
    result = {key: redact(item) for key, item in value.items()}
    if isinstance(result.get('radius_server'), dict):
        policy = result['radius_server']
        for client in policy.get('clients', []):
            if isinstance(client, dict) and 'secret' in client: client['secret'] = '[redacted]'
        for user in policy.get('users', {}).values():
            if isinstance(user, dict) and 'password_sha256' in user: user['password_sha256'] = '[redacted]'
    return result


def observe(manager, node):
    # Read only hashes: even errors cannot echo a secret-bearing config line.
    import hashlib
    from .radius_observation import observe_process
    from .ntp_socket import observe_socket
    evidence = {'configuration_verified': False, 'configuration_available': False, 'permissions_verified': False}
    try:
        result = manager.crun('exec', node['name'], '/bin/busybox', 'sha256sum', CONFIG, check=False, timeout=3)
        match = re.fullmatch(r'([0-9a-f]{64})  ' + re.escape(CONFIG) + r'\n?', result.stdout)
        evidence['configuration_available'] = result.returncode == 0 and bool(match)
        modes = manager.crun('exec', node['name'], '/bin/busybox', 'stat', '-c', '%a:%u:%g', CONFIG, DIRECTORY,
                             check=False, timeout=3)
        evidence['permissions_verified'] = modes.returncode == 0 and modes.stdout == '600:0:0\n700:0:0\n'
        evidence['configuration_verified'] = bool(evidence['configuration_available'] and evidence['permissions_verified'] and
            match.group(1) == hashlib.sha256(config_text(node).encode()).hexdigest())
        if node['radius_server'].get('accounting'):
            writer = manager.crun('exec', node['name'], '/bin/busybox', 'sha256sum', SCRIPT, check=False, timeout=3)
            mode = manager.crun('exec', node['name'], '/bin/busybox', 'stat', '-c', '%a:%u:%g', SCRIPT, check=False, timeout=3)
            evidence['writer_verified'] = (writer.returncode == 0 and writer.stdout ==
                hashlib.sha256(WRITER.encode()).hexdigest() + '  ' + SCRIPT + '\n' and
                mode.returncode == 0 and mode.stdout == '700:0:0\n')
            evidence['configuration_verified'] &= evidence['writer_verified']
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
        pass
    address = str(ipaddress.IPv4Interface(node['interfaces']['eth0']).ip)
    return {**evidence, 'process': observe_process(manager, node),
            'udp_socket': observe_socket(manager, node, address, port=1812),
            'accounting': {'enabled': True, 'udp_socket': observe_socket(manager, node, address, port=1813),
                           'storage': 'Private ephemeral verified records; not saved with lab configuration.'}
                          if node['radius_server'].get('accounting') else {'enabled': False},
            'clients': [client['address'] for client in node['radius_server']['clients']],
            'user_count': len(node['radius_server']['users']),
            'note': 'Configuration, PID/argv and UDP/1812 are separate sequential observations. A socket is not attributed to FreeRADIUS; PID reuse and state changes may occur. None proves authentication or access. No shared secret or password digest is returned.'}


def drift(manager, node):
    return [node['name'] + ': RADIUS configuration differs or is unavailable'] if node.get('radius_server') and not observe(manager, node)['configuration_verified'] else []
