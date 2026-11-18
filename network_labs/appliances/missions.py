"""Guided labs: a starting lab, goals, and checks that grade the student's work.

Two kinds of checks. Configuration checks read the lab draft (a route, a VLAN port, a Virtual IP, or a
packet run through the firewall policy as the guest's iptables would see it). Real checks are pings
sent from the running micro-VMs (one sudo-confirmed request), graded on what the network actually did.
A mission is solved when every check passes; real checks only count once the lab runs.
"""
import ipaddress

from .microvm import (dhcp_example, firewall_nat_example, ospf_example, quad_router_example, router_chain_example,
                      router_on_a_stick_example, switch_vlan_example)
from .native_models import port_names
from .spec import validate
from .vendor_config import routes


def _route_lab(kernel, disk):
    lab = router_chain_example(kernel, disk)
    lab['name'] = 'mission-route-manquante'
    r1, r2 = lab['nodes'][0], lab['nodes'][1]
    r1.update(model='cisco-isr4331')
    r2.update(model='juniper-mx204')
    r1.pop('guest_network', None)  # the fault: R1 does not know the far LAN
    return validate(lab)


def _vlan_lab(kernel, disk):
    lab = switch_vlan_example(kernel, disk)
    lab['name'] = 'mission-isoler-un-vlan'
    sw1, sw2 = lab['nodes'][0], lab['nodes'][1]
    sw1['model'], sw2['model'] = 'cisco-9200l', 'cisco-2960'
    sw1['switchports']['eth2'] = {'mode': 'access', 'vlan': 10}  # VM3 still sits in the users' VLAN
    return validate(lab)


def _publish_lab(kernel, disk):
    lab = firewall_nat_example(kernel, disk)
    lab['name'] = 'mission-publier-un-serveur'
    fw = lab['nodes'][0]
    fw['model'] = 'fortigate'
    fw['firewall']['rules'] = [r for r in fw['firewall']['rules'] if r['name'] != 'published-ping-in']
    fw['firewall']['nat'] = [r for r in fw['firewall']['nat'] if r['type'] != 'dnat']
    return validate(lab)


def _stick_lab(kernel, disk):
    lab = router_on_a_stick_example(kernel, disk)
    lab['name'] = 'mission-router-on-a-stick'
    switch, router = lab['nodes'][0], lab['nodes'][1]
    switch['model'], router['model'] = 'cisco-9200l', 'cisco-isr4331'
    router['subinterfaces']['eth0.20']['vlan'] = 30  # the fault: the VLAN 20 subinterface is tagged 30
    return validate(lab)


def _dhcp_lab(kernel, disk):
    lab = dhcp_example(kernel, disk)
    lab['name'] = 'mission-serveur-dhcp'
    router = lab['nodes'][0]
    router['model'] = 'cisco-isr4331'
    router['dhcp_server'] = None  # VM2 asks for an address and nobody answers
    return validate(lab)


def _ospf_lab(kernel, disk):
    lab = ospf_example(kernel, disk)
    lab['name'] = 'mission-ospf-multi-constructeurs'
    lab['nodes'][0]['ospf'] = None  # R1 (Cisco) has not joined OSPF yet: R2 (Juniper) and R3 (Huawei) already run it
    return validate(lab)


def _acl_lab(kernel, disk):
    lab = quad_router_example(kernel, disk)
    lab['name'] = 'mission-acl-invites'
    lab['nodes'][0]['model'] = 'cisco-ios-router'
    names = {'VM1': 'Invite', 'VM2': 'Personnel', 'VM3': 'Serveur', 'VM4': 'Internet'}
    for node in lab['nodes']:
        node['name'] = names.get(node['name'], node['name'])
    lab['links'] = [[[names.get(a, a), p], [names.get(b, b), q]] for (a, p), (b, q) in lab['links']]
    return validate(lab)


REAL_KINDS = ('reach', 'ospf-neighbor')


