"""IPv4 forward filtering inside a firewall micro-VM, from the same policy schema as container firewalls.

The guest kernel offers iptables but not nf_tables, so the image carries the legacy
iptables program and the agent drives it through typed requests. Address translation
uses the guest's iptables nat table: destination NAT in PREROUTING, masquerade and
source NAT in POSTROUTING. A guest kernel without that table is reported as such; a
policy without NAT never needs it.
"""
from .guest_control import request

RULE_FIELDS = ('in', 'out', 'protocol', 'source', 'destination', 'dport')
NAT_FIELDS = ('type', 'in', 'out', 'protocol', 'source', 'destination', 'dport', 'to', 'to_port')


def validate(node):
    policy = node['firewall']
    for entry in policy['nat']:
        # iptables matches the input port only before routing and the output port only after it.
        if entry['type'] != 'dnat' and 'in' in entry:
            raise ValueError('Micro-VM firewall: source NAT and masquerade match the outbound port only; remove in.')
    for entry in [*policy['rules'], *policy['nat']]:
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


def expected_nat(policy):
    """The nat table rules a guest must hold: PREROUTING (dnat) entries, then POSTROUTING ones, each in declared order."""
    ordered = [e for e in policy['nat'] if e['type'] == 'dnat'] + [e for e in policy['nat'] if e['type'] != 'dnat']
    return [{key: entry[key] for key in NAT_FIELDS if key in entry and (key != 'protocol' or entry[key] != 'any')} for entry in ordered]


def _no_nat_table(result):
    """True when the guest cannot hold NAT at all: an agent that predates NAT, or a kernel without the nat table."""
    text = result['output']
    return result['exit_code'] != 0 and ('unsupported operation' in text or 'does not exist' in text or "can't initialize" in text)


def _detail(result):
    detail = result['output'].strip()
    if result['exit_code'] == 127:
        return 'the guest image has no iptables; rebuild it with --with-firewall'
    if _no_nat_table(result):
        return 'the guest kernel (or agent) has no IPv4 NAT table; address translation cannot run on this guest'
    if "Couldn't load target" in detail:
        return detail + ' (rebuild the guest image with the current --with-firewall to include the NAT target modules)'
    return detail


def _run(socket, operation, **arguments):
    result = request(socket, operation, **arguments)
    if result['exit_code']:
        raise ValueError(f'Guest {operation} failed: {_detail(result)}')
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


def parse_nat(listing):
    """Read `iptables -t nat -S` back into the comparable form of expected_nat()."""
    names = {'-i': 'in', '-o': 'out', '-p': 'protocol', '-s': 'source', '-d': 'destination'}
    targets = {'DNAT': ('dnat', 'PREROUTING'), 'SNAT': ('snat', 'POSTROUTING'), 'MASQUERADE': ('masquerade', 'POSTROUTING')}
    chains, rules = {}, {'PREROUTING': [], 'POSTROUTING': []}
    for line in listing.splitlines():
        words = line.split()
        if len(words) == 3 and words[0] == '-P' and words[1] in ('PREROUTING', 'INPUT', 'OUTPUT', 'POSTROUTING'):
            chains[words[1]] = words[2]; continue
        if len(words) < 2 or words[0] != '-A' or words[1] not in rules:
            raise ValueError('Unexpected guest NAT line: ' + line)
        rule, index, chain = {}, 2, words[1]
        while index < len(words):
            option = words[index]
            if index + 1 >= len(words):
                raise ValueError('Truncated guest NAT rule: ' + line)
            value = words[index + 1]; index += 2
            if option == '-m': continue
            if option in names: rule[names[option]] = value
            elif option == '--dport': rule['dport'] = int(value)
            elif option == '-j' and value in targets and targets[value][1] == chain: rule['type'] = targets[value][0]
            elif option in ('--to-destination', '--to-source'):
                address, _, port = value.partition(':'); rule['to'] = address
                if port: rule['to_port'] = int(port)
            else: raise ValueError('Unmanaged guest NAT option: ' + line)
        if 'type' not in rule:
            raise ValueError('Unmanaged guest NAT target: ' + line)
        rules[chain].append(rule)
    if chains != dict.fromkeys(('PREROUTING', 'INPUT', 'OUTPUT', 'POSTROUTING'), 'ACCEPT'):
        raise ValueError('Guest NAT chain policies must all accept.')
    return rules['PREROUTING'] + rules['POSTROUTING']


def observe(socket):
    return parse(_run(socket, 'firewall-list'))


def observe_nat(socket):
    """The guest's NAT rules, or None when it has no nat table (and so cannot be translating)."""
    result = request(socket, 'firewall-nat-list')
    if _no_nat_table(result):
        return None
    if result['exit_code']:
        raise ValueError(f'Guest firewall-nat-list failed: {_detail(result)}')
    return parse_nat(result['output'])


def check(socket, node):
    if observe(socket) != expected(node['firewall']):
        raise ValueError('Guest firewall rules differ from the declared policy.')
    nat = observe_nat(socket)
    if node['firewall']['nat'] and nat is None:
        raise ValueError('Guest firewall has no IPv4 NAT table; address translation cannot run on this guest.')
    if (nat or []) != expected_nat(node['firewall']):
        raise ValueError('Guest firewall NAT rules differ from the declared policy.')


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
    # NAT is rebuilt while forwarding still drops. A guest without a nat table is fine only for a policy without NAT.
    flushed = request(socket, 'firewall-nat-flush')
    if flushed['exit_code'] and (policy['nat'] or not _no_nat_table(flushed)):
        raise ValueError(f'Guest firewall-nat-flush failed: {_detail(flushed)}')
    for entry in expected_nat(policy):
        _run(socket, 'firewall-nat-rule', rule=entry)
    _run(socket, 'firewall-policy', state=policy['default'])
    check(socket, node)
