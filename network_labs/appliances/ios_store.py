"""The Cisco IOS commands of the CCNA and Packet Tracer that the lab keeps in a device's configuration.

The structured model (addresses, routes, OSPF, BGP, ACLs, VLANs, DHCP, shutdown) is what the micro-VMs run. Around it a
real IOS configuration holds much more: hostname, banner, passwords, users, SSH, console and vty lines, CDP, NTP,
logging, SNMP, NAT, RIP, EIGRP, port security, spanning tree… Those lines are accepted here as IOS accepts them, kept in
node['cli_config'] and shown by « show running-config » where IOS puts them. Some act on the lab: hostname (the prompt),
banner motd, enable secret and password, line con 0 password and login (the console asks), service
password-encryption (type 7). The others are configuration only for now: GRAMMAR marks each one, and the command
catalogue says so.

node['cli_config'] = {'hostname': str | None, 'global': [line], 'interfaces': {port: [line]},
                      'blocks': [{'header': line, 'lines': [line]}], 'startup': text | None}
"""
import base64
import hashlib
import re

LIMIT_LINES = 400
LIMIT_TEXT = 200
EFFECT, STORED = 'effet', 'enregistré'
IP = r'\d+\.\d+\.\d+\.\d+'

# (mode, catalogue syntax, regex on the lower-cased line, words making its identity, help, example, effect, roles)
GRAMMAR = [
    ('config', 'hostname NOM', r'hostname (\S+)', 1, 'Nom de l’équipement (l’invite change).', ['hostname R-CENTRE'], EFFECT, 'RSF'),
    ('config', 'banner motd #TEXTE#', r'banner motd (\^c|.).+\1', 2, 'Message affiché à l’ouverture de la console.',
     ['banner motd #Acces reserve#'], EFFECT, 'RSF'),
    ('config', 'enable secret MOTDEPASSE', rf'enable secret (?:[059] )?\S+', 2, 'Mot de passe du mode privilégié (chiffré).',
     ['enable secret class'], EFFECT, 'RSF'),
    ('config', 'enable password MOTDEPASSE', r'enable password (?:[07] )?\S+', 2, 'Mot de passe du mode privilégié (en clair).',
     ['enable password cisco'], EFFECT, 'RSF'),
    ('config', 'service password-encryption', r'service password-encryption', 2, 'Chiffrer les mots de passe en clair (type 7).',
     ['service password-encryption'], EFFECT, 'RSF'),
    ('config', 'no ip domain-lookup', r'no ip domain-lookup', 3, 'Ne pas chercher un mot inconnu comme nom d’hôte.',
     ['no ip domain-lookup'], EFFECT, 'RSF'),
    ('config', 'ip domain-name NOM', r'ip domain-name \S+', 2, 'Domaine (nécessaire aux clés SSH).', ['ip domain-name lab.local'],
     EFFECT, 'RSF'),
    ('config', 'username NOM [privilege N] secret|password MOTDEPASSE',
     r'username \S+(?: privilege \d+)? (?:secret|password) (?:[0579] )?\S+', 2, 'Un compte local (login local, SSH).',
     ['username admin privilege 15 secret cisco123'], EFFECT, 'RSF'),
    ('config', 'crypto key generate rsa [modulus N]', r'crypto key generate rsa(?: general-keys)?(?: modulus \d+)?', 4,
     'Clés RSA pour SSH.', ['ip domain-name lab.local', 'crypto key generate rsa modulus 1024'], EFFECT, 'RSF'),
    ('config', 'ip ssh version 1|2', r'ip ssh version [12]', 3, 'Version de SSH.', ['ip ssh version 2'], STORED, 'RSF'),
    ('config', 'ip ssh time-out N', r'ip ssh time-out \d+', 3, 'Délai d’authentification SSH.', ['ip ssh time-out 60'], STORED, 'RSF'),
    ('config', 'ip ssh authentication-retries N', r'ip ssh authentication-retries \d+', 3, 'Essais SSH autorisés.',
     ['ip ssh authentication-retries 3'], STORED, 'RSF'),
    ('config', 'no cdp run', r'no cdp run', 3, 'Désactiver CDP sur l’équipement.', ['no cdp run'], STORED, 'RSF'),
    ('config', 'lldp run', r'lldp run', 2, 'Activer LLDP.', ['lldp run'], STORED, 'RSF'),
    ('config', 'clock timezone NOM HEURES', r'clock timezone \S+ -?\d+(?: \d+)?', 2, 'Fuseau horaire.', ['clock timezone CET 1'],
     STORED, 'RSF'),
    ('config', 'ntp server A.B.C.D', rf'ntp server {IP}', 3, 'Serveur NTP.', ['ntp server 192.0.2.123'], STORED, 'RSF'),
    ('config', 'logging host A.B.C.D', rf'logging (?:host )?{IP}', 3, 'Serveur syslog.', ['logging host 192.0.2.50'], STORED, 'RSF'),
    ('config', 'logging buffered N', r'logging buffered \d+', 2, 'Journal en mémoire.', ['logging buffered 8192'], STORED, 'RSF'),
    ('config', 'snmp-server community NOM ro|rw', r'snmp-server community \S+ (?:ro|rw)', 3, 'Communauté SNMP.',
     ['snmp-server community public ro'], STORED, 'RSF'),
    ('config', 'ip default-gateway A.B.C.D', rf'ip default-gateway {IP}', 2,
     'Passerelle de gestion du switch (dans le réseau de son interface vlan).', ['ip default-gateway 192.0.2.1'], EFFECT, 'S'),
    ('config', 'ip nat inside source list NOM interface PORT overload',
     r'ip nat inside source list \S+ interface \S+(?: overload)?', 6,
     'PAT : les sources de la liste sortent avec l’adresse du port (ports marqués ip nat inside / outside).',
     ['ip nat inside source list 1 interface {p1} overload'], EFFECT, 'R'),
    ('config', 'ip nat inside source list NOM pool NOM [overload]', r'ip nat inside source list \S+ pool \S+(?: overload)?', 6,
     'NAT dynamique : les sources de la liste sortent avec les adresses du pool (overload : la première, ports traduits).',
     ['ip nat pool PUBLIC 203.0.113.10 203.0.113.20 netmask 255.255.255.0', 'ip nat inside source list 1 pool PUBLIC overload'],
     EFFECT, 'R'),
    ('config', 'ip nat inside source static A.B.C.D A.B.C.D', rf'ip nat inside source static {IP} {IP}', 6,
     'NAT statique : l’adresse interne sort et se joint par l’adresse publique (le routeur la tient sur le port outside).',
     ['ip nat inside source static 192.0.2.10 203.0.113.10'], EFFECT, 'R'),
    ('config', 'ip nat pool NOM A.B.C.D A.B.C.D netmask MASQUE',
     rf'ip nat pool \S+ {IP} {IP} (?:netmask {IP}|prefix-length \d+)', 4,
     'Plage d’adresses publiques pour le NAT dynamique (16 adresses au plus dans le lab).',
     ['ip nat pool PUBLIC 203.0.113.10 203.0.113.20 netmask 255.255.255.0'], EFFECT, 'R'),
    ('config', 'spanning-tree mode pvst|rapid-pvst|mst', r'spanning-tree mode (?:pvst|rapid-pvst|mst)', 2,
     'Mode de spanning tree.', ['spanning-tree mode rapid-pvst'], STORED, 'S'),
    ('config', 'spanning-tree vlan VLAN priority N', r'spanning-tree vlan \S+ priority \d+', 3, 'Priorité du pont pour un VLAN.',
     ['spanning-tree vlan 1 priority 4096'], STORED, 'S'),
    ('config', 'spanning-tree vlan VLAN root primary|secondary', r'spanning-tree vlan \S+ root (?:primary|secondary)', 3,
     'Devenir pont racine.', ['spanning-tree vlan 1 root primary'], STORED, 'S'),
    ('config', 'vtp mode server|client|transparent', r'vtp mode (?:server|client|transparent)', 2, 'Mode VTP.',
     ['vtp mode transparent'], STORED, 'S'),
    ('config', 'vtp domain NOM', r'vtp domain \S+', 2, 'Domaine VTP.', ['vtp domain LAB'], STORED, 'S'),
    ('config', 'ipv6 unicast-routing', r'ipv6 unicast-routing', 2, 'Routage IPv6.', ['ipv6 unicast-routing'], STORED, 'R'),
    ('config-if', 'description TEXTE', r'description .+', 1, 'Commentaire sur le port.', ['interface {p0}', 'description vers-LAN'],
     EFFECT, 'RSF'),
    ('config-if', 'speed 10|100|1000|auto', r'speed (?:10|100|1000|auto)', 1, 'Vitesse du port.', ['interface {p0}', 'speed 100'],
     STORED, 'RSF'),
    ('config-if', 'duplex full|half|auto', r'duplex (?:full|half|auto)', 1, 'Mode duplex du port.', ['interface {p0}', 'duplex full'],
     STORED, 'RSF'),
    ('config-if', 'bandwidth N', r'bandwidth \d+', 1, 'Bande passante annoncée (kbit/s).', ['interface {p0}', 'bandwidth 10000'],
     STORED, 'RF'),
    ('config-if', 'ip nat inside|outside', r'ip nat (?:inside|outside)', 2, 'Côté du NAT (indispensable à la traduction).',
     ['interface {p0}', 'ip nat inside'], EFFECT, 'R'),
    ('config-if', 'ip helper-address A.B.C.D', rf'ip helper-address {IP}', 3,
     'Relais DHCP : les demandes des clients de ce port vont à ce serveur (un seul serveur par équipement dans le lab).',
     ['interface {p0}', 'ip helper-address 198.51.100.5'], EFFECT, 'R'),
    ('config-if', 'ipv6 address X:X::X/N', r'ipv6 address \S+', 3, 'Adresse IPv6.', ['interface {p0}', 'ipv6 address 2001:db8::1/64'],
     STORED, 'R'),
    ('config-if', 'switchport port-security', r'switchport port-security', 2, 'Activer la sécurité de port.',
     ['interface {p0}', 'switchport mode access', 'switchport port-security'], STORED, 'S'),
    ('config-if', 'switchport port-security maximum N', r'switchport port-security maximum \d+', 3,
     'Nombre maximal d’adresses MAC.', ['interface {p0}', 'switchport port-security maximum 2'], STORED, 'S'),
    ('config-if', 'switchport port-security mac-address sticky', r'switchport port-security mac-address sticky', 4,
     'Apprendre les adresses MAC et les garder.', ['interface {p0}', 'switchport port-security mac-address sticky'], STORED, 'S'),
    ('config-if', 'switchport port-security violation shutdown|restrict|protect',
     r'switchport port-security violation (?:shutdown|restrict|protect)', 3, 'Réaction à une violation.',
     ['interface {p0}', 'switchport port-security violation restrict'], STORED, 'S'),
    ('config-if', 'spanning-tree portfast', r'spanning-tree portfast(?: trunk)?', 2, 'Port d’accès vers un poste (pas d’attente).',
     ['interface {p0}', 'spanning-tree portfast'], STORED, 'S'),
    ('config-if', 'spanning-tree bpduguard enable', r'spanning-tree bpduguard enable', 2, 'Couper le port s’il reçoit des BPDU.',
     ['interface {p0}', 'spanning-tree bpduguard enable'], STORED, 'S'),
    ('config-if', 'no cdp enable', r'no cdp enable', 3, 'Pas de CDP sur ce port.', ['interface {p0}', 'no cdp enable'], STORED, 'RSF'),
    ('config-line', 'password MOTDEPASSE', r'password (?:[07] )?\S+', 1, 'Mot de passe de la ligne.',
     ['line con 0', 'password cisco', 'login'], EFFECT, 'RSF'),
    ('config-line', 'login [local]', r'login(?: local)?', 1, 'Demander le mot de passe (local : un compte username).',
     ['line con 0', 'password cisco', 'login'], EFFECT, 'RSF'),
    ('config-line', 'transport input ssh|telnet|all|none', r'transport input (?:ssh|telnet|all|none)(?: (?:ssh|telnet))?', 2,
     'Protocoles d’accès à distance.', ['line vty 0 4', 'transport input ssh'], EFFECT, 'RSF'),
    ('config-line', 'access-class N in', r'access-class \S+ in', 1,
     'Seules les sources que la liste N permet ouvrent une session Telnet ou SSH.', ['line vty 0 4', 'access-class 1 in'],
     EFFECT, 'RSF'),
    ('config-line', 'exec-timeout MINUTES [SECONDES]', r'exec-timeout \d+(?: \d+)?', 1, 'Déconnexion après inactivité.',
     ['line con 0', 'exec-timeout 5 0'], STORED, 'RSF'),
    ('config-line', 'logging synchronous', r'logging synchronous', 2, 'Les messages ne coupent pas la ligne tapée.',
     ['line con 0', 'logging synchronous'], STORED, 'RSF'),
    ('config-line', 'privilege level N', r'privilege level \d+', 2, 'Niveau de privilège à la connexion.',
     ['line con 0', 'privilege level 15'], STORED, 'RSF'),
    ('config-line', 'history size N', r'history size \d+', 2, 'Taille de l’historique.', ['line con 0', 'history size 50'], STORED, 'RSF'),
    ('config-rip', 'version 1|2', r'version [12]', 1, 'Version de RIP (2 si rien n’est dit).', ['router rip', 'version 2'], EFFECT, 'R'),
    ('config-rip', 'network A.B.C.D', rf'network {IP}', 2, 'Réseau (par classe) où RIP est actif et annoncé.',
     ['router rip', 'network 192.0.2.0'], EFFECT, 'R'),
    ('config-rip', 'no auto-summary', r'no auto-summary', 2, 'Pas de résumé par classe (le comportement du lab).',
     ['router rip', 'no auto-summary'], EFFECT, 'R'),
    ('config-rip', 'passive-interface PORT', r'passive-interface \S+', 2, 'Port sans annonce RIP.',
     ['router rip', 'passive-interface {p0}'], EFFECT, 'R'),
    ('config-rip', 'default-information originate', r'default-information originate', 2, 'Annoncer la route par défaut.',
     ['router rip', 'default-information originate'], STORED, 'R'),
    ('config-eigrp', 'network A.B.C.D [JOKER]', rf'network {IP}(?: {IP})?', 2, 'Réseau où EIGRP est actif.',
     ['router eigrp 10', 'network 192.0.2.0 0.0.0.255'], STORED, 'R'),
    ('config-eigrp', 'no auto-summary', r'no auto-summary', 2, 'Pas de résumé par classe.', ['router eigrp 10', 'no auto-summary'],
     STORED, 'R'),
    ('config-eigrp', 'passive-interface PORT', r'passive-interface \S+', 2, 'Port sans voisinage EIGRP.',
     ['router eigrp 10', 'passive-interface {p0}'], STORED, 'R'),
    ('config-eigrp', 'eigrp router-id A.B.C.D', rf'eigrp router-id {IP}', 2, 'Identifiant EIGRP.',
     ['router eigrp 10', 'eigrp router-id 1.1.1.1'], STORED, 'R'),
    ('config-vlan', 'name NOM', r'name [!-~]{1,32}', 1, 'Nom du VLAN (show vlan brief, show running-config).',
     ['vlan 30', 'name SERVEURS'], EFFECT, 'S'),
]
# Block headers: the line enters a sub-mode whose lines are kept under it.
BLOCKS = [('config', 'line con 0', r'line con(?:sole)? 0', 'config-line', 'Ligne console (mot de passe, login…).', ['line con 0'], 'RSF'),
          ('config', 'line vty 0 4|15', r'line vty 0 (?:4|15)', 'config-line', 'Lignes d’accès à distance (Telnet, SSH).',
           ['line vty 0 4'], 'RSF'),
          ('config', 'line aux 0', r'line aux 0', 'config-line', 'Ligne auxiliaire.', ['line aux 0'], 'R'),
          ('config', 'router rip', r'router rip', 'config-rip', 'Démarrer RIP (BIRD dans la micro-VM ; pas avec OSPF).',
           ['router rip'], 'R'),
          ('config', 'router eigrp AS', r'router eigrp \d+', 'config-eigrp', 'Démarrer EIGRP (configuration seulement pour l’instant).',
           ['router eigrp 10'], 'R')]