MISSIONS = [{'id': 'route-manquante',
             'lab': 'mission-route-manquante',
             'title': 'La route manquante',
             'level': 'Débutant',
             'kind': 'Dépannage',
             'vendors': 'Cisco ISR · Juniper MX',
             'story': 'Deux sites reliés par deux routeurs. Depuis le site A, VM2 ne joint plus le serveur VM3 du site B. Trouver la '
                      'panne avec les commandes show et la corriger.',
             'hints': ['Sur R1 : show ip route. Quel réseau manque ?', 'Le prochain saut vers le site B est R2, 203.0.113.2.'],
             'build': _route_lab,
             'checks': [{'kind': 'route',
                         'node': 'R1',
                         'destination': '198.51.100.20',
                         'via': '203.0.113.2',
                         'text': 'R1 a une route vers le site B (198.51.100.0/24) par R2'},
                        {'kind': 'reach',
                         'source': 'VM2',
                         'destination': '198.51.100.20',
                         'expect': True,
                         'text': 'VM2 joint VM3 (ping réel)'},
                        {'kind': 'reach',
                         'source': 'VM3',
                         'destination': '192.0.2.20',
                         'expect': True,
                         'text': 'VM3 répond à VM2 (ping réel)'}]},
            {'id': 'isoler-un-vlan',
             'lab': 'mission-isoler-un-vlan',
             'title': 'Isoler un poste dans un VLAN',
             'level': 'Intermédiaire',
             'kind': 'Configuration',
             'vendors': 'Cisco Catalyst 9200L · 2960',
             'story': 'VM3 appartient à la comptabilité et doit quitter le VLAN 10 des utilisateurs pour le VLAN 20, sans couper les '
                      'utilisateurs répartis sur les deux switches. Nécessite le noyau Network LABS (802.1Q).',
             'hints': ['VM3 est câblé sur gi1/0/3 de SW1.',
                       'switchport access vlan 20 — et le trunk vers SW2 doit toujours porter le VLAN 10.'],
             'build': _vlan_lab,
             'checks': [{'kind': 'switchport',
                         'node': 'SW1',
                         'port': 'eth2',
                         'vlan': 20,
                         'text': 'Le port de VM3 (gi1/0/3) est en access VLAN 20'},
                        {'kind': 'trunk',
                         'node': 'SW1',
                         'port': 'eth3',
                         'vlan': 10,
                         'text': 'Le trunk vers SW2 porte toujours le VLAN 10'},
                        {'kind': 'reach',
                         'source': 'VM1',
                         'destination': '192.0.2.14',
                         'expect': True,
                         'text': 'VM1 joint VM4 sur l’autre switch (ping réel)'},
                        {'kind': 'reach',
                         'source': 'VM1',
                         'destination': '192.0.2.13',
                         'expect': False,
                         'text': 'VM1 ne joint plus VM3 (ping réel)'}]},
            {'id': 'publier-un-serveur',
             'lab': 'mission-publier-un-serveur',
             'title': 'Publier un serveur derrière le pare-feu',
             'level': 'Intermédiaire',
             'kind': 'Configuration',
             'vendors': 'Fortinet FortiGate',
             'story': 'Le serveur VM2 (192.0.2.20) est dans le LAN derrière FW1. Il doit être joignable depuis l’extérieur à '
                      'l’adresse publique 198.51.100.1, en ICMP uniquement : pas de SSH depuis Internet.',
             'hints': ['Policy & Objects › Virtual IPs : 198.51.100.1 → 192.0.2.20 sur port2.',
                       'Une politique port2 → port1 vers 192.0.2.20/32, service ALL_ICMP, action ACCEPT.'],
             'build': _publish_lab,
             'checks': [{'kind': 'vip',
                         'node': 'FW1',
                         'external': '198.51.100.1',
                         'mapped': '192.0.2.20',
                         'port': 'eth1',
                         'text': 'Une Virtual IP publie 198.51.100.1 vers 192.0.2.20 sur port2'},
                        {'kind': 'policy',
                         'node': 'FW1',
                         'packet': {'in': 'eth1', 'source': '198.51.100.20', 'destination': '198.51.100.1', 'protocol': 'icmp'},
                         'expect': 'accept',
                         'text': 'La politique laisse passer le ping externe vers le serveur'},
                        {'kind': 'policy',
                         'node': 'FW1',
                         'packet': {'in': 'eth1',
                                    'source': '198.51.100.20',
                                    'destination': '198.51.100.1',
                                    'protocol': 'tcp',
                                    'dport': 22},
                         'expect': 'drop',
                         'text': 'Le SSH depuis l’extérieur reste bloqué'},
                        {'kind': 'reach',
                         'source': 'VM3',
                         'destination': '198.51.100.1',
                         'expect': True,
                         'text': 'VM3 joint le serveur publié (ping réel)'},
                        {'kind': 'reach',
                         'source': 'VM2',
                         'destination': '198.51.100.20',
                         'expect': True,
                         'text': 'Le LAN sort toujours (ping réel)'}]}]
