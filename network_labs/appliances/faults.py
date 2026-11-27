"""Troubleshooting mode ("Panne"): a working lab, one hidden fault, and a grade once it is repaired.

Each supported lab has known health probes (pings whose outcome the working lab produces, real-KVM
tested). A fault changes one thing in the draft and states only the symptom a user would report.
Grading checks that the faulted item is repaired (compared with the working lab, by behaviour where
possible) and, on the running lab, that every health probe behaves as in the working lab.
"""
import copy
import ipaddress
import random

from .microvm import firewall_nat_example, ospf_example, router_chain_example, switch_vlan_example
from .spec import validate
from .vendor_config import routes


def _routers(kernel, disk):
    lab = router_chain_example(kernel, disk)
    lab['nodes'][0]['model'], lab['nodes'][1]['model'] = 'cisco-isr4331', 'juniper-mx204'
    lab['name'] = 'panne-routeurs'
    return validate(lab)


def _vlans(kernel, disk):
    lab = switch_vlan_example(kernel, disk)
    lab['nodes'][0]['model'], lab['nodes'][1]['model'] = 'cisco-9200l', 'cisco-2960'
    lab['name'] = 'panne-vlans'
    return validate(lab)


def _firewall(kernel, disk):
    lab = firewall_nat_example(kernel, disk)
    lab['nodes'][0]['model'] = 'fortigate'
    lab['name'] = 'panne-pare-feu'
    return validate(lab)


def _ospf(kernel, disk):
    lab = ospf_example(kernel, disk)
    lab['name'] = 'panne-ospf'
    return validate(lab)


def reach(source, destination, expect, text):
    return {'kind': 'reach', 'source': source, 'destination': destination, 'expect': expect, 'text': text}


LABS = {
    'routeurs': {'title': 'Deux sites routés', 'vendors': 'Cisco ISR · Juniper MX', 'build': _routers,
                 'probes': [reach('VM2', '198.51.100.20', True, 'VM2 (site A) joint VM3 (site B)'),
                            reach('VM3', '192.0.2.20', True, 'VM3 (site B) joint VM2 (site A)')]},
    'vlans': {'title': 'Deux switches et des VLAN', 'vendors': 'Cisco Catalyst 9200L · 2960', 'build': _vlans,
              'probes': [reach('VM1', '192.0.2.12', True, 'VM1 joint VM2 (même switch, VLAN 10)'),
                         reach('VM1', '192.0.2.14', True, 'VM1 joint VM4 (autre switch, VLAN 10)'),
                         reach('VM1', '192.0.2.13', False, 'VM1 ne joint pas VM3 (VLAN 20)')]},
    'ospf': {'title': 'OSPF entre trois constructeurs', 'vendors': 'Cisco ISR · Juniper MX · Huawei AR', 'build': _ospf,
             'probes': [reach('VM2', '198.51.100.20', True, 'VM2 (derrière R1) joint VM3 (derrière R3)'),
                        reach('VM3', '192.0.2.20', True, 'VM3 joint VM2')]},
    'pare-feu': {'title': 'Pare-feu avec NAT', 'vendors': 'Fortinet FortiGate', 'build': _firewall,
                 'probes': [reach('VM2', '198.51.100.20', True, 'Le LAN (VM2) sort vers VM3'),
                            reach('VM3', '198.51.100.1', True, 'VM3 joint le serveur publié (198.51.100.1)')]},
}


def _node(spec, name):
    return next(n for n in spec['nodes'] if n['name'] == name)


# ---- faults: (lab, id) -> how to break it, what a user would report, how to tell it is repaired ----

def _drop_route(name):
    def apply(spec):
        node = _node(spec, name)
        node.pop('guest_network', None)
        node['routes'] = []
    def fixed(spec, original):
        want = [r for r in routes(_node(original, name)) if r[0] != '0.0.0.0/0']
        have = routes(_node(spec, name))
        missing = [n for n, g in want if (n, g) not in have]
        return not missing, ('routes de ' + name + ' complètes' if not missing else 'route absente : ' + ', '.join(missing))
    return apply, fixed


def _address(name, port, wrong):
    def apply(spec):
        _node(spec, name)['interfaces'][port] = wrong
    def fixed(spec, original):
        have, want = _node(spec, name)['interfaces'][port], _node(original, name)['interfaces'][port]
        ok = ipaddress.IPv4Interface(have) == ipaddress.IPv4Interface(want) if have else False
        return ok, f'{name} {port} : {have or "sans adresse"}'
    return apply, fixed


def _gateway(name, wrong):
    def apply(spec):
        _node(spec, name)['gateway'] = wrong
    def fixed(spec, original):
        have = _node(spec, name).get('gateway')
        return have == _node(original, name).get('gateway'), f'passerelle de {name} : {have or "aucune"}'
    return apply, fixed