CANONICAL_HEADERS = {'line console 0': 'line con 0'}


def _empty():
    return {'hostname': None, 'global': [], 'interfaces': {}, 'blocks': [], 'startup': None}


def config(node):
    return node.setdefault('cli_config', None) or _empty()


def validate(node):
    value = node.setdefault('cli_config', None)
    if value is None:
        return
    if not isinstance(value, dict) or set(value) - {'hostname', 'global', 'interfaces', 'blocks', 'startup'}:
        raise ValueError('cli_config: hostname, global, interfaces, blocks, startup.')
    full = dict(_empty(), **value)
    lines = list(full['global']) + [l for ls in full['interfaces'].values() for l in ls] + \
        [b['header'] for b in full['blocks']] + [l for b in full['blocks'] for l in b['lines']]
    if len(lines) > LIMIT_LINES or any(not isinstance(l, str) or not l.isprintable() or len(l) > LIMIT_TEXT for l in lines):
        raise ValueError(f'cli_config: at most {LIMIT_LINES} printable lines of {LIMIT_TEXT} characters.')
    if full['hostname'] is not None and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,62}', full['hostname']):
        raise ValueError('hostname: a letter, then letters, digits, - or _.')
    if set(full['interfaces']) - set(node['interfaces']) - set(node.get('subinterfaces') or {}) - set(node.get('svis') or {}):
        raise ValueError('cli_config: lines for declared interfaces only.')
    if full['startup'] is not None and (not isinstance(full['startup'], str) or len(full['startup']) > 65536):
        raise ValueError('cli_config: startup is a configuration text.')
    full['interfaces'] = {port: lines for port, lines in full['interfaces'].items() if lines}
    defaults = ({'header': 'line con 0', 'lines': []}, {'header': 'line vty 0 4', 'lines': ['login']})
    vlans = set(node.get('vlans') or [])
    full['blocks'] = [b for b in full['blocks'] if b not in defaults  # what IOS shows when nothing was configured
                      and not (b['header'].startswith('vlan ') and (not b['lines'] or int(b['header'][5:]) not in vlans))]
    empty = not (full['hostname'] or full['global'] or full['interfaces'] or full['blocks'] or full['startup'])
    node['cli_config'] = None if empty else full  # nothing beyond the model: no stored configuration


