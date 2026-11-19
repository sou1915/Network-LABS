"""IOS EXEC commands beyond the ones read from the guest: version, CDP, interfaces, startup configuration, history, clock.

Each answer is built from what the lab holds: the device's model and ports, its configuration (and the stored IOS
lines), its cables and its neighbours' names, the observation of the running guest (or of the project while the lab is
stopped). Nothing is invented that the lab does not hold: interface counters, for one, are not shown.
"""
import datetime
import ipaddress
import re

from . import ios_store, vendor_show
from .native_models import MODELS, port_names
from .vendor_config import ios_name

SHOWS = ['show ip nat translations', 'show ip nat statistics', 'show version', 'show cdp neighbors', 'show cdp neighbors detail',
         'show interfaces', 'show startup-config', 'show history', 'show clock', 'show users', 'show privilege', 'show ip protocols',
         'show interfaces trunk', 'show interfaces status', 'show ip dhcp binding', 'show arp', 'show ip arp',
         'show mac address-table', 'show ip route static', 'show ip eigrp neighbors', 'show spanning-tree']
ROUTE_CODES = {'connected': 'CL', 'static': 'S', 'rip': 'R', 'eigrp': 'D', 'ospf': 'O', 'bgp': 'B'}


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
    if full == 'show interfaces status':
        return status(console)
    if full == 'show ip dhcp binding':
        return bindings(console)
    if full == 'show ip eigrp neighbors':
        return eigrp_neighbors(console)
    if full in ('show arp', 'show ip arp'):
        return arp(console)
    if full in ('show mac address-table', 'show mac-address-table'):
        return mac_table(console)
    match = re.fullmatch(r'show spanning-tree(?: vlan (\d+))?', full)
    if match:
        return spanning_tree(console, int(match[1]) if match[1] else None)
    match = re.fullmatch(r'show ip route (\S+)', full)
    kinds = [k for k in ROUTE_CODES if match and k.startswith(words[-1])]  # the word as typed (« stat » is not statistics)
    if len(kinds) == 1:  # « sh ip ro stat »: only the static routes
        return routes_of(console, ROUTE_CODES[kinds[0]])
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
    if full == 'show users':  # this session marked *: the console, or the vty line a telnet / ssh session came in on
        lines = ['    Line       User       Host(s)              Idle       Location',
                 f'{"   " if console.vty else "*  "}0 con 0                idle                 00:00:00']
        if console.vty:
            lines.append(f'*  2 vty 0     {console.vty["user"]:<11}idle                 00:00:00 {console.vty["from"]}')
        return '\n'.join(lines)
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
         'stat': 'statistics', 'statistics': 'statistics', 'ip': 'ip', 'erase': 'erase', 'reload': 'reload', 'trunk': 'trunk', 'set': 'set',
         'status': 'status', 'dhcp': 'dhcp', 'bind': 'binding', 'binding': 'binding', 'arp': 'arp', 'mac': 'mac',
         'add': 'address-table', 'address-table': 'address-table', 'mac-address-table': 'mac-address-table', 'ro': 'route',
         'route': 'route', 'eigrp': 'eigrp', 'spa': 'spanning-tree', 'span': 'spanning-tree', 'spanning': 'spanning-tree',
         'spanning-tree': 'spanning-tree', 'vl': 'vlan', 'vlan': 'vlan'}


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


def status(console):
    """« show interfaces status » as a Catalyst prints it: connected / notconnect / disabled (shut), VLAN or trunk."""
    from .vendor_config import ios_short
    node = console.node()
    if node['role'] != 'switch':
        return ''
    up = {i['port']: i['up'] for i in console.observe()['interfaces']}
    lines = [f'{"Port":<10}{"Name":<19}{"Status":<13}{"Vlan":<11}{"Duplex":>6} {"Speed":>6} Type']
    for port in node['interfaces']:
        label = _label(node, port)
        shut = port in (node.get('shutdown') or [])
        state = 'disabled' if shut else 'connected' if up.get(port) else 'notconnect'
        switchport = (node.get('switchports') or {}).get(port) or {'mode': 'access', 'vlan': 1}
        vlan = 'trunk' if switchport['mode'] == 'trunk' else str(switchport['vlan'])
        gigabit = label.startswith(('Gigabit', 'TenGigabit'))
        duplex, speed = ('a-full', 'a-1000' if gigabit else 'a-100') if state == 'connected' else ('auto', 'auto')
        kind = '10/100/1000BaseTX' if gigabit else '10/100BaseTX'
        description = next((l[12:] for l in ios_store.config(node)['interfaces'].get(port, []) if l.lower().startswith('description ')),
                           '')
        lines.append(f'{ios_short(label):<10}{description[:18]:<19}{state:<13}{vlan:<11}{duplex:>6} {speed:>6} {kind}')
    return '\n'.join(lines)


def _cisco_mac(mac):
    digits = mac.replace(':', '').lower()
    return '.'.join(digits[i:i + 4] for i in range(0, 12, 4))


