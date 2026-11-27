"""The terminal commands around the server services (guest_services): what IOS and a PC's shell print for them.

IOS: ping or traceroute to a name (« ip host », then the DNS server of « ip name-server »), show hosts, show ntp status,
show ntp associations, show logging; the device's log messages (%SYS-5-CONFIG_I, %LINK-5-CHANGED…) kept in its buffer
and sent to its « logging host » collectors as syslog datagrams. A PC or a server (BusyBox shell): nslookup, ping NAME,
curl and wget -qO- toward a web server, logread for the messages a syslog server has collected.

The lab running, each one is a request to the guest (a real DNS query, a real HTTP GET…); the lab stopped, the project
answers through the network model.
"""
import datetime
import re
import time

from . import guest_services

UNKNOWN_HOST = '% Unrecognized host or address, or protocol not running.'
LOGS = {}  # (lab, node) -> [(datetime, text)]: each device's log buffer, shared by its terminal windows
LOG_KEEP = 200
SEQUENCE = {}


def _ip(text):
    return bool(re.fullmatch(r'\d+\.\d+\.\d+\.\d+', text)) and all(int(p) < 256 for p in text.split('.'))


def lookup(console, name):
    """(rows, error, server) of a DNS query for NAME from the console's device to its DNS server."""
    spec = console.spec_now()
    node = console.node(spec)
    server = guest_services.resolver(spec, node)
    if server is None:
        return [], 'no server', None
    reply = console.service('resolve', [server, name])
    if reply is None:  # the lab stopped: the project's DNS servers answer
        rows, error = guest_services.model_resolve(spec, console.name, server, name)
        return rows, error, server
    code, output = reply
    if code:
        return [], output.strip() or 'timeout', server
    rows = [tuple(line.split(None, 1)) for line in output.splitlines() if ' ' in line]
    return rows, None, server


def addresses_of(rows):
    return [value for kind, value in rows if kind == 'A']


# ---- Cisco IOS ----

def ios_resolve(console, name):
    """(address or None, the « Translating » line or None) for an IOS command naming a host."""
    node = console.node()
    table = guest_services.ios_hosts(node)
    if name.lower() in table:
        return table[name.lower()][0], None
    if not guest_services.name_servers(node):
        return None, None
    rows, error, server = lookup(console, name)
    found = addresses_of(rows)
    note = f'Translating "{name}"...domain server ({server})' + (' [OK]' if found else '')
    return (found[0] if found else None), note


def ios_ping(console, command):
    """« ping NAME » on IOS: the name translated, then the ping; None when COMMAND is not a ping to a name."""
    match = re.fullmatch(r'ping (?:ip )?([A-Za-z_][A-Za-z0-9_.-]*)', ' '.join(command.split()), re.IGNORECASE)
    if not match or match[1].lower() in ('ip',):
        return None
    address, note = ios_resolve(console, match[1])
    if address is None:
        return '\n'.join(part for part in (note, UNKNOWN_HOST) if part)
    from . import vendor_show
    text = vendor_show.ping_text(console.node(), console.ping(address))
    return '\n'.join(part for part in (note, text) if part)


def show(console, full):
    """show hosts / ntp status / ntp associations / logging, or None."""
    if full in ('show hosts', 'show host'):
        return hosts(console)
    if full in ('show ntp status', 'show ntp associations'):
        return ntp(console, associations=full.endswith('associations'))
    if full in ('show logging', 'show log'):
        return logging(console)
    return None


def hosts(console):
    node = console.node()
    servers = guest_services.name_servers(node)
    domain = guest_services.ios_value(node, 'ip', 'domain-name')
    lookup_on = guest_services.ios_value(node, 'no', 'ip', 'domain-lookup') is None
    lines = [f'Default domain is {domain[0]}' if domain else 'Default domain is not set',
             'Name/address lookup uses ' + ('domain service' if lookup_on else 'static mappings'),
             'Name servers are ' + (', '.join(servers) if servers else '255.255.255.255'), '',
             'Codes: UN - unknown, EX - expired, OK - OK, ?? - revalidate', '       temp - temporary, perm - permanent',
             '       NA - Not Applicable None - Not defined', '',
             'Host                      Port  Flags      Age Type   Address(es)']
    for name, values in sorted(guest_services.ios_hosts(node).items()):
        lines.append(f'{name:<25} None  (perm, OK)  0   IP    {" ".join(values)}')
    return '\n'.join(lines)