def hostname(node):
    return (node.get('cli_config') or {}).get('hostname') or node['name']


def vlan_name(node, vid):
    """The name given under « vlan VID » (« name STAFF »), or None."""
    block = next((b for b in config(node)['blocks'] if b['header'] == f'vlan {vid}'), None)
    return next((l.split(None, 1)[1] for l in block['lines'] if l.lower().startswith('name ')), None) if block else None


def drop_block(node, header):
    current = config(node)
    if any(b['header'] == header for b in current['blocks']):
        current['blocks'] = [b for b in current['blocks'] if b['header'] != header]
        node['cli_config'] = current


def _identity(line, words):
    return ' '.join(line.lower().split()[:words])


def _find(mode, low):
    for entry in GRAMMAR:
        if entry[0] == mode and re.fullmatch(entry[2], low):
            return entry
    return None


def store(node, mode, line, port=None, block=None):
    """Keep LINE (typed in MODE) in the device's configuration if IOS takes it there; False otherwise. A line replaces the
    one with the same identity (« enable secret », « username admin »…); « no X » removes it; the lines IOS writes in
    their negative form (« no ip domain-lookup », « no cdp run ») are kept as typed and removed by their positive form."""
    text = ' '.join(line.split())
    low = text.lower()
    negative = low.startswith('no ')
    current = config(node)
    target = _target(current, mode, port, block)
    entry = _find(mode, low)
    if entry is not None:  # a positive line, or one IOS keeps in its « no » form
        if entry[1] == 'hostname NOM':
            name = text.split()[1]
            current['hostname'] = None if name == node['name'] else name  # the device's own name is the default
        else:
            key = _key_of(text, mode)
            target[:] = [l for l in target if _key_of(l, mode) != key] + [text]
    elif negative and _find(mode, low[3:]) is not None:  # « no X » with X complete
        key = _key_of(low[3:], mode)
        if key == 'hostname':
            current['hostname'] = None
        target[:] = [l for l in target if _key_of(l, mode) != key]
    elif not negative and _find(mode, 'no ' + low) is not None:  # « ip domain-lookup » undoes « no ip domain-lookup »
        target[:] = [l for l in target if l.lower() != 'no ' + low]
    elif negative:  # « no enable secret », « no username admin »: the identity alone
        entry = next((e for e in GRAMMAR if e[0] == mode and not e[1].startswith('no ')
                      and _identity(e[1], e[3]) == _identity(low[3:], e[3]) and len(low[3:].split()) >= e[3]), None)
        if entry is None:
            return False
        key = _identity(low[3:], entry[3])
        if key == 'hostname':
            current['hostname'] = None
        target[:] = [l for l in target if _key_of(l, mode) != key]
    else:
        return False
    node['cli_config'] = current
    return True


