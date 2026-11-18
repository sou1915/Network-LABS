"""IOS EXEC commands beyond the ones read from the guest: version, CDP, interfaces, startup configuration, history, clock.

Each answer is built from what the lab holds: the device's model and ports, its configuration (and the stored IOS
lines), its cables and its neighbours' names, the observation of the running guest (or of the project while the lab is
stopped). Nothing is invented that the lab does not hold: interface counters, for one, are not shown.
"""
import datetime
import ipaddress
import re

from . import ios_store
from .native_models import MODELS, port_names
from .vendor_config import ios_name

SHOWS = ['show ip nat translations', 'show ip nat statistics', 'show version', 'show cdp neighbors', 'show cdp neighbors detail',
         'show interfaces', 'show startup-config', 'show history', 'show clock', 'show users', 'show privilege', 'show ip protocols', 'show interfaces trunk']


def answer(console, low):
    """The reply to an EXEC line this module handles, or None."""
    words = low.split()
    full = ' '.join(_expand(words))
    if full in ('terminal length', 'terminal width') or re.fullmatch(r'terminal (length|width) \d+', full):
        return ''
    if full == 'show version':
        return version(console)
    if full in ('show cdp neighbors', 'show cdp neighbors detail'):
        return cdp(console, detail=full.endswith('detail'))
    if full == 'show interfaces' or re.fullmatch(r'show interfaces \S+', full) and words[-1] not in ('trunk',):
        return interfaces(console, None if full == 'show interfaces' else low.split()[-1])
    if full == 'show interfaces trunk':
        return trunks(console)
    if re.fullmatch(r'show running-config interface \S+', full):
        return running_interface(console, low.split()[-1])
    if full == 'show startup-config':
        startup = ios_store.config(console.node()).get('startup')
        return startup if startup else 'startup-config is not present'
    if full == 'show history':
        return '\n'.join('  ' + line for line in console.typed[-10:])
    if full == 'show clock':
        return clock(console)
    if full.startswith('clock set '):
        return set_clock(console, low)
    if full == 'show users':
        return ('    Line       User       Host(s)              Idle       Location\n'
                '*  0 con 0                idle                 00:00:00')
    if full == 'show privilege':
        return f'Current privilege level is {15 if console.mode == "enable" else 1}'
    if full == 'show ip protocols':
        return protocols(console)
    if full in ('show ip nat translations', 'show ip nat statistics'):
        return nat(console, statistics=full.endswith('statistics'))
    if full in ('copy running-config startup-config', 'write memory', 'write'):
        return save(console, copy=full.startswith('copy'))
    if full in ('erase startup-config', 'write erase'):
        console.store_startup(None)
        return 'Erasing the nvram filesystem will remove all configuration files! Continue? [confirm]\n[OK]\n' \
               'Erase of nvram: complete'
    if full == 'reload':
        return '% Network LABS : ■ Arrêter puis ▶ Démarrer redémarre le lab (la configuration enregistrée est conservée).'
    return None


WORDS = {'sh': 'show', 'sho': 'show', 'ver': 'version', 'vers': 'version', 'version': 'version', 'int': 'interfaces',
         'inter': 'interfaces', 'interface': 'interfaces', 'interfaces': 'interfaces', 'nei': 'neighbors', 'neighbors': 'neighbors',
         'det': 'detail', 'detail': 'detail', 'start': 'startup-config', 'startup-config': 'startup-config',
         'run': 'running-config', 'running-config': 'running-config', 'hist': 'history', 'history': 'history',
         'clo': 'clock', 'clock': 'clock', 'priv': 'privilege', 'privilege': 'privilege', 'prot': 'protocols',
         'protocols': 'protocols', 'wr': 'write', 'write': 'write', 'mem': 'memory', 'memory': 'memory', 'copy': 'copy',
         'term': 'terminal', 'terminal': 'terminal', 'len': 'length', 'length': 'length', 'width': 'width',
         'users': 'users', 'cdp': 'cdp', 'nat': 'nat', 'trans': 'translations', 'translations': 'translations',
         'stat': 'statistics', 'statistics': 'statistics', 'ip': 'ip', 'erase': 'erase', 'reload': 'reload', 'trunk': 'trunk', 'set': 'set'}


def _expand(words):
    return [WORDS.get(word, word) for word in words]


def _model(console):
    node = console.node()
    return MODELS.get(node.get('model'), {'brand': 'Cisco', 'model': 'IOS', 'ports': []})


def version(console):
    node, model = console.node(), _model(console)
    name = ios_store.hostname(node)
    ports = port_names(node)
    gig = sum(1 for p in ports.values() if ios_name(p).startswith('Gigabit'))
    fast = sum(1 for p in ports.values() if ios_name(p).startswith('Fast'))
    lines = ['Cisco IOS XE Software, Version 16.09.04 (modèle Network LABS)',
             'Cisco IOS Software [Fuji], ISR Software, Version 16.9.4, RELEASE SOFTWARE',
             'Technical Support: http://www.cisco.com/techsupport',
             '',
             'ROM: IOS-XE ROMMON',
             f'{name} uptime is {console.uptime()}',
             'System image file is "network-labs:micro-vm" (Linux, pas Cisco IOS : le nœud est une micro-VM)',
             '',
             f'cisco {model["model"]} ({node["role"]}) processor with {node.get("memory_mib", 128) * 1024}K bytes of memory.']
    if gig:
        lines.append(f'{gig} Gigabit Ethernet interfaces')
    if fast:
        lines.append(f'{fast} FastEthernet interfaces')
    lines += ['', 'Configuration register is 0x2102']
    return '\n'.join(lines)


