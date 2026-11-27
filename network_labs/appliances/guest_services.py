"""Server services on micro-VMs, as Packet Tracer's Server offers them and as IOS has them.

A server (a host micro-VM) gets node['services']:

    {'dns': {'on': bool, 'records': [[NAME, 'A', A.B.C.D] | [ALIAS, 'CNAME', NAME], ...]},
     'http': {'on': bool, 'pages': {'index.html': TEXT, ...}},
     'ntp': {'on': bool}, 'syslog': {'on': bool}, 'tftp': {'on': bool, 'files': {NAME: TEXT, ...}}}

and a PC's or server's DNS server is node['resolvers'] (or the DHCP pool's DNS server when its port takes a lease).
A router or a switch takes IOS lines instead: « ip dns server » with its « ip host NAME A.B.C.D » table, « ntp master
[STRATUM] », « ntp server A.B.C.D » (the router keeps the association), « logging host A.B.C.D » with « logging trap
LEVEL » (its log messages leave as syslog datagrams), « ip name-server A.B.C.D » (and « no ip domain-lookup »), « ip http
server ».

In the guest everything is real: the agent's --services daemon answers DNS queries (A, CNAME, and PTR from the A
records), NTP requests, collects syslog datagrams and keeps an NTP association; BusyBox httpd serves the pages. A stopped
lab answers from the project through the network model (the query's path and firewalls checked as UDP 53 / TCP 80).
"""
import ipaddress
import re

FIELDS = ('dns', 'http', 'ntp', 'syslog', 'tftp')
FILES = 16
FILE_SIZE = 65536
FILE = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}')
RECORDS = 64
PAGES = 8
PAGE_SIZE = 16384
NAME = re.compile(r'[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?(?:\.[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?)*')
PAGE = re.compile(r'[a-z0-9_-]{1,35}\.(?:html|htm|txt|css)')
SEVERITIES = ('emergencies', 'alerts', 'critical', 'errors', 'warnings', 'notifications', 'informational', 'debugging')
DEFAULT_PAGE = ('<html>\n<head><title>Network LABS</title></head>\n<body>\n<h1>Network LABS</h1>\n'
                '<p>This page is served by {name}, a server of the laboratory (HTTP service).</p>\n'
                '<p><a href="hello.html">A second page</a></p>\n</body>\n</html>\n')
HELLO_PAGE = '<html>\n<body>\n<h1>Hello, World!</h1>\n<p><a href="index.html">Back</a></p>\n</body>\n</html>\n'


def default_services(name):
    """A new server's services, as Packet Tracer's Server starts: HTTP on with two pages, the others off."""
    return {'dns': {'on': False, 'records': []}, 'http': {'on': True, 'pages': {'index.html': DEFAULT_PAGE.format(name=name),
                                                                                  'hello.html': HELLO_PAGE}},
            'ntp': {'on': False}, 'syslog': {'on': False}, 'tftp': {'on': False, 'files': {}}}


def _name(value, what):
    if not isinstance(value, str) or len(value) > 90 or not NAME.fullmatch(value):
        raise ValueError(f'{what} : un nom DNS (lettres, chiffres, tirets, points), 90 caractères au plus.')
    return value.lower()