MISSIONS += [
    {'id': 'router-on-a-stick', 'lab': 'mission-router-on-a-stick', 'title': 'Routage inter-VLAN sur un seul lien',
     'level': 'Intermédiaire', 'kind': 'Dépannage', 'vendors': 'Cisco ISR 4331 · Catalyst 9200L',
     'story': 'R1 route les VLAN 10 et 20 sur un seul trunk (router-on-a-stick). Depuis la mise en service, VM1 (VLAN 10) '
              'ne joint pas VM2 (VLAN 20). Nécessite le noyau Network LABS (802.1Q).',
     'hints': ['Sur R1 : show running-config, regarder les sous-interfaces de gi0/0/0.',
               'interface gi0/0/0.20 puis encapsulation dot1Q 20 : l’étiquette doit être celle du VLAN des postes.'],
     'build': _stick_lab,
     'checks': [{'kind': 'subinterface', 'node': 'R1', 'vlan': 20, 'address': '198.51.100.1/24',
                 'text': 'R1 a une sous-interface étiquetée VLAN 20 avec 198.51.100.1/24'},
                {'kind': 'reach', 'source': 'VM1', 'destination': '198.51.100.10', 'expect': True,
                 'text': 'VM1 (VLAN 10) joint VM2 (VLAN 20)'},
                {'kind': 'reach', 'source': 'VM2', 'destination': '192.0.2.10', 'expect': True,
                 'text': 'VM2 (VLAN 20) joint VM1 (VLAN 10)'}]},
    {'id': 'serveur-dhcp', 'lab': 'mission-serveur-dhcp', 'title': 'Distribuer les adresses avec DHCP', 'level': 'Débutant',
     'kind': 'Configuration', 'vendors': 'Cisco ISR 4331',
     'story': 'VM2 est configuré en DHCP mais personne ne lui répond. Faire de R1 le serveur DHCP du LAN 192.0.2.0/24 : '
              'passerelle 192.0.2.1, et les adresses .1 à .99 réservées aux équipements fixes.',
     'hints': ['ip dhcp excluded-address 192.0.2.1 192.0.2.99', 'ip dhcp pool LAN, puis network 192.0.2.0 255.255.255.0 et '
               'default-router 192.0.2.1.'],
     'build': _dhcp_lab,
     'checks': [{'kind': 'dhcp', 'node': 'R1', 'port': 'eth0', 'router': '192.0.2.1', 'first': '192.0.2.100',
                 'text': 'R1 sert un pool DHCP sur gi0/0/0 avec la passerelle 192.0.2.1, hors .1–.99'},
                {'kind': 'reach', 'source': 'VM2', 'destination': '198.51.100.20', 'expect': True,
                 'text': 'VM2 obtient une adresse et joint VM3 (ping réel)'}]},
]
MISSIONS.append(
    {'id': 'ospf-multi-constructeurs', 'lab': 'mission-ospf-multi-constructeurs', 'title': 'OSPF entre trois constructeurs',
     'level': 'Avancé', 'kind': 'Configuration', 'vendors': 'Cisco ISR 4331 · Juniper MX204 · Huawei AR6120',
     'story': 'R2 (Juniper) et R3 (Huawei) échangent déjà leurs routes en OSPF, zone 0. Faire entrer R1 (Cisco) dans OSPF '
              'pour que le LAN de VM2 et celui de VM3 se joignent, sans aucune route statique. Le LAN de R1 ne doit pas '
              'envoyer de hello vers les postes. Nécessite l’image micro-VM avec BIRD (--with-routing).',
     'hints': ['Sur R2 : show ospf neighbor, puis sur R1 : router ospf 1.',
               'network 192.0.2.0 0.0.0.255 area 0, network 203.0.113.0 0.0.0.3 area 0, puis passive-interface gi0/0/0.'],
     'build': _ospf_lab,
     'checks': [{'kind': 'ospf', 'node': 'R1', 'port': 'eth1', 'passive': False,
                 'text': 'R1 active OSPF zone 0 sur gi0/0/1, vers R2'},
                {'kind': 'ospf', 'node': 'R1', 'port': 'eth0', 'passive': True,
                 'text': 'R1 annonce son LAN 192.0.2.0/24, en interface passive'},
                {'kind': 'ospf-neighbor', 'node': 'R1', 'neighbor': '2.2.2.2',
                 'text': 'R1 voit R2 (2.2.2.2) en état Full (OSPF réel)'},
                {'kind': 'reach', 'source': 'VM2', 'destination': '198.51.100.20', 'expect': True,
                 'text': 'VM2 joint VM3 à travers les trois routeurs (ping réel)'},
                {'kind': 'reach', 'source': 'VM3', 'destination': '192.0.2.20', 'expect': True,
                 'text': 'VM3 répond à VM2 (ping réel)'}]})