def _neighbours(console):
    """(local port, neighbour node, its port) for each cable of this device."""
    spec = console.spec_now()
    nodes = {n['name']: n for n in spec['nodes']}
    found = []
    for a, b in spec['links']:
        for mine, theirs in ((a, b), (b, a)):
            if mine[0] == console.name:
                found.append((mine[1], nodes[theirs[0]], theirs[1]))
    return found


def _label(node, port):
    shown = port_names(node).get(port, port)
    return ios_name(shown) if node.get('model') and MODELS.get(node['model'], {}).get('brand') == 'Cisco' else shown


def cdp(console, detail=False):
    node = console.node()
    if any(line.lower() == 'no cdp run' for line in ios_store.config(node)['global']):
        return '% CDP is not enabled'
    rows = []
    for port, other, their_port in _neighbours(console):
        if any(l.lower() == 'no cdp enable' for l in ios_store.config(node)['interfaces'].get(port, [])):
            continue
        model = MODELS.get(other.get('model'), {})
        if model.get('brand') != 'Cisco':
            continue  # CDP is Cisco's: other brands and PCs do not answer
        capability = {'router': 'R', 'switch': 'S', 'firewall': 'R'}.get(other['role'], 'H')
        rows.append((ios_store.hostname(other), _label(node, port), capability, model.get('model', ''), _label(other, their_port),
                     other))
    if detail:
        blocks = []
        for name, local, capability, platform, remote, other in rows:
            address = next((a.split('/')[0] for a in other['interfaces'].values() if a), None)
            blocks.append('\n'.join(['-------------------------', f'Device ID: {name}', 'Entry address(es): ',
                                     f'  IP address: {address}' if address else '', f'Platform: cisco {platform},  Capabilities: '
                                     + {'R': 'Router', 'S': 'Switch', 'H': 'Host'}[capability],
                                     f'Interface: {local},  Port ID (outgoing port): {remote}', 'Holdtime : 160 sec']))
        return '\n'.join(blocks) if blocks else ''
    lines = ['Capability Codes: R - Router, T - Trans Bridge, B - Source Route Bridge',
             '                  S - Switch, H - Host, I - IGMP, r - Repeater, P - Phone', '',
             f'{"Device ID":<17}{"Local Intrfce":<18}{"Holdtme":<11}{"Capability":<12}{"Platform":<10}Port ID']
    short = lambda port: re.sub(r'^([A-Za-z]{3})[A-Za-z]*\s*', r'\1 ', port)  # GigabitEthernet0/0/1 -> Gig 0/0/1, as IOS
    lines += [f'{name:<17}{short(local):<18}{"160":<11}{capability:<12}{platform[:9].replace(" ", ""):<10}{short(remote)}'
              for name, local, capability, platform, remote, _ in rows]
    return '\n'.join(lines)


def interfaces(console, wanted=None):
    node = console.node()
    observation = console.observe()
    lines = []
    for interface in observation['interfaces']:
        port = interface['port']
        name = _label(node, port.split('.')[0]) + (('.' + port.split('.')[1]) if '.' in port else '')
        if wanted and _short(name) != _short(wanted):
            continue
        shut = port in (node.get('shutdown') or [])
        state = 'administratively down' if shut else ('up' if interface['up'] else 'down')
        protocol = 'up' if interface['up'] and not shut else 'down'
        lines.append(f'{name} is {state}, line protocol is {protocol} ')
        lines.append('  Hardware is ISR4331-3x1GE, address is (micro-VM virtio)')
        description = next((l[12:] for l in ios_store.config(node)['interfaces'].get(port, []) if l.lower().startswith('description ')),
                           None)
        if description:
            lines.append(f'  Description: {description}')
        for address in interface['addresses'][:1]:
            lines.append(f'  Internet address is {address}')
        lines += ['  MTU 1500 bytes, BW 1000000 Kbit/sec, DLY 10 usec,', '  Encapsulation ARPA, loopback not set',
                  '  (compteurs de paquets non relevés par Network LABS)']
    return '\n'.join(lines) if lines else "% Invalid input detected at '^' marker."


def _short(name):
    match = re.fullmatch(r'([A-Za-z]+)\s*([\d/.]+)', name)
    return (match[1][:1].lower(), match[2]) if match else name.lower()  # g0/0/1 = gi0/0/1 = GigabitEthernet0/0/1