def ntp_state(console):
    """{'synced', 'stratum', 'reference', 'offset', 'delay', 'server', 'master'} of the device's NTP."""
    node = console.node()
    master, peer = guest_services.ntp_master(node), guest_services.ntp_peer(node)
    state = {'synced': False, 'stratum': 16, 'reference': None, 'offset': 0.0, 'delay': 0.0, 'server': peer, 'master': master}
    if peer:
        reply = console.service('services-show', [])
        if reply is None:  # the lab stopped: the model's path to the server, and its stratum
            spec = console.spec_now()
            from .network_model import Model
            target = guest_services.server_node(spec, peer)
            tokens = guest_services.wanted(target)[0] if target else []
            stratum = next((int(t.split(':')[1]) for t in tokens if t.startswith('ntp:')), None)
            if stratum and Model(spec).ping(console.name, peer, protocol='udp', dport=123)[0]:
                state.update(synced=True, stratum=min(15, stratum + 1), reference=peer)
        else:
            sync = guest_services.parse_state(reply[1]).get('sync') or {}
            if sync.get('synced') == '1':
                state.update(synced=True, stratum=min(15, int(sync.get('stratum', '15')) + 1), reference=peer,
                             offset=float(sync.get('offset', 0)), delay=float(sync.get('delay', 0)))
    if not state['synced'] and master:
        state.update(synced=True, stratum=master, reference='127.127.1.1')
    return state


def ntp(console, associations):
    state = ntp_state(console)
    now = datetime.datetime.now(datetime.timezone.utc)
    if associations:
        lines = ['  address         ref clock       st   when   poll reach  delay  offset   disp']
        if state['master']:
            lines.append(f'{"*" if state["reference"] == "127.127.1.1" else " "}~127.127.1.1     .LOCL.          {state["master"] - 1:>2}'
                         '      1     16   377  0.000   0.000   0.190')
        if state['server']:
            mark = '*' if state['reference'] == state['server'] else ' '
            st = state['stratum'] - 1 if state['reference'] == state['server'] else 16
            reach = 377 if mark == '*' else 0
            lines.append(f'{mark}~{state["server"]:<16}{".LOCL." if st != 16 else ".INIT.":<16}{st:>2}'
                         f'      {12 if mark == "*" else "-":>1}     16   {reach:>3}  {state["delay"] * 1000:.3f}   {state["offset"] * 1000:.3f}   0.020')
        lines.append(' * sys.peer, # selected, + candidate, - outlyer, x falseticker, ~ configured')
        return '\n'.join(lines)
    if not state['synced']:
        return 'Clock is unsynchronized, stratum 16, no reference clock\nnominal freq is 250.0000 Hz, actual freq is 250.0000 Hz, ' \
               'precision is 2**24\nreference time is 00000000.00000000 (00:00:00.000 UTC Mon Jan 1 1900)\n' \
               'clock offset is 0.0000 msec, root delay is 0.00 msec\nroot dispersion is 0.00 msec, peer dispersion is 0.00 msec'
    return '\n'.join([f'Clock is synchronized, stratum {state["stratum"]}, reference is {state["reference"]}',
                      'nominal freq is 250.0000 Hz, actual freq is 250.0000 Hz, precision is 2**24',
                      f'reference time is {now.strftime("%H:%M:%S.%f")[:-3]} UTC {now.strftime("%a %b %d %Y")}',
                      f'clock offset is {state["offset"] * 1000:.4f} msec, root delay is {state["delay"] * 1000:.2f} msec',
                      'root dispersion is 0.02 msec, peer dispersion is 0.02 msec'])


def clock_synced(console):
    """True when the device's clock follows NTP (« show clock » then prints no « * »)."""
    node = console.node()
    if not (guest_services.ntp_master(node) or guest_services.ntp_peer(node)):
        return False
    return ntp_state(console)['synced']