def validate(node):
    services = node.get('services')
    if services is None:
        return
    if node.get('runtime') != 'firecracker' or node.get('role') != 'host':
        raise ValueError('Services (DNS, HTTP, NTP, Syslog) : un serveur micro-VM (rôle poste/serveur).')
    if not isinstance(services, dict) or set(services) - set(FIELDS):
        raise ValueError('Services : dns, http, ntp, syslog.')
    for key in FIELDS:
        entry = services.setdefault(key, {'on': False})
        if not isinstance(entry, dict) or not isinstance(entry.get('on'), bool):
            raise ValueError(f'Service {key} : « on » vrai ou faux.')
    dns = services['dns']
    if set(dns) - {'on', 'records'}:
        raise ValueError('Service DNS : on, records.')
    records = dns.setdefault('records', [])
    if not isinstance(records, list) or len(records) > RECORDS:
        raise ValueError(f'Service DNS : {RECORDS} enregistrements au plus.')
    clean = []
    for record in records:
        if not isinstance(record, list) or len(record) != 3 or record[1] not in ('A', 'CNAME'):
            raise ValueError('Enregistrement DNS : [nom, A ou CNAME, valeur].')
        name = _name(record[0], 'Nom')
        if record[1] == 'A':
            try:
                value = str(ipaddress.IPv4Address(record[2]))
            except (ipaddress.AddressValueError, ValueError):
                raise ValueError(f'Enregistrement A de {name} : une adresse IPv4.') from None
        else:
            value = _name(record[2], 'Nom canonique')
            if value == name:
                raise ValueError(f'CNAME de {name} : un autre nom.')
        clean.append([name, record[1], value])
    names = [r[0] for r in clean]
    for name, kind, _ in clean:
        if kind == 'CNAME' and names.count(name) > 1:
            raise ValueError(f'{name} : un alias (CNAME) ne porte pas d’autre enregistrement.')
    if len({tuple(r) for r in clean}) != len(clean):
        raise ValueError('Enregistrement DNS en double.')
    dns['records'] = clean
    http = services['http']
    if set(http) - {'on', 'pages'}:
        raise ValueError('Service HTTP : on, pages.')
    pages = http.setdefault('pages', {})
    if not isinstance(pages, dict) or len(pages) > PAGES:
        raise ValueError(f'Service HTTP : {PAGES} pages au plus.')
    for page, text in pages.items():
        if not isinstance(page, str) or not PAGE.fullmatch(page):
            raise ValueError(f'Page {page} : nom.html (lettres minuscules, chiffres, - et _), .htm, .txt ou .css.')
        if not isinstance(text, str) or len(text.encode()) > PAGE_SIZE:
            raise ValueError(f'Page {page} : un texte de {PAGE_SIZE // 1024} Kio au plus.')
    for key in ('ntp', 'syslog'):
        if set(services[key]) - {'on'}:
            raise ValueError(f'Service {key} : on.')
    tftp = services['tftp']
    if set(tftp) - {'on', 'files'}:
        raise ValueError('Service TFTP : on, files.')
    files = tftp.setdefault('files', {})
    if not isinstance(files, dict) or len(files) > FILES:
        raise ValueError(f'Service TFTP : {FILES} fichiers au plus.')
    for name, text in files.items():
        if not isinstance(name, str) or not FILE.fullmatch(name):
            raise ValueError(f'Fichier TFTP {name} : lettres, chiffres, point, tiret (64 caractères).')
        if not isinstance(text, str) or len(text.encode()) > FILE_SIZE:
            raise ValueError(f'Fichier TFTP {name} : un texte de {FILE_SIZE // 1024} Kio au plus.')


# ---- IOS lines (routers and switches) ----

def _global(node):
    from . import ios_store
    if not node.get('cli_config'):
        return []
    return [' '.join(line.split()) for line in ios_store.config(node)['global']]


def ios_hosts(node):
    """{name: [address, ...]} of « ip host NAME A.B.C.D [A.B.C.D ...] » lines, as « show hosts » lists them."""
    table = {}
    for line in _global(node):
        words = line.split()
        if len(words) >= 4 and [w.lower() for w in words[:2]] == ['ip', 'host'] and NAME.fullmatch(words[2]):
            addresses = [w for w in words[3:] if re.fullmatch(r'\d+\.\d+\.\d+\.\d+', w)]
            if addresses:
                table[words[2].lower()] = addresses[:8]
    return table


def ios_value(node, *prefix):
    """The words after the first global line starting with PREFIX (lower case), or None."""
    for line in _global(node):
        words = line.lower().split()
        if words[:len(prefix)] == list(prefix):
            return words[len(prefix):]
    return None


def name_servers(node):
    """« ip name-server A.B.C.D ... » addresses ([] with « no ip domain-lookup »)."""
    if ios_value(node, 'no', 'ip', 'domain-lookup') is not None:
        return []
    found = []
    for line in _global(node):
        words = line.lower().split()
        if words[:2] == ['ip', 'name-server']:
            found += [w for w in words[2:] if re.fullmatch(r'\d+\.\d+\.\d+\.\d+', w)]
    return found[:6]


def log_hosts(node):
    """[address] of « logging host A.B.C.D » / « logging A.B.C.D » lines."""
    found = []
    for line in _global(node):
        words = line.lower().split()
        if words[:1] == ['logging'] and len(words) in (2, 3) and re.fullmatch(r'\d+\.\d+\.\d+\.\d+', words[-1]) \
                and (len(words) == 2 or words[1] == 'host'):
            found.append(words[-1])
    return found


def trap_level(node):
    """« logging trap LEVEL »: the highest severity number sent (informational, 6, by default)."""
    value = ios_value(node, 'logging', 'trap')
    if not value:
        return 6
    word = value[0]
    if word.isdigit():
        return min(7, int(word))
    return next((i for i, name in enumerate(SEVERITIES) if name.startswith(word)), 6)


def ntp_peer(node):
    value = ios_value(node, 'ntp', 'server')
    return value[0] if value else None


def ntp_master(node):
    value = ios_value(node, 'ntp', 'master')
    if value is None:
        return None
    return int(value[0]) if value and value[0].isdigit() and 1 <= int(value[0]) <= 15 else 8


# ---- what a guest runs ----

