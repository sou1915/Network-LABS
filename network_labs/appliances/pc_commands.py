"""A PC's Windows-style commands, as Packet Tracer's PCs answer them: ipconfig, ipconfig /all, arp -a.

The PC is a Linux micro-VM; these read its real state (« ip addr », « ip route », « ip neigh » through the guest agent,
or the project's model while the lab is stopped) and print it the way a Windows PC does.
"""
import ipaddress
import re



def interfaces(addresses_text):
    """[{'name', 'up', 'mac', 'addresses'}] from « ip addr » output (BusyBox or the project's model)."""
    found, current = [], None
    for line in addresses_text.splitlines():
        header = re.match(r'^\d+: ([^:@]+)(?:@[^:]+)?: <([^>]*)>', line)
        if header:
            current = {'name': header[1], 'up': 'UP' in header[2].split(','), 'mac': None, 'addresses': []}
            if current['name'] != 'lo':
                found.append(current)
            continue
        words = line.split()
        if current is None:
            continue
        if words[:1] == ['link/ether'] and len(words) > 1:
            current['mac'] = words[1]
        elif words[:1] == ['inet'] and len(words) > 1:
            current['addresses'].append(ipaddress.IPv4Interface(words[1]))
    return found


def gateway(routes_text, port):
    for line in routes_text.splitlines():
        words = line.split()
        if words[:2] == ['default', 'via'] and 'dev' in words and words[words.index('dev') + 1] == port:
            return words[2]
    return None


def _field(label, value):
    """« IPv4 Address. . . . . . . . . . . : value »: dots on fixed odd columns up to the colon, as Windows writes."""
    line = '   ' + label
    while len(line) < 36:
        line += '.' if len(line) % 2 else ' '
    return f'{line} : {value}'.rstrip()


def _windows_mac(mac):
    return mac.upper().replace(':', '-') if mac else None


def ipconfig(name, addresses_text, routes_text, dhcp_ports=(), full=False):
    lines = ['', 'Windows IP Configuration', '']
    if full:
        lines += [_field('Host Name', name), _field('Primary Dns Suffix', ''), _field('Node Type', 'Hybrid'),
                  _field('IP Routing Enabled', 'No'), '']
    for interface in interfaces(addresses_text):
        lines += ['', f'Ethernet adapter {interface["name"]}:', '']
        if not interface['up']:
            lines += [_field('Media State', 'Media disconnected'), _field('Connection-specific DNS Suffix', '')]
            continue
        lines.append(_field('Connection-specific DNS Suffix', ''))
        if full:
            lines.append(_field('Description', 'Network LABS micro-VM (virtio)'))
            if interface['mac']:
                lines.append(_field('Physical Address', _windows_mac(interface['mac'])))
            dhcp = interface['name'] in dhcp_ports
            lines += [_field('DHCP Enabled', 'Yes' if dhcp else 'No'), _field('Autoconfiguration Enabled', 'Yes')]
        address = interface['addresses'][0] if interface['addresses'] else None
        lines += [_field('IPv4 Address', (str(address.ip) if address else '0.0.0.0') + ('(Preferred)' if full and address else '')),
                  _field('Subnet Mask', str(address.netmask) if address else '0.0.0.0'),
                  _field('Default Gateway', gateway(routes_text, interface['name']) or '')]
    return '\n'.join(lines)


def neighbors(neighbors_text):
    """[{'address', 'port', 'mac', 'state'}] from « ip neigh » output; incomplete entries (no MAC) left out."""
    found = []
    for line in neighbors_text.splitlines():
        words = line.split()
        if len(words) >= 5 and 'lladdr' in words and 'dev' in words:
            found.append({'address': words[0], 'port': words[words.index('dev') + 1], 'mac': words[words.index('lladdr') + 1],
                          'state': words[-1]})
    return found


def arp(neighbors_text, addresses_text):
    entries = neighbors(neighbors_text)
    if not entries:
        return 'No ARP Entries Found.'
    lines = []
    for index, interface in enumerate(interfaces(addresses_text), 2):
        mine = [e for e in entries if e['port'] == interface['name']]
        if not mine or not interface['addresses']:
            continue
        lines += ['', f'Interface: {interface["addresses"][0].ip} --- 0x{index:x}',
                  f'  {"Internet Address":<22}{"Physical Address":<22}Type']
        lines += [f'  {e["address"]:<22}{_windows_mac(e["mac"]):<22}{"static" if e["state"] == "PERMANENT" else "dynamic"}'
                  for e in mine]
    return '\n'.join(lines) if lines else 'No ARP Entries Found.'