def logging(console):
    node = console.node()
    kept = LOGS.get((console.lab, console.name), [])
    level = guest_services.trap_level(node)
    targets = guest_services.log_hosts(node)
    sent = sum(1 for _, text in kept if _severity(text) <= level)
    lines = ['Syslog logging: enabled (0 messages dropped, 0 messages rate-limited, 0 flushes, 0 overruns, xml disabled, '
             'filtering disabled)', '', 'No Active Message Discriminator.', '', 'No Inactive Message Discriminator.', '',
             f'    Console logging: level debugging, {len(kept)} messages logged, xml disabled,',
             '                     filtering disabled',
             '    Monitor logging: level debugging, 0 messages logged, xml disabled,', '                     filtering disabled',
             f'    Buffer logging:  level debugging, {len(kept)} messages logged, xml disabled,',
             '                    filtering disabled', '    Exception Logging: size (4096 bytes)',
             '    Count and timestamp logging messages: disabled', '    Persistent logging: disabled', '',
             'No active filter modules.', '',
             f'    Trap logging: level {guest_services.SEVERITIES[level]}, {sent} message lines logged']
    for target in targets:
        lines += [f'        Logging to {target}  (udp port 514, audit disabled,', '              link up),',
                  f'              {sent} message lines logged,', '              0 message lines rate-limited,',
                  '              0 message lines dropped-by-MD,', '              xml disabled, sequence number disabled',
                  '              filtering disabled']
    lines += ['        Logging Source-Interface:       VRF Name:', '', 'Log Buffer (8192 bytes):', '']
    lines += [f'*{when.strftime("%b %d %H:%M:%S.")}{when.microsecond // 1000:03d}: {text}' for when, text in kept]
    return '\n'.join(lines)


def _severity(text):
    match = re.match(r'%[A-Z0-9_]+-(\d)-', text)
    return int(match[1]) if match else 6


def logged(console, reply):
    """Keep the log messages in REPLY in the device's buffer and send them to its syslog collectors (lab running)."""
    if not isinstance(reply, str) or '%' not in reply:
        return
    messages = re.findall(r'^%[A-Z0-9_]+-\d-[A-Z0-9_]+: .*$', reply, re.M)
    if not messages:
        return
    kept = LOGS.setdefault((console.lab, console.name), [])
    node = console.node()
    targets, level = guest_services.log_hosts(node), guest_services.trap_level(node)
    for text in messages:
        when = datetime.datetime.now(datetime.timezone.utc)
        kept.append((when, text))
        del kept[:-LOG_KEEP]
        if not targets or _severity(text) > level:
            continue
        key = (console.lab, console.name)
        SEQUENCE[key] = SEQUENCE.get(key, 0) + 1
        _, datagram = guest_services.syslog_message(console.hostname, SEQUENCE[key], text, when)
        for target in targets:
            try:
                console.service('syslog-send', [target, datagram])
            except (OSError, ValueError):
                pass  # UDP, as on the device: a collector out of reach loses the message


# ---- a PC's or a server's shell (BusyBox) ----

def windows(node):
    """A Windows PC or server: its shell answers ping and nslookup as Windows does (Packet Tracer's PCs too)."""
    return str(node.get('model') or '').startswith('windows')


def windows_ping(console, words):
    """ping [-n N] NAME|A.B.C.D, as Windows prints it."""
    target = words[-1]
    count = int(words[words.index('-n') + 1]) if '-n' in words[:-1] and words[words.index('-n') + 1].isdigit() else 4
    count = max(1, min(count, 8))
    address = target
    if not _ip(target):
        rows, _, _ = lookup(console, target)
        found = addresses_of(rows)
        if not found:
            return (f'La requête Ping n’a pas pu trouver l’hôte {target}. Vérifiez le nom et essayez à nouveau.')
        address = found[0]
    result = console.ping(address, count=count)
    shown = f'{target} [{address}]' if target != address else address
    lines = [f'Envoi d’une requête \'Ping\'  {shown} avec 32 octets de données :']
    times = []
    for reply in result['replies']:
        if reply['ok']:
            ms = reply.get('time_ms') or 1.0
            times.append(ms)
            lines.append(f'Réponse de {address} : octets=32 temps{"<1ms" if ms < 1 else "=" + str(round(ms)) + " ms"} TTL={reply.get("ttl") or 64}')
        else:
            lines.append('Délai d’attente de la demande dépassé.')
    sent, received = len(result['replies']), len(times)
    lines += ['', f'Statistiques Ping pour {address}:',
              f'    Paquets : envoyés = {sent}, reçus = {received}, perdus = {sent - received} (perte {round(100 * (sent - received) / max(1, sent))}%),']
    if times:
        lines += ['Durée approximative des boucles en millisecondes :',
                  f'    Minimum = {round(min(times))}ms, Maximum = {round(max(times))}ms, Moyenne = {round(sum(times) / len(times))}ms']
    return '\n'.join(lines)