def wanted(node):
    """(the --services tokens, the web pages or None) NODE's guest should run."""
    tokens, pages = [], None
    if node.get('role') == 'host':
        services = node.get('services') or {}
        dns = services.get('dns') or {}
        if dns.get('on'):
            tokens.append('dns')
            tokens += [f"{'a' if kind == 'A' else 'cname'}:{name}={value}" for name, kind, value in dns.get('records', [])]
        if (services.get('ntp') or {}).get('on'):
            tokens.append('ntp:1')  # a server's own clock: stratum 1, reference LOCL
        if (services.get('syslog') or {}).get('on'):
            tokens.append('syslog')
        if (services.get('tftp') or {}).get('on'):
            tokens.append('tftp')
        http = services.get('http') or {}
        if http.get('on'):
            pages = dict(http.get('pages') or {}) or {'index.html': DEFAULT_PAGE.format(name=node['name'])}
        return tokens, pages
    if ios_value(node, 'ip', 'dns', 'server') is not None:
        tokens.append('dns')
        for name, addresses in sorted(ios_hosts(node).items()):
            tokens += [f'a:{name}={address}' for address in addresses]
    if ntp_master(node):
        tokens.append(f'ntp:{ntp_master(node)}')
    if ntp_peer(node):
        tokens.append(f'sync:{ntp_peer(node)}')
    if ios_value(node, 'ip', 'http', 'server') is not None:
        pages = {'index.html': f'<html><body><h1>{node["name"]}</h1><p>Cisco IOS HTTP server (Network LABS)</p></body></html>\n'}
    return tokens, pages


def _write_pages(query, socket, pages, old_pages):
    from .guest_control import PAGE_CHUNK
    for page in sorted(set(old_pages or {}) - set(pages or {})):
        query(socket, 'http-page-delete', service=[page])
    for page, text in sorted((pages or {}).items()):
        if (old_pages or {}).get(page) == text:
            continue
        data = text.encode()
        chunks = [data[i:i + PAGE_CHUNK] for i in range(0, len(data), PAGE_CHUNK)] or [b'']
        query(socket, 'http-page', service=[page, chunks[0]])
        for chunk in chunks[1:]:
            query(socket, 'http-page-add', service=[page, chunk])


def tftp_files(node):
    """{name: text} a server's TFTP service holds in the project (copied into its guest at boot)."""
    tftp = (node.get('services') or {}).get('tftp') or {} if node.get('role') == 'host' else {}
    return dict(tftp.get('files') or {}) if tftp.get('on') else {}


def put_file(query, socket, area, name, text):
    """A text into the guest's file area (« out »: to send, « tftp »: the server's), in chunks."""
    from .guest_control import PAGE_CHUNK
    query(socket, 'file-delete', service=[area, name])
    data = text.encode()
    for i in range(0, len(data), PAGE_CHUNK):
        query(socket, 'file-put', service=[area, name, data[i:i + PAGE_CHUNK]])
    if not data:
        query(socket, 'file-put', service=[area, name, b''])


def start(socket, node):
    """At boot: the services daemon and the web server NODE declares."""
    from .guest_startup import query
    for name, text in sorted(tftp_files(node).items()):
        put_file(query, socket, 'tftp', name, text)
    tokens, pages = wanted(node)
    if tokens:
        query(socket, 'services-start', service=tokens)
    if pages is not None:
        _write_pages(query, socket, pages, None)
        query(socket, 'http-start')


def change(socket, old, new):
    """A running guest from OLD's services to NEW's: only what differs."""
    from .guest_startup import query
    (old_tokens, old_pages), (tokens, pages) = wanted(old), wanted(new)
    before, after = tftp_files(old), tftp_files(new)
    for name in sorted(set(before) - set(after)):
        query(socket, 'file-delete', service=['tftp', name])
    for name, text in sorted(after.items()):
        if before.get(name) != text:
            put_file(query, socket, 'tftp', name, text)
    if tokens != old_tokens:
        query(socket, 'services-start', service=tokens) if tokens else query(socket, 'services-stop')
    if pages != old_pages:
        if pages is None:
            query(socket, 'http-stop')
        else:
            _write_pages(query, socket, pages, old_pages)
            if old_pages is None:
                query(socket, 'http-start')


def parse_state(text):
    """SERVICES_SHOW as {'dns': {...}, 'ntp': {...}, 'syslog': {...}, 'sync': {...}, 'http': bool}."""
    state = {'http': False}
    for line in text.splitlines():
        words = line.split()
        if not words:
            continue
        if words[0] == 'http':
            state['http'] = True
            continue
        values = {'on': words[1]} if words[0] != 'sync' else {'server': words[1]}
        for key, value in zip(words[2::2], words[3::2]):
            values[key] = value
        state[words[0]] = values
    return state


def parse_syslog(text):
    """SYSLOG_READ lines as [{'time', 'source', 'message'}], oldest first."""
    rows = []
    for line in text.splitlines():
        parts = line.split(' ', 2)
        if len(parts) == 3 and parts[0].isdigit():
            rows.append({'time': int(parts[0]), 'source': parts[1], 'message': parts[2]})
    return rows


