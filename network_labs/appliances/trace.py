"""traceroute / tracert from a node's terminal, as each device prints it.

A running micro-VM answers hop by hop: the guest agent sends one UDP probe at a given TTL (BusyBox traceroute, 1 s
wait) and the routers on the way reply with ICMP time exceeded, the destination with port unreachable, a router
without a route with net unreachable (!N). walk() asks three probes per hop, as IOS and Windows do, and one only when
the first stays silent. A stopped lab answers from the network model (the path a probe would take, each router's
address on the port it arrives by). Unlike a real IOS, which goes on to 30 hops until Ctrl+Shift+6, the trace stops
after a few silent hops in a row: the terminal waits for the whole answer.
"""
import ipaddress
import re

MAX_HOPS = 15
SILENT_STOP = 3
_IOS = r'tr(?:a(?:c(?:e(?:r(?:o(?:u(?:t(?:e)?)?)?)?)?)?)?)?'  # tr … traceroute, as IOS abbreviates it
SYNTAX = {'ios': rf'{_IOS}(?: ip)? (\S+)', 'eos': r'traceroute (\S+)', 'vrp': r'tracert (\S+)'}


def probe(code, output):
    """One BusyBox traceroute probe: {'address', 'time_ms', 'flag'}; address None for « * »."""
    match = re.search(r'^\s*\d+\s+(\d+\.\d+\.\d+\.\d+)\s+([\d.]+) ms(?:\s+(![A-Z]?))?', output, re.M)
    if match:
        return {'address': match[1], 'time_ms': float(match[2]), 'flag': match[3]}
    unreachable = code != 0 and 'unreachable' in output.lower()  # no route on the node itself
    return {'address': None, 'time_ms': None, 'flag': '!N' if unreachable else None}


def walk(send, destination, max_hops=MAX_HOPS):
    """{'destination', 'hops': [{'ttl', 'probes'}], 'reached'}: SEND(ttl) gives one probe's outcome."""
    hops, silent = [], 0
    for ttl in range(1, max_hops + 1):
        probes = [send(ttl)]
        answered = probes[0]['address'] is not None or probes[0]['flag']
        probes += [send(ttl) for _ in range(2)] if answered else [dict(probes[0]), dict(probes[0])]
        hops.append({'ttl': ttl, 'probes': probes})
        address = next((p['address'] for p in probes if p['address']), None)
        flag = next((p['flag'] for p in probes if p['flag']), None)
        if address == destination or flag:
            return {'destination': destination, 'hops': hops, 'reached': address == destination and not flag}
        silent = silent + 1 if address is None else 0
        if silent >= SILENT_STOP:
            break
    return {'destination': destination, 'hops': hops, 'reached': False}


def from_model(model, source, destination):
    """The same result from the network model, for a stopped lab."""
    found = model.trace(source, destination)
    hops = []
    for ttl, address in enumerate(found['hops'], 1):
        hops.append({'ttl': ttl, 'probes': [{'address': address, 'time_ms': 1.0 if address else None, 'flag': None}] * 3})
    if not found['reached']:  # silent hops until SILENT_STOP in a row, as walk() stops
        trailing = 0
        for address in reversed(found['hops']):
            if address:
                break
            trailing += 1
        for ttl in range(len(hops) + 1, min(MAX_HOPS, len(hops) + SILENT_STOP - trailing) + 1):
            hops.append({'ttl': ttl, 'probes': [{'address': None, 'time_ms': None, 'flag': None}] * 3})
    return {'destination': str(destination), 'hops': hops, 'reached': found['reached'], 'why': found['why']}


def parse(syntax, command):
    """(True, address or None) for a traceroute line of SYNTAX ('host' for a PC), (False, None) otherwise."""
    line = ' '.join(command.split())
    pattern = r'(?:traceroute|tracert)(?: -n)? (\S+)' if syntax == 'host' else SYNTAX.get(syntax)
    match = re.fullmatch(pattern, line, re.IGNORECASE) if pattern else None
    if not match:
        return False, None
    try:
        return True, str(ipaddress.IPv4Address(match[1]))
    except ValueError:
        return True, None