def windows_nslookup(console, name, server=None):
    spec = console.spec_now()
    node = console.node(spec)
    server = server or guest_services.resolver(spec, node)
    if server is None:
        return '*** Le serveur par défaut n’est pas disponible\nServeur :  UnKnown\nAddress:  127.0.0.1'
    reply = console.service('resolve', [server, name])
    if reply is None:
        rows, error = guest_services.model_resolve(spec, console.name, server, name)
    else:
        code, output = reply
        rows = [tuple(line.split(None, 1)) for line in output.splitlines() if ' ' in line] if not code else []
        error = output.strip() if code else None
    lines = ['Serveur :   UnKnown', f'Address:  {server}', '']
    if error in ('timeout', 'unreachable', 'no server'):
        return '\n'.join(lines[:2] + ['', 'DNS request timed out.\n    timeout was 2 seconds.\n*** La demande à UnKnown a dépassé le délai d’attente'])
    if error:
        return '\n'.join(lines + [f'*** UnKnown ne parvient pas à trouver {name} : Non-existent domain'])
    names = [value for kind, value in rows if kind == 'PTR']
    if names:
        return '\n'.join(lines + [f'Nom :    {names[0]}', f'Address:  {name}'])
    canonical = next((value for kind, value in rows if kind == 'CNAME'), None)
    found = addresses_of(rows)
    lines += [f'Nom :    {canonical or name}', ('Addresses:  ' if len(found) > 1 else 'Address:  ') + '\n          '.join(found)]
    if canonical:
        lines.append(f'Aliases:  {name}')
    return '\n'.join(lines)


def host(console, command):
    """nslookup, ping NAME, curl / wget -qO-, logread; None for another command."""
    words = command.split()
    low = [w.lower() for w in words]
    if windows(console.node()):
        if low[0] == 'ping' and len(words) >= 2 and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', words[-1]):
            return windows_ping(console, low[:-1] + [words[-1]])
        if low[0] == 'nslookup' and len(words) in (2, 3):
            return windows_nslookup(console, words[1], words[2] if len(words) == 3 else None)
    if low[0] == 'nslookup' and len(words) in (2, 3):
        return nslookup(console, words[1], words[2] if len(words) == 3 else None)
    if low[0] == 'ping' and len(words) >= 2 and not _ip(words[-1]) and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', words[-1]):
        rows, error, _ = lookup(console, words[-1])
        found = addresses_of(rows)
        if not found:
            return f"ping: bad address '{words[-1]}'"
        text = console.host(' '.join(words[:-1] + [found[0]]), ' '.join(low[:-1] + [found[0]]))
        return text.replace(f'PING {found[0]} ({found[0]})', f'PING {words[-1]} ({found[0]})', 1).replace(
            f'--- {found[0]} ping statistics', f'--- {words[-1]} ping statistics', 1)
    url, headers = None, False
    if low[0] == 'curl' and len(words) == 2:
        url = words[1]
    elif low[:2] == ['curl', '-i'] and len(words) == 3:  # the response's status line and headers too (the desktop's browser)
        url, headers = words[2], True
    elif low[0] == 'wget' and len(words) == 3 and low[1] in ('-qo-', '-qo', '-o-') or low[:3] == ['wget', '-o', '-'] and len(words) == 4:
        url = words[-1]
    elif low[0] == 'wget' and len(words) == 2:
        return 'wget : la page s’affiche ici avec « wget -qO- URL » ou « curl URL » (pas de fichier enregistré dans la micro-VM).'
    if url is not None:
        return browse(console, url, curl=low[0] == 'curl', headers=headers)
    if low in (['logread'], ['cat', '/var/log/messages']):
        return logread(console)
    if low in (['ls', '/tftpboot'], ['ls', '-l', '/tftpboot']):  # a server's TFTP files
        listing = tftp_listing(console)
        if low[1] == '-l':
            return '\n'.join(f'-rw-r--r--    1 root     root     {size:>8} {name}' for name, size in sorted(listing.items()))
        return '  '.join(sorted(listing))
    if len(low) == 2 and low[0] == 'cat' and low[1].startswith('/tftpboot/'):
        name = words[1][len('/tftpboot/'):]
        reply = console.service('tftp-read', [name]) if re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}', name) else (1, '')
        if reply is None:
            files = guest_services.tftp_files(console.node())
            reply = (0, files[name]) if name in files else (1, '')
        return reply[1].rstrip('\n') if not reply[0] else f"cat: can't open '{words[1]}': No such file or directory"
    return None