# ---- clients ----

def resolver(spec, node):
    """The DNS server NODE asks: a router's « ip name-server », a host's DHCP lease (its pool's DNS server) or its
    declared resolver; None without one."""
    if node.get('role') != 'host':
        servers = name_servers(node)
        return servers[0] if servers else None
    if node.get('dhcp_clients'):  # the pool that gives this host its lease brings its DNS server
        from .network_model import Model
        model = Model(spec)
        for port in node['dhcp_clients']:
            lease = model.leases.get((node['name'], port))
            from .dhcp import pools, with_pool
            for server in spec['nodes']:
                for pool in pools(server):
                    if lease and pool.get('dns') and lease[0].ip in _pool_network(with_pool(server, pool)):
                        return pool['dns'][0]
    resolvers = node.get('resolvers') or []
    return resolvers[0] if resolvers else None


def _pool_network(server):
    from .dhcp import pool_network
    return pool_network(server)


def records_of(node):
    """{name: ('A', [addresses]) | ('CNAME', target)} a DNS server node answers for, or None when it serves no DNS."""
    if node.get('role') == 'host':
        dns = (node.get('services') or {}).get('dns') or {}
        if not dns.get('on'):
            return None
        table = {}
        for name, kind, value in dns.get('records', []):
            if kind == 'CNAME':
                table[name] = ('CNAME', value)
            else:
                table.setdefault(name, ('A', []))[1].append(value)
        return table
    if ios_value(node, 'ip', 'dns', 'server') is None:
        return None
    return {name: ('A', addresses) for name, addresses in ios_hosts(node).items()}


def answer(table, name):
    """What a DNS server holding TABLE answers for NAME: ([('CNAME', target), ('A', address), ...], None) or ([], 'NXDOMAIN')."""
    name = name.lower().rstrip('.')
    if re.fullmatch(r'\d+\.\d+\.\d+\.\d+', name):
        found = [('PTR', host) for host, (kind, value) in sorted(table.items()) if kind == 'A' and name in value]
        return (found, None) if found else ([], 'NXDOMAIN')
    if name not in table:
        return [], 'NXDOMAIN'
    kind, value = table[name]
    if kind == 'CNAME':
        rows = [('CNAME', value)]
        if value in table and table[value][0] == 'A':
            rows += [('A', address) for address in table[value][1]]
        return rows, None
    return [('A', address) for address in value], None


def server_node(spec, address):
    """The node holding ADDRESS on one of its ports, or None."""
    for node in spec['nodes']:
        for value in (node.get('interfaces') or {}).values():
            if value and str(ipaddress.IPv4Interface(value).ip) == address:
                return node
        for sub in (node.get('subinterfaces') or {}).values():
            if sub.get('address') and str(ipaddress.IPv4Interface(sub['address']).ip) == address:
                return node
        for svi in (node.get('svis') or {}).values():
            if svi.get('address') and str(ipaddress.IPv4Interface(svi['address']).ip) == address:
                return node
    return None


def model_resolve(spec, source, server, name):
    """A DNS query from SOURCE to SERVER in the project (the lab stopped): (rows, error) as the agent's RESOLVE gives."""
    from .network_model import Model
    ok, _ = Model(spec).ping(source, server, protocol='udp', dport=53)
    target = server_node(spec, server)
    table = records_of(target) if target else None
    if not ok or table is None:
        return [], 'timeout'
    return answer(table, name)


def model_http(spec, source, server, port, path):
    """An HTTP GET in the project: (status, body) or (None, error)."""
    from .network_model import Model
    target = server_node(spec, server)
    pages = wanted(target)[1] if target else None
    ok, _ = Model(spec).ping(source, server, protocol='tcp', dport=port)
    if not ok:
        return None, 'timeout'
    if pages is None or port != 80:
        return None, 'connection refused'
    page = path.strip('/') or 'index.html'
    if page in pages:
        return 200, pages[page]
    return 404, ('<HTML><HEAD><TITLE>404 Not Found</TITLE></HEAD>\n<BODY><H1>404 Not Found</H1>\n'
                 'The requested URL was not found\n</BODY></HTML>\n')


def syslog_message(hostname, sequence, text, when):
    """IOS's syslog datagram: <PRI>SEQ: *Mmm dd hh:mm:ss.mmm: %FAC-SEV-MNEMONIC: text (facility local7)."""
    match = re.match(r'%[A-Z0-9_]+-(\d)-', text)
    severity = int(match[1]) if match else 6
    stamp = when.strftime('%b %d %H:%M:%S.') + f'{when.microsecond // 1000:03d}'
    return severity, f'<{23 * 8 + severity}>{sequence}: *{stamp}: {text}'