def _first(hop):
    return next((p['address'] for p in hop['probes'] if p['address']), None)


def ios_text(result):
    lines = ['Type escape sequence to abort.', f'Tracing the route to {result["destination"]}', 'VRF info: (vrf in name/id, vrf out name/id)']
    for hop in result['hops']:
        address = _first(hop)
        if address is None and not any(p['flag'] for p in hop['probes']):
            lines.append(f'{hop["ttl"]:>3}  *  *  *')
            continue
        parts = []
        for p in hop['probes']:
            if p['flag']:
                parts.append({'!X': '!A'}.get(p['flag'], p['flag']) + ' ')
            elif p['address'] is None:
                parts.append('* ')
            else:
                parts.append(f'{round(p["time_ms"])} msec')
        lines.append(f'{hop["ttl"]:>3} {address or "*"} ' + ' '.join(parts).rstrip())
    return '\n'.join(lines)


def vrp_text(result):
    lines = [f' traceroute to {result["destination"]}({result["destination"]}), max hops: {MAX_HOPS} ,packet length: 40,'
             'press CTRL_C to break']
    for hop in result['hops']:
        address = _first(hop)
        if address is None:
            lines.append(f' {hop["ttl"]} * * *')
            continue
        times = ['*' if p['address'] is None else f'{max(1, round(p["time_ms"]))} ms' for p in hop['probes']]
        lines.append(f' {hop["ttl"]} {address} ' + '  '.join(times))
    return '\n'.join(lines)


def busybox_text(result):
    lines = [f'traceroute to {result["destination"]} ({result["destination"]}), {MAX_HOPS} hops max, 46 byte packets']
    for hop in result['hops']:
        address = _first(hop)
        if address is None:
            lines.append(f'{hop["ttl"]:>2}  *  *  *')
            continue
        times = ['*' if p['address'] is None else f'{p["time_ms"]:.3f} ms' + (f' {p["flag"]}' if p['flag'] else '')
                 for p in hop['probes']]
        lines.append(f'{hop["ttl"]:>2}  {address}  ' + '  '.join(times))
    return '\n'.join(lines)


def windows_text(result, french=False):
    """tracert as a Packet Tracer (Windows) PC prints it; a Windows PC of the laboratory (French Windows) in French."""
    lines = [f'Détermination de l’itinéraire vers {result["destination"]} avec un maximum de {MAX_HOPS} sauts.' if french
             else f'Tracing route to {result["destination"]} over a maximum of {MAX_HOPS} hops:', '']
    for hop in result['hops']:
        address = _first(hop)
        cells = []
        for p in hop['probes']:
            if p['address'] is None:
                cells.append(f'{"*":>5}   ')
            else:
                cells.append(f'{"<1" if p["time_ms"] < 1 else round(p["time_ms"]):>5} ms')
        lines.append(f'{hop["ttl"]:>3} ' + ' '.join(cells) + '  ' + (address or ('Délai d’attente de la demande dépassé.' if french else 'Request timed out.')))
    lines += ['', 'Itinéraire déterminé.' if french else 'Trace complete.']
    return '\n'.join(lines)


def text(syntax, result, command='', french=False):
    if syntax == 'ios':
        return ios_text(result)
    if syntax == 'vrp':
        return vrp_text(result)
    if syntax == 'host' and command.split()[0].lower() == 'tracert':
        return windows_text(result, french)
    return busybox_text(result)


def unknown(syntax):
    if syntax == 'ios':
        return '% Unrecognized host or address, or protocol not running.'
    if syntax == 'vrp':
        return 'Error: The host name or IP address is invalid.'
    return 'traceroute: bad address'
