"""IPv4 forward filtering inside a firewall micro-VM, from the same policy schema as container firewalls.

The guest kernel offers iptables but not nf_tables, so the image carries the legacy
iptables program and the agent drives it through typed requests. Address translation
is not offered on guests yet and is refused instead of being silently ignored.
"""
from .guest_control import request

RULE_FIELDS = ('in', 'out', 'protocol', 'source', 'destination', 'dport')


def validate(node):
    policy = node['firewall']
    if policy['nat']:
        raise ValueError('Micro-VM firewall: address translation is not available yet; remove nat entries.')
    for entry in policy['rules']:
        for field in ('in', 'out'):
            if field in entry and entry[field] not in node['interfaces']:
                raise ValueError('Unknown firewall interface: ' + str(entry[field]))


def expected(policy):
    """The exact forward chain a guest must hold, in order."""
    rules = [{'state': {'INVALID'}, 'action': 'drop'}]
    if policy['stateful']:
        rules.append({'state': {'RELATED', 'ESTABLISHED'}, 'action': 'accept'})
    for entry in policy['rules']:
        rule = {key: entry[key] for key in RULE_FIELDS if key in entry and (key != 'protocol' or entry[key] != 'any')}
        rules.append({**rule, 'action': entry['action']})
    return {'default': policy['default'], 'rules': rules}


def _run(socket, operation, **arguments):
    result = request(socket, operation, **arguments)
    if result['exit_code']:
        detail = result['output'].strip()
        if result['exit_code'] == 127:
            detail = 'the guest image has no iptables; rebuild it with --with-firewall'
        raise ValueError(f'Guest {operation} failed: {detail}')
    return result['output']


def parse(listing):
    """Read `iptables -S FORWARD` back into the comparable form of expected()."""
    names = {'-i': 'in', '-o': 'out', '-p': 'protocol', '-s': 'source', '-d': 'destination'}
    default, rules = None, []
    for line in listing.splitlines():
        words = line.split()
        if words[:2] == ['-P', 'FORWARD'] and len(words) == 3:
            default = words[2].lower(); continue
        if words[:2] != ['-A', 'FORWARD']:
            raise ValueError('Unexpected guest firewall line: ' + line)
        rule, index = {}, 2
        while index < len(words):
            option = words[index]
            if index + 1 >= len(words):
                raise ValueError('Truncated guest firewall rule: ' + line)
            value = words[index + 1]; index += 2
            if option == '-m': continue  # The match module is implied by the options that follow it.
            if option in names: rule[names[option]] = value
            elif option == '--dport': rule['dport'] = int(value)
            elif option == '--ctstate': rule['state'] = set(value.split(','))
            elif option == '-j': rule['action'] = value.lower()
            else: raise ValueError('Unmanaged guest firewall option: ' + line)
        rules.append(rule)
    if default not in ('accept', 'drop'):
        raise ValueError('Guest firewall policy is unreadable.')
    return {'default': default, 'rules': rules}


def observe(socket):
    return parse(_run(socket, 'firewall-list'))


def check(socket, node):
    if observe(socket) != expected(node['firewall']):
        raise ValueError('Guest firewall rules differ from the declared policy.')


def apply(socket, node):
    """Closed while it changes: drop first, then rebuild, then the declared default."""
    policy = node['firewall']
    _run(socket, 'firewall-policy', state='drop')
    _run(socket, 'firewall-flush')
    _run(socket, 'firewall-state', state='invalid')
    if policy['stateful']:
        _run(socket, 'firewall-state', state='established')
    for entry in policy['rules']:
        rule = {key: entry[key] for key in RULE_FIELDS if key in entry}
        _run(socket, 'firewall-rule', rule={**rule, 'action': entry['action']})
    _run(socket, 'firewall-policy', state=policy['default'])
    check(socket, node)