MISSIONS.append(
    {'id': 'acl-invites', 'lab': 'mission-acl-invites', 'title': 'Filtrer le Wi-Fi invités avec une ACL', 'level': 'Intermédiaire',
     'kind': 'Configuration', 'vendors': 'Cisco IOS',
     'story': 'Le Wi-Fi invités (gi0/0, 192.0.2.0/24) joint le serveur interne 203.0.113.10. Il ne doit plus le joindre, mais '
              'doit toujours sortir vers Internet (100.64.0.10), et le personnel (gi0/1) joint toujours le serveur. Une ACL '
              'étendue appliquée en entrée sur gi0/0. Nécessite le disque complet (Préparer cet ordinateur).',
     'hints': ['ip access-list extended INVITES, une ligne deny puis une ligne permit : sans permit, tout est refusé.',
               'deny icmp 192.0.2.0 0.0.0.255 host 203.0.113.10, permit ip any any, puis interface gi0/0 et '
               'ip access-group INVITES in.'],
     'build': _acl_lab,
     'checks': [{'kind': 'acl', 'node': 'R1', 'port': 'eth0', 'packet': {'source': '192.0.2.10', 'destination': '203.0.113.10',
                                                                         'protocol': 'icmp'}, 'expect': 'deny',
                 'text': 'L’ACL de gi0/0 refuse le ping des invités vers le serveur'},
                {'kind': 'acl', 'node': 'R1', 'port': 'eth0', 'packet': {'source': '192.0.2.10', 'destination': '100.64.0.10',
                                                                         'protocol': 'icmp'}, 'expect': 'permit',
                 'text': 'Les invités sortent toujours vers Internet'},
                {'kind': 'reach', 'source': 'Invite', 'destination': '203.0.113.10', 'expect': False,
                 'text': 'Invité ne joint plus le serveur (ping réel)'},
                {'kind': 'reach', 'source': 'Invite', 'destination': '100.64.0.10', 'expect': True,
                 'text': 'Invité joint Internet (ping réel)'},
                {'kind': 'reach', 'source': 'Personnel', 'destination': '203.0.113.10', 'expect': True,
                 'text': 'Le personnel joint le serveur (ping réel)'}]})
BY_ID = {mission['id']: mission for mission in MISSIONS}


def mission(mission_id):
    if isinstance(mission_id, str) and mission_id.startswith('panne-'):
        from .faults import LABS, mission_for
        if mission_id[len('panne-'):] in LABS:
            return mission_for(mission_id[len('panne-'):])
    if isinstance(mission_id, str) and mission_id.startswith('scenario-') and mission_id[len('scenario-'):].isdigit():
        from .scenarios import mission_for
        return mission_for(int(mission_id[len('scenario-'):]))
    if mission_id not in BY_ID:
        raise ValueError('Mission inconnue : ' + str(mission_id))
    return BY_ID[mission_id]


def _node(spec, name):
    return next((n for n in spec['nodes'] if n['name'] == name), None)


def evaluate_policy(node, packet):
    """'accept' or 'drop' for one new packet entering NODE: destination NAT first, then the first matching rule."""
    policy = node.get('firewall')
    if policy is None:
        return 'accept'
    destination, dport = ipaddress.IPv4Address(packet['destination']), packet.get('dport')
    protocol = packet['protocol']
    for entry in policy.get('nat', []):
        if entry['type'] == 'dnat' and entry.get('in') == packet['in'] and destination in ipaddress.IPv4Network(entry['destination']):
            wanted = entry.get('protocol', 'any')
            if wanted not in ('any', protocol) or (entry.get('dport') and entry['dport'] != dport):
                continue
            destination = ipaddress.IPv4Address(entry['to'])
            dport = entry.get('to_port', dport)
            break
    out = next((p for p, a in node['interfaces'].items() if a and destination in ipaddress.IPv4Interface(a).network), None)
    if out is None:
        for network, gateway in routes(node):
            if destination in ipaddress.IPv4Network(network):
                hop = ipaddress.IPv4Address(gateway)
                out = next((p for p, a in node['interfaces'].items() if a and hop in ipaddress.IPv4Interface(a).network), None)
                break
    source = ipaddress.IPv4Address(packet['source'])
    for rule in policy.get('rules', []):
        if rule.get('in') not in (None, packet['in']) or rule.get('out') not in (None, out):
            continue
        if rule.get('source') and source not in ipaddress.IPv4Network(rule['source']):
            continue
        if rule.get('destination') and destination not in ipaddress.IPv4Network(rule['destination']):
            continue
        if rule.get('protocol', 'any') not in ('any', protocol) or (rule.get('dport') and rule['dport'] != dport):
            continue
        return rule['action']
    return policy.get('default', 'drop')