def _switchport(name, port, policy):
    def apply(spec):
        node = _node(spec, name)
        node['switchports'][port] = policy
        node['vlans'] = sorted(set(node['vlans']) | ({policy['vlan']} if policy['mode'] == 'access' else set()))
    def fixed(spec, original):
        have, want = _node(spec, name)['switchports'].get(port), _node(original, name)['switchports'].get(port)
        same = have == want or (have and want and have['mode'] == want['mode'] == 'trunk' and set(want['allowed']) <= set(
            _node(spec, name)['vlans'] if have['allowed'] == 'all' else have['allowed']))
        detail = (f'access VLAN {have["vlan"]}' if have and have['mode'] == 'access' else
                  'trunk ' + ','.join(map(str, have['allowed'])) if have else 'non configuré')
        return bool(same), f'{name} {port} : {detail}'
    return apply, fixed


def _rule(name, rule_name, change, packet):
    def apply(spec):
        policy = _node(spec, name)['firewall']
        if change == 'remove':
            policy['rules'] = [r for r in policy['rules'] if r['name'] != rule_name]
        else:
            next(r for r in policy['rules'] if r['name'] == rule_name)['action'] = 'drop'
    def fixed(spec, original):
        from .missions import evaluate_policy
        have, want = evaluate_policy(_node(spec, name), packet), evaluate_policy(_node(original, name), packet)
        return have == want, f'politique de {name} : flux {"autorisé" if have == "accept" else "bloqué"}'
    return apply, fixed


def _vip(name, vip_name):
    def apply(spec):
        policy = _node(spec, name)['firewall']
        policy['nat'] = [r for r in policy['nat'] if r['name'] != vip_name]
    def fixed(spec, original):
        want = next(r for r in _node(original, name)['firewall']['nat'] if r['name'] == vip_name)
        ok = any(r['type'] == 'dnat' and r.get('in') == want['in'] and r['to'] == want['to'] and r['destination'] == want['destination']
                 for r in _node(spec, name)['firewall']['nat'])
        return ok, 'publication du serveur ' + ('présente' if ok else 'absente')
    return apply, fixed


def _ospf_fault(name, change):
    """CHANGE breaks NAME's OSPF; repaired when NAME runs OSPF on the same ports, each active or passive as before."""
    def apply(spec):
        change(_node(spec, name))
    def fixed(spec, original):
        from .native_models import port_names
        from .ospf import enabled_interfaces
        node, before = _node(spec, name), _node(original, name)
        if not node.get('ospf'):
            return False, f'pas d’OSPF sur {name}'
        have = {port: value['passive'] for port, value in enabled_interfaces(node).items()}
        want = {port: value['passive'] for port, value in enabled_interfaces(before).items()}
        shown = port_names(node)
        detail = f'OSPF de {name} : ' + ', '.join(f'{shown.get(p, p)} {"passive" if v else "active"}' for p, v in sorted(have.items()))
        return have == want, detail
    return apply, fixed


def _passive(port):
    def change(node):
        node['ospf']['interfaces'][port]['passive'] = True
    return change


def _unadvertise(port):
    def change(node):
        network = str(ipaddress.IPv4Interface(node['interfaces'][port]).network)
        node['ospf']['networks'] = [n for n in node['ospf']['networks'] if n != network]
        node['ospf']['interfaces'].pop(port)
    return change


def _no_ospf(node):
    node['ospf'] = None