def nslookup(console, name, server=None):
    spec = console.spec_now()
    node = console.node(spec)
    server = server or guest_services.resolver(spec, node)
    if server is None or not _ip(server):
        return ';; connection timed out; no servers could be reached'
    reply = console.service('resolve', [server, name])
    if reply is None:
        rows, error = guest_services.model_resolve(spec, console.name, server, name)
    else:
        code, output = reply
        rows = [tuple(line.split(None, 1)) for line in output.splitlines() if ' ' in line] if not code else []
        error = output.strip() if code else None
    lines = [f'Server:\t\t{server}', f'Address:\t{server}:53', '']
    if error in ('timeout', 'unreachable', 'no server'):
        return ';; connection timed out; no servers could be reached'
    if error:
        return '\n'.join(lines + [f"** server can't find {name}: {error}"])
    for kind, value in rows:
        if kind == 'CNAME':
            lines.append(f'{name}\tcanonical name = {value}')
        elif kind == 'PTR':
            octets = name.split('.')
            lines.append(f'{".".join(reversed(octets))}.in-addr.arpa\tname = {value}')
        else:
            lines += [f'Name:\t{name}', f'Address: {value}']
    return '\n'.join(lines)


def browse(console, url, curl, headers=False):
    """GET URL from the device: http://HOST[:PORT][/PATH], HOST a name (DNS) or an address."""
    match = re.fullmatch(r'(?:http://)?([A-Za-z0-9_.-]+)(?::(\d{1,5}))?(/[A-Za-z0-9/._-]*)?', url)
    if not match:
        return 'curl: (3) URL using bad/illegal format or missing URL' if curl else f'wget: bad address \'{url}\''
    host_name, port, path = match[1], int(match[2] or 80), match[3] or '/'
    address = host_name
    if not _ip(host_name):
        rows, _, _ = lookup(console, host_name)
        found = addresses_of(rows)
        if not found:
            return f'curl: (6) Could not resolve host: {host_name}' if curl else f"wget: bad address '{host_name}'"
        address = found[0]
    text = fetch(console, address, port, path)
    if text.startswith('!'):
        reason = text[1:]
        if curl:
            return {'connection refused': f'curl: (7) Failed to connect to {host_name} port {port}: Connection refused',
                    'timeout': f'curl: (28) Failed to connect to {host_name} port {port}: Connection timed out'}.get(
                        reason, f'curl: (7) Failed to connect to {host_name} port {port}: {reason}')
        return f'wget: can\'t connect to remote host ({address}): {"Connection refused" if "refused" in reason else "Connection timed out"}'
    if headers:
        return text
    head, _, body = text.partition('\r\n\r\n')
    status = head.splitlines()[0] if head else ''
    if not curl and ' 200 ' not in status:
        return f'wget: server returned error: {status}'
    return body.rstrip('\n')


def fetch(console, address, port, path):
    """The raw HTTP response, or '!' + the reason it failed."""
    reply = console.service('http-get', [address, port, path])
    if reply is None:
        status, body = guest_services.model_http(console.spec_now(), console.name, address, port, path)
        if status is None:
            return '!' + body
        reason = {200: 'OK', 404: 'Not Found'}[status]
        return f'HTTP/1.1 {status} {reason}\r\nContent-type: text/html\r\n\r\n{body}'
    code, output = reply
    return output if not code else '!' + output.strip()