def _check_config(spec, check):
    node = _node(spec, check['node'])
    if node is None:
        return False, 'Équipement absent : ' + check['node']
    shown = port_names(node)
    kind = check['kind']
    if kind == 'route':
        target = ipaddress.IPv4Address(check['destination'])
        if any(a and target in ipaddress.IPv4Interface(a).network for a in node['interfaces'].values()):
            return True, 'réseau directement connecté'
        for network, gateway in routes(node):
            if target in ipaddress.IPv4Network(network):
                ok = gateway == check['via']
                return ok, f'route {network} via {gateway}' + ('' if ok else f' (attendu : via {check["via"]})')
        return False, f'aucune route ne couvre {check["destination"]}'
    if kind in ('switchport', 'trunk'):
        port = (node.get('switchports') or {}).get(check['port'], {'mode': 'access', 'vlan': 1})
        name = shown.get(check['port'], check['port'])
        if kind == 'switchport':
            ok = port['mode'] == 'access' and port['vlan'] == check['vlan']
            return ok, f'{name} : ' + (f'access VLAN {port["vlan"]}' if port['mode'] == 'access' else 'trunk')
        allowed = node.get('vlans', []) if port.get('allowed') == 'all' else port.get('allowed', [])
        ok = port['mode'] == 'trunk' and check['vlan'] in allowed
        return ok, f'{name} : ' + ('trunk ' + ','.join(map(str, allowed)) if port['mode'] == 'trunk' else f'access VLAN {port["vlan"]}')
    if kind == 'vip':
        for entry in (node.get('firewall') or {}).get('nat', []):
            if (entry['type'] == 'dnat' and entry.get('in') == check['port'] and entry['to'] == check['mapped']
                    and ipaddress.IPv4Address(check['external']) in ipaddress.IPv4Network(entry['destination'])):
                return True, f'{entry["name"]} : {check["external"]} → {check["mapped"]}'
        return False, 'aucune Virtual IP ne publie cette adresse'
    if kind == 'policy':
        verdict = evaluate_policy(node, check['packet'])
        return verdict == check['expect'], 'autorisé' if verdict == 'accept' else 'bloqué'
    if kind == 'subinterface':
        for name, sub in (node.get('subinterfaces') or {}).items():
            if sub.get('address') and ipaddress.IPv4Interface(sub['address']) == ipaddress.IPv4Interface(check['address']):
                ok = sub.get('vlan') == check['vlan']
                parent, _, vid = name.partition('.')
                return ok, f'{shown.get(parent, parent)}.{vid} : encapsulation dot1Q {sub.get("vlan")}'
        return False, 'aucune sous-interface ne porte ' + check['address']
    if kind == 'dhcp':
        server = node.get('dhcp_server')
        if not server:
            return False, 'aucun serveur DHCP'
        name = shown.get(server['interface'], server['interface'])
        problems = []
        if server['interface'] != check['port']:
            problems.append(f'sur {name}')
        if server.get('router') != check['router']:
            problems.append('passerelle ' + (server.get('router') or 'absente'))
        if ipaddress.IPv4Address(server['start']) < ipaddress.IPv4Address(check['first']):
            problems.append(f'le pool commence à {server["start"]}')
        return not problems, f'{name} : {server["start"]} – {server["end"]}' + (' (' + ', '.join(problems) + ')' if problems else '')
    if kind == 'acl':
        from .acl import evaluate
        name = shown.get(check['port'], check['port'])
        listed = (node.get('acl_ports') or {}).get(check['port'])
        verdict = evaluate(node, check['port'], check['packet'])
        detail = f'{name} : ' + (f'liste {listed}, ' if listed else 'aucune liste, ') + ('autorisé' if verdict == 'permit' else 'refusé')
        return verdict == check['expect'], detail
    if kind == 'ospf':
        name = shown.get(check['port'], check['port'])
        if not node.get('ospf'):
            return False, 'pas de processus OSPF'
        from .ospf import enabled_interfaces
        port = enabled_interfaces(node).get(check['port'])
        if port is None:
            return False, f'{name} : aucun réseau OSPF ne couvre ce port'
        ok = port['passive'] == check['passive']
        return ok, f'{name} : ' + ('passive' if port['passive'] else 'active') + f', coût {port["cost"]}' + (
            '' if ok else ' (attendu : ' + ('passive' if check['passive'] else 'active, avec des hello') + ')')
    raise ValueError('Contrôle inconnu : ' + kind)


