"""Guided labs: a starting lab, goals, and checks that grade the student's work.

Two kinds of checks. Configuration checks read the lab draft (a route, a VLAN port, a Virtual IP, or a
packet run through the firewall policy as the guest's iptables would see it). Real checks are pings
sent from the running micro-VMs (one sudo-confirmed request), graded on what the network actually did.
A mission is solved when every check passes; real checks only count once the lab runs.
"""
import ipaddress

from .microvm import firewall_nat_example, router_chain_example, switch_vlan_example
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
BY_ID = {mission['id']: mission for mission in MISSIONS}


def mission(mission_id):
    if isinstance(mission_id, str) and mission_id.startswith('panne-'):
        from .faults import LABS, mission_for
        if mission_id[len('panne-'):] in LABS:
            return mission_for(mission_id[len('panne-'):])
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
    raise ValueError('Contrôle inconnu : ' + kind)


def grade(spec, mission_id, real=None):
    """Results for every check: configuration checks from SPEC, real checks from REAL ({index: (ok, detail)}) when given."""
    current = mission(mission_id)
    results = []
    for index, check in enumerate(current['checks']):
        if check['kind'] == 'reach':
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


def run_real(manager, mission_id):
    """Send the mission's pings from the running guests: [[index, ok, detail], ...] (caller holds the lab lock)."""
    current = mission(mission_id)
    found = []
    for index, check in enumerate(current['checks']):
        if check['kind'] != 'reach':
            continue
        result = manager.ping_node(check['source'], check['destination'], count=3)
        answered = sum(r['ok'] for r in result['replies'])
        ok = (answered > 0) == check['expect']
        expected = 'réponse' if check['expect'] else 'aucune réponse'
        found.append([index, ok, f'{answered}/3 réponses' + ('' if ok else f' (attendu : {expected})')])
    return {'mission': mission_id, 'results': found}