def trunks(console):
    node = console.node()
    if node['role'] != 'switch':
        return ''
    rows = [(port, sp) for port, sp in (node.get('switchports') or {}).items() if sp.get('mode') == 'trunk']
    lines = [f'{"Port":<13}{"Mode":<13}{"Encapsulation":<15}{"Status":<13}Native vlan']
    lines += [f'{_label(node, port):<13}{"on":<13}{"802.1q":<15}{"trunking":<13}{sp["native_vlan"]}' for port, sp in rows]
    lines += ['', f'{"Port":<13}Vlans allowed on trunk']
    lines += [f'{_label(node, port):<13}' + ('1-4094' if sp['allowed'] == 'all' else ','.join(map(str, sp['allowed'])))
              for port, sp in rows]
    return '\n'.join(lines)


def running_interface(console, wanted):
    from .vendor_config import render
    text = render(console.spec_now(), console.name)
    blocks = text.split('\n!\n')
    for block in blocks:
        first = block.strip().splitlines()[0] if block.strip() else ''
        if first.lower().startswith('interface ') and _short(first.split()[1]) == _short(wanted):
            return f'Building configuration...\n\nCurrent configuration : {len(block) + 1} bytes\n!\n{block.strip()}\nend'
    return "% Invalid input detected at '^' marker."


def clock(console):
    now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=console.clock_offset)
    return now.strftime('*%H:%M:%S.%f')[:-3] + now.strftime(' UTC %a %b %d %Y')


def set_clock(console, low):
    match = re.fullmatch(r'clock set (\d{1,2}):(\d{2}):(\d{2}) (\d{1,2}) ([a-z]+) (\d{4})', low)
    if not match:
        return '% Incomplete command.'
    months = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
    month = next((i for i, m in enumerate(months, 1) if match[5].startswith(m)), None)
    if month is None:
        return "% Invalid input detected at '^' marker."
    wanted = datetime.datetime(int(match[6]), month, int(match[4]), int(match[1]), int(match[2]), int(match[3]),
                               tzinfo=datetime.timezone.utc)
    console.clock_offset = (wanted - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    return ''


def protocols(console):
    node = console.node()
    lines = []
    if node.get('ospf'):
        ospf = node['ospf']
        lines += [f'Routing Protocol is "ospf {ospf["process_id"]}"', f'  Router ID {ospf["router_id"]}',
                  '  Number of areas in this router is 1. 1 normal 0 stub 0 nssa', '  Routing for Networks:']
        for network in ospf['networks']:
            value = ipaddress.IPv4Network(network)
            lines.append(f'    {value.network_address} {value.hostmask} area 0')
        lines.append('  Distance: (default is 110)')
    if node.get('bgp'):
        bgp = node['bgp']
        lines += ['', f'Routing Protocol is "bgp {bgp["asn"]}"', '  Neighbor(s):']
        lines += [f'    {n["address"]}' for n in bgp['neighbors']]
        lines.append('  Distance: external 20 internal 200 local 200')
    rip = next((b for b in ios_store.config(node)['blocks'] if b['header'] == 'router rip'), None)
    if rip:
        from .rip import process
        running = process(node)
        lines += ['', 'Routing Protocol is "rip"', '  Sending updates every 5 seconds (Network LABS : rythme accéléré)',
                  f'  Default version control: send version {running["version"] if running else 2}',
                  '  Routing for Networks:'] + [f'    {l.split()[1]}' for l in rip['lines'] if l.startswith('network ')]
        if running:
            passive = [p['port'] for p in running['interfaces'] if p['passive']]
            if passive:
                lines += ['  Passive Interface(s):'] + [f'    {_label(node, p)}' for p in passive]
        lines.append('  Distance: (default is 120)')
    return '\n'.join(lines)


def save(console, copy=False):
    from .vendor_config import render
    text = render(console.spec_now(), console.name)
    body = '\n'.join(l for l in text.splitlines() if not l.startswith(('! Network LABS', '! le nœud')))
    console.store_startup(body)
    return ('Destination filename [startup-config]? \n' if copy else '') + 'Building configuration...\n[OK]'


def nat(console, statistics=False):
    """« show ip nat translations »: the guest kernel's tracked connections that leave translated (PAT)."""
    from .ios_nat import entries
    node = console.node()
    rules = entries(node)
    sessions = [s for s in (console.observe().get('sessions') or [])
                if s.get('reply_destination') and s['reply_destination'] != s['source']]
    if statistics:
        from .vendor_config import port_names
        outside = sorted({ios_name(port_names(node)[r['out']]) for r in rules})
        return '\n'.join([f'Total active translations: {len(sessions)} (0 static, {len(sessions)} dynamic; {len(sessions)} extended)',
                          'Outside interfaces:', *(f'  {name}' for name in outside),
                          f'Dynamic mappings: {len(rules)} (overload)'])
    lines = [f'{"Pro":<5}{"Inside global":<23}{"Inside local":<23}{"Outside local":<23}Outside global']
    for s in sessions:
        port = f':{s["port"]}' if s.get('port') else ''
        lines.append(f'{s["protocol"]:<5}{s["reply_destination"] + port:<23}{s["source"] + port:<23}'
                     f'{s["destination"] + port:<23}{s["destination"] + port}')
    return '\n'.join(lines)