def grade(spec, mission_id, real=None):
    """Results for every check: configuration checks from SPEC, real checks from REAL ({index: (ok, detail)}) when given."""
    current = mission(mission_id)
    results = []
    for index, check in enumerate(current['checks']):
        if check['kind'] in REAL_KINDS:
            if real and index in real:
                ok, detail = real[index]  # REAL: {index: (ok, detail)}, from run_real's results
                results.append({'text': check['text'], 'kind': 'réel', 'status': 'ok' if ok else 'fail', 'detail': detail})
            else:
                results.append({'text': check['text'], 'kind': 'réel', 'status': 'pending',
                                'detail': 'lab à démarrer puis « Tester sur le lab »'})
            continue
        try:
            ok, detail = _check_config(spec, check)
        except (ValueError, KeyError) as error:
            ok, detail = False, str(error)
        results.append({'text': check['text'], 'kind': 'configuration', 'status': 'ok' if ok else 'fail', 'detail': detail})
    passed = sum(r['status'] == 'ok' for r in results)
    return {'mission': mission_id, 'results': results, 'passed': passed, 'total': len(results),
            'solved': passed == len(results)}


MAX_PROBES = 12


def encode_probes(checks):
    """'SOURCE>ADDRESS>1;...' for the privileged request: the pings a generated scenario expects to work (1) or fail (0)."""
    return ';'.join(f"{c['source']}>{c['destination']}>{int(bool(c['expect']))}" for c in checks)


def decode_probes(text):
    """The reach checks of encode_probes(), validated: identifiers, IPv4 addresses, at most MAX_PROBES."""
    from .spec import identifier
    if not isinstance(text, str) or len(text) > 1024:
        raise ValueError('Invalid mission probes.')
    checks = []
    for item in text.split(';'):
        source, address, expect = item.split('>')
        if expect not in ('0', '1'):
            raise ValueError('Invalid mission probe expectation.')
        checks.append({'kind': 'reach', 'source': identifier(source), 'destination': str(ipaddress.IPv4Address(address)),
                       'expect': expect == '1', 'text': ''})
    if not 1 <= len(checks) <= MAX_PROBES:
        raise ValueError('A mission has 1..12 probes.')
    return checks


def run_real(manager, mission_id, probes=None):
    """Send the mission's pings from the running guests: [[index, ok, detail], ...] (caller holds the lab lock).
    PROBES (encode_probes text) replaces the catalogue's checks for a scenario generated on the student's machine."""
    current = {'checks': decode_probes(probes)} if probes is not None else mission(mission_id)
    found = []
    for index, check in enumerate(current['checks']):
        if check['kind'] == 'ospf-neighbor':
            found.append([index, *_neighbor(manager, check)])
            continue
        if check['kind'] != 'reach':
            continue
        result = manager.ping_node(check['source'], check['destination'], count=3)
        answered = sum(r['ok'] for r in result['replies'])
        ok = (answered > 0) == check['expect']
        expected = 'réponse' if check['expect'] else 'aucune réponse'
        found.append([index, ok, f'{answered}/3 réponses' + ('' if ok else f' (attendu : {expected})')])
    return {'mission': mission_id, 'results': found}


def _neighbor(manager, check):
    """(ok, detail) from the neighbour table of the node's running OSPF daemon."""
    try:
        observation = manager.observe_node(check['node'])
    except Exception as error:  # a stopped daemon or an image without BIRD: the check fails with the reason
        return False, str(error)
    if not observation.get('ospf'):
        return False, 'OSPF ne tourne pas sur ' + check['node']
    rows = {row['router_id']: row for row in observation['ospf']['neighbors']}
    row = rows.get(check['neighbor'])
    if row is None:
        return False, 'voisins : ' + (', '.join(f'{r} {v["state"]}' for r, v in rows.items()) or 'aucun')
    return row['state'] == 'Full', f'{check["neighbor"]} : {row["state"]}' + ('' if row['state'] == 'Full' else ' (attendu : Full)')