def logread(console):
    node = console.node()
    if not ((node.get('services') or {}).get('syslog') or {}).get('on'):
        return 'logread: le service Syslog de ce serveur est arrêté (Services › SYSLOG).'
    reply = console.service('syslog-read', [])
    if reply is None:
        return '(le lab est arrêté : aucun message reçu)'
    rows = guest_services.parse_syslog(reply[1])
    return '\n'.join(f'{time.strftime("%b %d %H:%M:%S", time.gmtime(r["time"]))} {r["source"]} {r["message"]}' for r in rows) \
        or '(aucun message reçu)'


# ---- TFTP: IOS « copy … tftp: » and « copy tftp: … », with IOS's questions ----

PLACES = {'running-config': 'running', 'run': 'running', 'system:running-config': 'running', 'startup-config': 'startup',
          'start': 'startup', 'nvram:startup-config': 'startup'}


def _place(word):
    """'running', 'startup', ('tftp', host, file) or None for a copy source or destination."""
    low = word.lower()
    if low in PLACES:
        return PLACES[low]
    match = re.fullmatch(r'tftp:(?://([A-Za-z0-9_.-]+)/([A-Za-z0-9._-]+))?', word, re.IGNORECASE) or re.fullmatch(r'tftp', low)
    if match:
        return ('tftp', match[1] if match.re.groups else None, match[2] if match.re.groups else None)
    return None


def ios_copy(console, command):
    """« copy running-config tftp: » and the others through TFTP: their questions start (console.dialog), or None."""
    words = command.split()
    if len(words) != 3 or words[0].lower() != 'copy':
        return None
    source, target = _place(words[1]), _place(words[2])
    if source is None or target is None or (not isinstance(source, tuple) and not isinstance(target, tuple)):
        return None
    if isinstance(source, tuple) and isinstance(target, tuple):
        return "%Error: copy from tftp: to tftp: is not supported"
    remote = source if isinstance(source, tuple) else target
    console.dialog = {'source': source, 'target': target, 'host': remote[1], 'file': remote[2], 'steps': []}
    if not remote[1]:
        console.dialog['steps'].append(('host', 'Address or name of remote host []? '))
    if isinstance(source, tuple):
        if not remote[2]:
            console.dialog['steps'].append(('file', 'Source filename []? '))
        console.dialog['steps'].append(('destination', f'Destination filename [{target}-config]? '))
    elif not remote[2]:
        console.dialog['steps'].append(('file', f'Destination filename [{console.hostname.lower()}-confg]? '))
    if not console.dialog['steps']:
        return finish(console)
    return ''


def dialog_answer(console, text):
    """One answer to the copy's current question; the transfer once the last one is given."""
    dialog = console.dialog
    key, _ = dialog['steps'].pop(0)
    value = text.strip()
    if key == 'host':
        dialog['host'] = value
    elif key == 'file':
        dialog['file'] = value or (f'{console.hostname.lower()}-confg' if not isinstance(dialog['source'], tuple) else '')
    if dialog['steps']:
        return ''
    return finish(console)


def finish(console):
    dialog, console.dialog = console.dialog, None
    host, name = dialog['host'], dialog['file']
    url = f'tftp://{host}/{name}'
    if not host or not name or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}', name):
        return '%Error parsing filename (Invalid argument)'
    address = host if _ip(host) else ios_resolve(console, host)[0]
    if address is None:
        return f'%Error opening {url} (Unknown host)'
    started = time.monotonic()
    if isinstance(dialog['target'], tuple):  # this device's configuration to the server
        text = _configuration(console, dialog['source'])
        if text is None:
            return '%Error opening nvram:startup-config (No such file or directory)'
        error = _tftp_put(console, address, name, text)
        if error:
            return f'%Error opening {url} ({error})'
        took = max(time.monotonic() - started, 0.001)
        return f'!!\n{len(text.encode())} bytes copied in {took:.3f} secs ({int(len(text.encode()) / took)} bytes/sec)'
    text, error = _tftp_get(console, address, name)
    if error:
        return f'Accessing {url}...\n%Error opening {url} ({error})'
    took = max(time.monotonic() - started, 0.001)
    size = len(text.encode())
    shown = [f'Accessing {url}...', f'Loading {name} from {address}: !', f'[OK - {size} bytes]', '',
             f'{size} bytes copied in {took:.3f} secs ({int(size / took)} bytes/sec)']
    if dialog['target'] == 'startup':
        console.store_startup(text)
        return '\n'.join(shown)
    applied = merge(console, text)  # copy tftp: running-config merges the lines, as IOS does
    return '\n'.join(shown + ([applied] if applied else []) + [f'%SYS-5-CONFIG_I: Configured from {url} by console'])