def _key_of(line, mode):
    """The identity of a stored line: its first words as the grammar says (the whole line for « no » forms)."""
    low = ' '.join(line.split()).lower()
    entry = _find(mode, low)
    if entry is None:
        return low
    return low if entry[1].startswith('no ') else _identity(low, entry[3])


def _target(current, mode, port, block):
    if mode == 'config-if':
        return current['interfaces'].setdefault(port, [])
    if mode in ('config-line', 'config-rip', 'config-eigrp', 'config-vlan'):
        found = next((b for b in current['blocks'] if b['header'] == block), None)
        if found is None:  # « vlan N » keeps no block until a line goes under it
            found = {'header': block, 'lines': []}
            current['blocks'].append(found)
        return found['lines']
    return current['global']


def enter_block(node, low):
    """The sub-mode and the canonical header of a block line (line con 0, router rip…), or (None, None)."""
    no = low.startswith('no ')
    for _, syntax, pattern, mode, *_ in BLOCKS:
        if re.fullmatch(pattern, low[3:] if no else low):
            header = CANONICAL_HEADERS.get(low[3:] if no else low, low[3:] if no else low)
            current = config(node)
            if no:
                current['blocks'] = [b for b in current['blocks'] if b['header'] != header]
                node['cli_config'] = current
                return 'removed', header
            if not any(b['header'] == header for b in current['blocks']):
                current['blocks'].append({'header': header, 'lines': []})
            node['cli_config'] = current
            return mode, header
    return None, None