INBOUND = {'in': 'eth1', 'source': '198.51.100.20', 'destination': '198.51.100.1', 'protocol': 'icmp'}
OUTBOUND = {'in': 'eth0', 'source': '192.0.2.20', 'destination': '198.51.100.20', 'protocol': 'icmp'}
FAULTS = {
    'routeurs': {
        'r1-route': (_drop_route('R1'), 'Le site A ne joint plus le site B.', 'R1 a perdu sa route vers 198.51.100.0/24.'),
        'r2-route': (_drop_route('R2'), 'Le site B ne joint plus le site A.', 'R2 a perdu sa route vers 192.0.2.0/24.'),
        'r2-address': (_address('R2', 'eth1', '198.51.100.129/25'), 'Le serveur VM3 ne répond plus au site A.',
                       'R2 a l’adresse 198.51.100.129/25 sur xe-0/0/1 au lieu de 198.51.100.1/24 : VM3 perd sa passerelle.'),
        'vm2-gateway': (_gateway('VM2', '192.0.2.254'), 'VM2 joint son routeur mais plus le site B.',
                        'La passerelle de VM2 est 192.0.2.254 au lieu de 192.0.2.1.'),
    },
    'vlans': {
        'vm2-vlan': (_switchport('SW1', 'eth1', {'mode': 'access', 'vlan': 20}), 'VM1 ne joint plus son voisin VM2.',
                     'Le port de VM2 (gi1/0/2) est passé en VLAN 20.'),
        'trunk': (_switchport('SW1', 'eth3', {'mode': 'trunk', 'native_vlan': 1, 'allowed': [20]}),
                  'Les utilisateurs du VLAN 10 ne se joignent plus d’un switch à l’autre.',
                  'Le trunk gi1/0/4 ne porte plus le VLAN 10.'),
        'vm3-vlan': (_switchport('SW1', 'eth2', {'mode': 'access', 'vlan': 10}),
                     'La comptabilité (VM3) est joignable par tous les utilisateurs.',
                     'Le port de VM3 (gi1/0/3) est en VLAN 10 au lieu de 20.'),
    },
    'ospf': {
        'r1-off': (_ospf_fault('R1', _no_ospf), 'Le site de VM2 ne joint plus rien au-delà de R1.',
                   'OSPF a été retiré de R1 (router ospf 1 absent).'),
        'r2-passive': (_ospf_fault('R2', _passive('eth1')), 'R1 et R2 se voient, mais VM3 est injoignable.',
                       'Sur R2, xe-0/0/1 (vers R3) est passive : aucun voisin OSPF avec R3.'),
        'r3-lan': (_ospf_fault('R3', _unadvertise('eth1')), 'Les trois routeurs sont voisins, mais le LAN de VM3 est inconnu.',
                   'R3 n’annonce plus son LAN 198.51.100.0/24 (network absent).'),
    },
    'pare-feu': {
        'outbound-rule': (_rule('FW1', 'inside-ping-out', 'remove', OUTBOUND), 'Le LAN ne sort plus vers l’extérieur.',
                          'La politique inside-ping-out a été supprimée.'),
        'inbound-deny': (_rule('FW1', 'published-ping-in', 'deny', INBOUND), 'Le serveur publié ne répond plus depuis l’extérieur.',
                         'La politique published-ping-in est passée en DENY.'),
        'vip': (_vip('FW1', 'publish-vm2'), 'Le serveur publié ne répond plus depuis l’extérieur.',
                'La Virtual IP publish-vm2 a été supprimée.'),
    },
}


def create(lab_key, kernel, disk, seed=None):
    """A working lab with one random fault: {'lab', 'fault', 'symptom', 'answer', 'spec', 'original'}."""
    if lab_key not in LABS:
        raise ValueError('Lab de panne inconnu : ' + str(lab_key))
    original = LABS[lab_key]['build'](kernel, disk)
    fault = random.Random(seed).choice(sorted(FAULTS[lab_key]))
    (apply, _), symptom, answer = FAULTS[lab_key][fault][0], FAULTS[lab_key][fault][1], FAULTS[lab_key][fault][2]
    broken = copy.deepcopy(original)
    apply(broken)
    return {'lab': lab_key, 'fault': fault, 'symptom': symptom, 'answer': answer, 'spec': validate(broken), 'original': original}


def mission_for(lab_key):
    """The health probes of a lab as a mission, for the privileged 'mission' request ('panne-<lab>')."""
    item = LABS[lab_key]
    return {'id': 'panne-' + lab_key, 'lab': 'panne-' + lab_key, 'checks': item['probes']}


def grade(spec, panne, real=None):
    """The fault's repair check, then the lab's health probes (real results from run_real, {index: (ok, detail)})."""
    _, fixed = FAULTS[panne['lab']][panne['fault']][0]
    try:
        ok, detail = fixed(spec, panne['original'])
    except (ValueError, KeyError, StopIteration) as error:
        ok, detail = False, str(error)
    # The repaired item is only named once repaired: before that, saying what is wrong would give the answer away.
    shown = detail if ok else 'pas encore réparée : chercher la cause (Indice pour de l’aide)'
    results = [{'text': 'La panne est réparée', 'kind': 'configuration', 'status': 'ok' if ok else 'fail', 'detail': shown}]
    for index, probe in enumerate(LABS[panne['lab']]['probes']):
        if real and index in real:
            passed, detail = real[index]
            results.append({'text': probe['text'], 'kind': 'réel', 'status': 'ok' if passed else 'fail', 'detail': detail})
        else:
            results.append({'text': probe['text'], 'kind': 'réel', 'status': 'pending',
                            'detail': 'lab à démarrer puis « Tester sur le lab »'})
    passed = sum(r['status'] == 'ok' for r in results)
    return {'mission': 'panne-' + panne['lab'], 'results': results, 'passed': passed, 'total': len(results),
            'solved': passed == len(results)}
