"""Telnet and SSH into a lab device, as IOS lets them in: what « line vty 0 4 » (or 0 15), the usernames, the RSA key and
« access-class » allow, with IOS's own answers.

The session itself is the target's CLI (guest_console), entered once the login succeeds; the address must answer for
real (a ping from where the command was typed, through the running guests) and no access list on the way may drop the
TCP connection (23 for Telnet, 22 for SSH, through the network model).
"""
import ipaddress
import re

from . import ios_store

REFUSED = '% Connection refused by remote host'
TIMED_OUT = '% Connection timed out; remote host not responding'
DEFAULT_VTY = {'header': 'line vty 0 4', 'lines': ['login']}  # what a Cisco device starts with


def vty(node):
    """The lines of the device's vty block (0 4, else 0 15; IOS's default when none was typed)."""
    blocks = ios_store.config(node)['blocks'] if node.get('cli_config') else []
    return next((b for b in blocks if b['header'] == 'line vty 0 4'),
                next((b for b in blocks if b['header'] == 'line vty 0 15'), DEFAULT_VTY))['lines']


def _value(lines, prefix):
    return next((l for l in lines if l.lower().startswith(prefix)), None)


def transports(node):
    line = _value(vty(node), 'transport input ')
    if line is None:
        return {'telnet', 'ssh'}
    words = set(line.lower().split()[2:])
    return {'telnet', 'ssh'} if 'all' in words else set() if 'none' in words else words


def login(node):
    """'local' (usernames), 'line' (the line password) or None (no login asked)."""
    line = _value(vty(node), 'login')
    return None if line is None else 'local' if line.lower() == 'login local' else 'line'


def line_password(node):
    line = _value(vty(node), 'password ')
    return ios_store.password_of(line) if line else None


def user_ok(node, user, typed):
    """Whether USER (a « username … secret|password … » line) logs in with TYPED."""
    for line in ios_store.config(node)['global'] if node.get('cli_config') else []:
        words = line.split()
        if words[:2] == ['username', user]:
            low = [w.lower() for w in words]
            if 'secret' in low:
                return ios_store.secret_hash(typed) == ios_store.stored_secret(line)
            if 'password' in low:
                return typed == ios_store.password_of(line)
    return False


def has_users(node):
    return any(l.lower().startswith('username ') for l in (ios_store.config(node)['global'] if node.get('cli_config') else []))


def ssh_ready(node):
    """IOS answers SSH once RSA keys exist (« crypto key generate rsa », which needs « ip domain-name »)."""
    lines = [l.lower() for l in (ios_store.config(node)['global'] if node.get('cli_config') else [])]
    return any(l.startswith('crypto key generate rsa') for l in lines) and any(l.startswith('ip domain-name ') for l in lines)


def access_class_allows(node, source):
    """« access-class N in » on the vty lines: the source must be permitted by list N (its first matching entry)."""
    line = _value(vty(node), 'access-class ')
    if line is None:
        return True
    from .acl import evaluate
    name = line.split()[1]
    if name not in (node.get('acls') or {}):
        return True  # IOS lets everything in when the list does not exist
    probe = dict(node, acl_ports={'vty': name})
    return evaluate(probe, 'vty', {'source': str(source), 'destination': '0.0.0.0', 'protocol': 'tcp'}) == 'permit'


def owner(spec, address):
    """The device holding ADDRESS (a port, subinterface or management SVI), or None."""
    from .network_model import addresses
    address = ipaddress.IPv4Address(address)
    for node in spec['nodes']:
        if any(a.ip == address for a in addresses(node).values()):
            return node
    return None


def opening(kind, target, source):
    """Why a TELNET/SSH session to TARGET from SOURCE stops before the login, as IOS says it; None when the login starts."""
    if target is None or target.get('role') == 'host' or target.get('runtime') != 'firecracker':
        return REFUSED
    if kind not in transports(target) or (kind == 'ssh' and not ssh_ready(target)):
        return REFUSED
    if source is not None and not access_class_allows(target, source):
        return REFUSED
    if kind == 'ssh' and login(target) != 'local':
        return REFUSED  # SSH asks a username: login local (or AAA, not in the lab)
    if login(target) == 'line' and not line_password(target):
        return 'Password required, but none set'
    return None


def parse(command):
    """('telnet', None, address) / ('ssh', user, address) for « telnet A » / « ssh -l USER A », else None."""
    words = command.split()
    if len(words) == 2 and words[0].lower() == 'telnet':
        return 'telnet', None, words[1]
    if len(words) == 4 and words[0].lower() == 'ssh' and words[1] == '-l':
        return 'ssh', words[2], words[3]
    if len(words) == 2 and words[0].lower() == 'ssh' and re.fullmatch(r'[^@\s]+@\S+', words[1]):
        user, _, address = words[1].partition('@')
        return 'ssh', user, address
    return None