# ---- passwords as IOS writes them ----

_XLAT = b'dsfd;kfoA,.iyewrkldJKDHSUBsgvca69834ncxv9873254k;fg87'


def type7(password, seed=2):
    """Cisco type 7 (the reversible « service password-encryption » form)."""
    out = f'{seed:02d}'
    for index, char in enumerate(password.encode()):
        out += f'{char ^ _XLAT[(seed + index) % len(_XLAT)]:02X}'
    return out


def untype7(text):
    seed, data = int(text[:2]), bytes.fromhex(text[2:])
    return bytes(b ^ _XLAT[(seed + i) % len(_XLAT)] for i, b in enumerate(data)).decode()


def secret_hash(password, salt='mERr'):
    """The « enable secret 5 » form: an MD5-based digest of the secret (checked, never shown in clear)."""
    digest = base64.b64encode(hashlib.md5((salt + password).encode()).digest()).decode().rstrip('=').replace('+', '.')
    return f'$1${salt}${digest[:22]}'


def stored_secret(line):
    """The secret of an « enable secret » / « username … secret » line, as stored (5 $1$… or the clear text typed)."""
    words = line.split()
    value = words[-1]
    return value if len(words) >= 2 and words[-2] in ('5', '9') else secret_hash(value)


def password_of(line):
    """The clear password of a « password X », « password 7 X » or « enable password X » line."""
    words = line.split()
    return untype7(words[-1]) if len(words) >= 2 and words[-2] == '7' else words[-1]