def _configuration(console, place):
    from . import ios_store
    if place == 'startup':
        return ios_store.config(console.node()).get('startup')
    text = console.ios_running()
    return text.split('\n!\n', 1)[-1] if text.startswith('Building configuration') else text


def _tftp_put(console, address, name, text):
    """None once the server has the file, else IOS's reason (Timed out, Permission denied…)."""
    data = text.encode()
    if console.service('tftp-files', []) is None:  # the lab stopped: the server's file in the project
        return _model_put(console, address, name, text)
    try:
        console.service('file-delete', ['out', name])
        from .guest_control import PAGE_CHUNK
        for i in range(0, len(data), PAGE_CHUNK):
            code, output = console.service('file-put', ['out', name, data[i:i + PAGE_CHUNK]])
            if code:
                return output.strip() or 'Error'
        code, output = console.service('tftp-put', [address, name])
    except (OSError, ValueError) as error:
        return str(error)
    return None if not code else ('Timed out' if 'Timed out' in output else output.strip() or 'Error')


def _tftp_get(console, address, name):
    reply = console.service('tftp-get', [address, name])
    if reply is None:
        return _model_get(console, address, name)
    code, output = reply
    return (output, None) if not code else ('', 'Timed out' if 'Timed out' in output else output.strip() or 'Error')


def _model_server(console, address, port=69):
    from .network_model import Model
    spec = console.spec_now()
    target = guest_services.server_node(spec, address)
    serving = target is not None and 'tftp' in guest_services.wanted(target)[0]
    ok = Model(spec).ping(console.name, address, protocol='udp', dport=port)[0]
    return (target if serving else None), ok


def _model_put(console, address, name, text):
    import copy
    target, ok = _model_server(console, address)
    if not ok or target is None:
        return 'Timed out'
    with console.manager().locked() as manager:
        spec = manager.read()['spec']
        server = copy.deepcopy(next(n for n in spec['nodes'] if n['name'] == target['name']))
        files = server['services']['tftp'].setdefault('files', {})
        if name not in files and len(files) >= guest_services.FILES:
            return 'Disk full or allocation exceeded'
        files[name] = text
        manager.configure_routing(server['name'], server)
    return None


def _model_get(console, address, name):
    target, ok = _model_server(console, address)
    if not ok or target is None:
        return '', 'Timed out'
    files = guest_services.tftp_files(target)
    return (files[name], None) if name in files else ('', 'No such file or directory')


def merge(console, text):
    """A configuration file's lines typed into configuration mode (comments, « end », banners of the file skipped)."""
    skip = re.compile(r'(!.*|end|version .*|building configuration.*|current configuration.*|no service timestamps .*)', re.IGNORECASE)
    lines = [l.rstrip() for l in text.splitlines() if l.strip() and not skip.fullmatch(l.strip())]
    mode = console.mode
    console.mode, console.pending, console.context = 'config', [], None
    with console.manager().locked() as manager:
        console.base = manager.read()['spec']
    errors = []
    for line in lines:
        reply = console.ios_line(line)
        if reply.startswith('%') and 'Invalid' in reply:
            errors.append(f'{line}\n{reply}')
    reply = console.ios_apply(final=True)
    console.mode, console.context, console.pending, console.base = mode if mode != 'config' else 'enable', None, [], None
    return '\n'.join(errors + ([reply] if reply and reply != 'Aucun changement.' else []))


# ---- a server's TFTP files from its shell: ls /tftpboot, cat /tftpboot/NAME ----

def tftp_listing(console):
    reply = console.service('tftp-files', [])
    if reply is None:
        files = guest_services.tftp_files(console.node())
        return {name: len(text.encode()) for name, text in files.items()}
    return {line.split()[0]: int(line.split()[1]) for line in reply[1].splitlines() if len(line.split()) == 2}