def arp(console):
    """« show arp »: the router's own addresses (age -) and the neighbours its guest kernel has resolved."""
    from .pc_commands import interfaces, neighbors
    node = console.node()
    names = {p: _label(node, p) for p in node['interfaces']}
    lines = [f'{"Protocol":<10}{"Address":<17}{"Age (min)":<11}{"Hardware Addr":<16}{"Type":<7}Interface']
    rows = []
    for interface in interfaces(console.query('addresses')):
        for address in interface['addresses'] if interface['mac'] and interface['name'] in names else []:
            rows.append((address.ip, '-', interface['mac'], names[interface['name']]))
    for entry in neighbors(console.query('neighbors')):
        if entry['port'] in names:
            rows.append((ipaddress.IPv4Address(entry['address']), '0', entry['mac'], names[entry['port']]))
    lines += [f'{"Internet":<10}{str(ip):<17}{age:>8}   {_cisco_mac(mac):<16}{"ARPA":<7}{port}' for ip, age, mac, port in sorted(rows)]
    return '\n'.join(lines)


def mac_table(console):
    """« show mac address-table »: the MAC addresses the switch guest's bridge has learned, per VLAN and port."""
    from .vendor_config import ios_short
    node = console.node()
    if node['role'] != 'switch':
        return "% Invalid input detected at '^' marker."
    from .guest_startup import vlan_plan
    plan = vlan_plan(node)  # None: a plain bridge, every port in VLAN 1
    members = None if plan is None else {(port, vid) for port, vid, _ in plan}
    rows = set()  # once each; entries learned before VLAN filtering (vid 0) or before a port changed VLAN are stale
    for line in console.query('bridge-fdb').splitlines():
        port, mac, vlan = line.split()
        vid = 1 if members is None else int(vlan)
        if port in node['interfaces'] and (members is None or (port, vid) in members):
            rows.add((vid, _cisco_mac(mac), ios_short(_label(node, port))))
    lines = ['          Mac Address Table', '-' * 43, '', f'{"Vlan":<8}{"Mac Address":<18}{"Type":<12}Ports',
             f'{"----":<8}{"-----------":<18}{"--------":<12}-----', '']
    lines += [f'{vlan:>4}    {mac:<18}{"DYNAMIC":<12}{port}' for vlan, mac, port in sorted(rows)]
    lines.append(f'Total Mac Addresses for this criterion: {len(rows)}')
    return '\n'.join(lines)


def spanning_tree(console, vlan=None):
    """« show spanning-tree [vlan N] »: the 802.1D tree of the switch guest's bridge (one tree for every VLAN, shown
    as VLAN0001), read from the running bridge, or computed from the cables while the lab is stopped."""
    from . import guest_stp
    from .guest_startup import parse_stp
    node = console.node()
    if node['role'] != 'switch':
        return "% Invalid input detected at '^' marker."
    if (node.get('spanning_tree') or {}).get('mode') != 'stp':
        return 'No spanning tree instance exists.'
    if vlan not in (None, 1):
        return (f'Spanning tree instance(s) for vlan {vlan} does not exist.\n'
                '% Network LABS : ce switch fait tourner un seul arbre 802.1D pour tous ses VLAN (show spanning-tree vlan 1).')
    listing, spec = parse_stp(console.query('bridge-stp-show')), console.spec_now()
    cabled = {end[1] for link in spec['links'] for end in link if end[0] == node['name']}
    view = guest_stp.from_guest(listing, node, cabled) if listing.get('bridge') else guest_stp.from_model(spec, node['name'])
    return guest_stp.render(node, view)


def routes_of(console, codes):
    """« show ip route static » (connected, rip, ospf, bgp): the full table's header and its routes of those codes."""
    text = vendor_show.show(console.node(), console.observe(), 'show ip route')
    head, _, body = text.partition('\n\n')
    gateway, _, routes = body.partition('\n\n')
    kept = [line for line in routes.splitlines() if line[:1] in codes]
    return '\n'.join([head, '', gateway, ''] + kept)


def bindings(console):
    """« show ip dhcp binding »: the leases the router's DHCP server has given (read in the guest when it runs)."""
    node = console.node()
    port = (node.get('dhcp_server') or {}).get('interface')
    lines = ['Bindings from all pools not associated with VRF:',
             f'{"IP address":<16}{"Client-ID/":<24}{"Lease expiration":<24}{"Type":<11}{"State":<11}Interface',
             f'{"":<16}Hardware address/', f'{"":<16}User name']
    for lease in console.dhcp_bindings():
        digits = '01' + lease['mac'].replace(':', '') if lease['mac'] else ''
        client = '.'.join(digits[i:i + 4] for i in range(0, len(digits), 4)) or '(projet)'
        lines.append(f'{lease["address"]:<16}{client:<24}{"--":<24}{"Automatic":<11}{"Active":<11}{_label(node, port) if port else ""}')
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
    from .eigrp import process as eigrp_process
    eigrp = eigrp_process(node)
    if eigrp:
        lines += ['', f'Routing Protocol is "eigrp {eigrp["asn"]}"', '  EIGRP-IPv4 Protocol for AS({})'.format(eigrp['asn']),
                  f'    Router-ID: {eigrp["router_id"]}', '  Routing for Networks:']
        lines += [f'    {ipaddress.IPv4Network(n).network_address} {ipaddress.IPv4Network(n).hostmask}' for n in eigrp['networks']]
        if eigrp['passive']:
            lines += ['  Passive Interface(s):'] + [f'    {_label(node, p)}' for p in eigrp['passive']]
        lines.append('  Distance: internal 90 external 170')
    return '\n'.join(lines)