def check_enable(node, typed):
    """None when no enable password is set; else whether TYPED is it (secret first, as on IOS)."""
    lines = config(node)['global']
    secret = next((l for l in lines if l.lower().startswith('enable secret ')), None)
    if secret:
        return secret_hash(typed) == stored_secret(secret)
    password = next((l for l in lines if l.lower().startswith('enable password ')), None)
    return None if password is None else typed == password_of(password)


def console_login(node):
    """The console password when « line con 0 » has « login » and a password, else None."""
    block = next((b for b in config(node)['blocks'] if b['header'] == 'line con 0'), None)
    if not block or not any(l.lower() == 'login' for l in block['lines']):
        return None
    password = next((l for l in block['lines'] if l.lower().startswith('password ')), None)
    return password_of(password) if password else None


def banner(node):
    line = next((l for l in config(node)['global'] if l.lower().startswith('banner motd ')), None)
    if not line:
        return ''
    body = line[len('banner motd '):]
    if body.startswith('^C') and body.endswith('^C') and len(body) >= 4:
        return body[2:-2]
    return body[1:-1] if len(body) >= 2 and body[0] == body[-1] else body


# ---- show running-config ----

def _shown(line, encrypt):
    """A stored line as « show running-config » prints it: secrets hashed, passwords type 7 when asked."""
    words = line.split()
    low = [w.lower() for w in words]
    if low[:2] == ['enable', 'secret'] or (low[:1] == ['username'] and 'secret' in low):
        at = low.index('secret')
        return ' '.join(words[:at + 1] + ['5', stored_secret(line)])
    if low[:2] == ['enable', 'password'] or low[:1] == ['password'] or (low[:1] == ['username'] and 'password' in low):
        at = low.index('password')
        clear = password_of(line)
        return ' '.join(words[:at + 1] + (['7', type7(clear)] if encrypt else [clear]))
    return line


def render_global(node):
    """Stored global lines in IOS's order, without the ones IOS prints near the end."""
    current = config(node)
    encrypt = any(l.lower() == 'service password-encryption' for l in current['global'])
    tail = ('banner ', 'ntp ', 'logging ', 'snmp-server ', 'ip nat ', 'crypto key ')
    order = ('service ', 'enable ', 'username ', 'no ip domain-lookup', 'ip domain-name', 'ip ssh', 'clock ', 'spanning-tree ',
             'vtp ', 'no cdp', 'lldp', 'ip default-gateway', 'ipv6 ')
    rank = lambda line: next((i for i, p in enumerate(order) if line.lower().startswith(p)), len(order))
    return [_shown(l, encrypt) for l in sorted(current['global'], key=rank) if not l.lower().startswith(tail)]


def render_interface(node, port):
    current = config(node)
    lines = current['interfaces'].get(port, [])
    return [l for l in lines if l.lower().startswith('description ')], [l for l in lines if not l.lower().startswith('description ')]


def render_tail(node):
    """Routing blocks, NAT, SNMP, logging, NTP, banner and the console/vty lines, in IOS's order."""
    current = config(node)
    encrypt = any(l.lower() == 'service password-encryption' for l in current['global'])
    lines = []
    for block in current['blocks']:
        if block['header'].startswith('router '):
            lines += [block['header']] + [' ' + l for l in block['lines']] + ['!']
    lines += [l for l in current['global'] if l.lower().startswith('ip nat ')]
    lines += [l for l in current['global'] if l.lower().startswith(('snmp-server ', 'logging ', 'ntp '))]
    text = banner(node)
    if text:
        lines += [f'banner motd ^C{text}^C', '!']
    shown = {b['header'] for b in current['blocks']}
    for header in ('line con 0', 'line aux 0', 'line vty 0 4', 'line vty 0 15'):
        block = next((b for b in current['blocks'] if b['header'] == header), None)
        if block:
            lines += [header] + [' ' + _shown(l, encrypt) for l in block['lines']] + ['!']
        elif header in ('line con 0', 'line vty 0 4') and not (header == 'line vty 0 4' and 'line vty 0 15' in shown):
            lines += [header] + ([' login'] if header.startswith('line vty') else []) + ['!']
    return lines


def catalogue_entries():
    """The command catalogue's entries for these commands (examples checked by the catalogue's tests)."""
    found = []
    for mode, syntax, _, _, text, example, effect, roles in GRAMMAR:
        note = '' if effect == EFFECT else ' (configuration enregistrée ; sans effet sur le trafic du lab pour l’instant)'
        found.append(('Configuration Cisco', mode, syntax, text + note, example, roles))
    for mode, syntax, _, _, text, example, roles in BLOCKS:
        found.append(('Configuration Cisco', mode, syntax, text, example, roles))
    return found