def eigrp_neighbors(console):
    """« show ip eigrp neighbors »: the adjacencies FRR's eigrpd reports in the guest (the model's on a stopped lab)."""
    from .vendor_config import ios_short
    node = console.node()
    eigrp = console.observe().get('eigrp')
    if not eigrp:
        return ''
    lines = [f'EIGRP-IPv4 Neighbors for AS({eigrp["asn"]})',
             'H   Address                 Interface              Hold Uptime   SRTT   RTO  Q  Seq',
             '                                                   (sec)         (ms)       Cnt Num']
    for index, n in enumerate(eigrp['neighbors']):
        uptime = int(n['uptime']) if n['uptime'].isdigit() else 0
        clock = f'{uptime // 3600:02d}:{uptime // 60 % 60:02d}:{uptime % 60:02d}'
        lines.append(f'{index:<4}{n["address"]:<24}{ios_short(_label(node, n["port"])):<23}{n["hold"]:>4} {clock:<9}'
                     f'{n["srtt"]:>4} {n["rto"]:>5}  {n["queue"]:<3}{n["seq"]}')
    return '\n'.join(lines)


def save(console, copy=False):
    from .vendor_config import render
    text = render(console.spec_now(), console.name)
    body = '\n'.join(l for l in text.splitlines() if not l.startswith(('! Network LABS', '! le nœud')))
    console.store_startup(body)
    return ('Destination filename [startup-config]? \n' if copy else '') + 'Building configuration...\n[OK]'


def nat(console, statistics=False):
    """« show ip nat translations / statistics »: static entries, then the guest kernel's translated connections."""
    from . import ios_nat
    from .vendor_config import port_names
    node = console.node()
    active = ios_nat.entries(node)
    statics = [ios_nat.STATIC.fullmatch(l) for l in ios_nat._global(node) if ios_nat.STATIC.fullmatch(l)] if active else []
    rows = []
    for s in console.observe().get('sessions') or []:
        port = f':{s["port"]}' if s.get('port') else ''
        if s.get('reply_destination') and s['reply_destination'] != s['source']:  # leaving: its source translated
            rows.append((s['protocol'], s['reply_destination'], s['source'], s['destination'], port))
        elif s.get('reply_source') and s['reply_source'] != s['destination']:  # arriving: a static entry's destination
            rows.append((s['protocol'], s['destination'], s['reply_source'], s['source'], port))
    if statistics:
        names = port_names(node)
        lines = [f'Total active translations: {len(statics) + len(rows)} ({len(statics)} static, {len(rows)} dynamic; '
                 f'{len(rows)} extended)']
        for side in ('outside', 'inside'):
            lines += [f'{side.capitalize()} interfaces:'] + [f'  {ios_name(names[p])}' for p in sorted(ios_nat._marked(node, side))]
        lines += ['Hits: 0  Misses: 0', 'Dynamic mappings:', '-- Inside Source']
        mappings = [ios_nat.SOURCE.fullmatch(l) for l in ios_nat._global(node) if ios_nat.SOURCE.fullmatch(l)] if active else []
        ranges = ios_nat.pools(node)
        for number, match in enumerate(mappings, 1):
            pool = match[2].lower() == 'pool'
            target = f'pool {match[3]}' if pool else f'interface {ios_name(names.get(_port_or(node, match[3]), match[3]))}'
            lines.append(f'[Id: {number}] access-list {match[1]} {target}{" overload" if match[4] else ""} refcount {len(rows)}')
            if pool and match[3] in ranges:
                first, last = ranges[match[3]]
                lines += [f' pool {match[3]}: id {number}', f'\tstart {first} end {last}',
                          f'\ttype generic, total addresses {int(last) - int(first) + 1}']
        return '\n'.join(lines)
    lines = [f'{"Pro":<5}{"Inside global":<23}{"Inside local":<23}{"Outside local":<23}Outside global']
    lines += [f'{"---":<5}{m[2]:<23}{m[1]:<23}{"---":<23}---' for m in statics]
    lines += [f'{p:<5}{g + port:<23}{l + port:<23}{o + port:<23}{o + port}' for p, g, l, o, port in rows]
    return '\n'.join(lines)


def _port_or(node, name):
    from .vendor_config import _port
    try:
        return _port(node, name)
    except ValueError:
        return name
