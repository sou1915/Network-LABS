"""The commands each node's terminal accepts, as a catalogue to browse: syntax, what it does, an example.

One catalogue per vendor syntax (Cisco IOS, Arista EOS, Huawei VRP, Junos, PAN-OS, FortiOS, RouterOS) and one for
the BusyBox shell of hosts and generic Linux nodes. Each entry says in which mode it is typed, for which roles it
exists (router, switch, firewall), and gives an example written with the node's own port names. The tests run every
example through the same parser the terminal uses, and every show command through the same show code, so the
catalogue lists only what really works.

Entry: (topic, mode, syntax, help, example lines, roles). Roles: 'R' router, 'S' switch, 'F' firewall.
Example lines use {p0}, {p1}, {p2}: the node's first ports as its vendor names them, and {name}: the node's name.
"""
import ipaddress
import re

from . import vendor_config, vendor_show

ROUTER, SWITCH, FIREWALL = 'R', 'S', 'F'
ALL = 'RSF'

# How each mode is reached, shown above the commands of that mode.
MODES = {
    'ios': {'exec': 'au démarrage (R1>) ; « enable » donne R1#', 'config': 'configure terminal (depuis R1#)',
            'config-if': 'interface PORT (depuis config)', 'config-subif': 'interface PORT.N (depuis config)',
            'config-router': 'router ospf N ou router bgp AS (depuis config)',
            'config-ext-nacl': 'ip access-list extended NOM (depuis config)', 'dhcp-config': 'ip dhcp pool NOM (depuis config)'},
    'vrp': {'user': 'au démarrage (<R1>)', 'system': 'system-view (depuis <R1>)', 'interface': 'interface PORT (depuis system)',
            'ospf': 'ospf N (depuis system)', 'ospf-area': 'area 0 (depuis ospf)', 'bgp': 'bgp AS (depuis system)',
            'bgp-af-ipv4': 'ipv4-family unicast (depuis bgp)'},
    'junos': {'operational': 'au démarrage (admin@R1>)', 'configuration': 'configure (puis commit pour appliquer)'},
    'panos': {'operational': 'au démarrage (admin@FW1>)', 'configuration': 'configure (puis commit pour appliquer)'},
    'fortios': {'exec': 'au démarrage (FW1 #)', 'config': 'config SECTION … end (appliqué à « end »)'},
    'routeros': {'exec': 'au démarrage ([admin@R1] >)', 'config': 'chaque ligne /menu … est appliquée aussitôt'},
    'shell': {'shell': 'au démarrage (root@VM1:~#)'},
}
MODES['eos'] = MODES['ios']

_IOS_COMMON = [
    ('Modes', 'exec', 'enable', 'Passer en mode privilégié (R1#).', ['enable'], ALL),
    ('Modes', 'exec', 'disable', 'Revenir au mode utilisateur (R1>).', ['disable'], ALL),
    ('Modes', 'exec', 'configure terminal', 'Entrer en configuration (depuis R1#). Les lignes sont appliquées au nœud en marche à « end ».',
     ['configure terminal'], ALL),
    ('Modes', 'config', 'end', 'Quitter la configuration et appliquer les lignes tapées au nœud en marche.', ['end'], ALL),
    ('Modes', 'config', 'exit', 'Sortir du sous-mode (interface, router, …) vers config.', ['exit'], ALL),
    ('Vérification', 'exec', 'show running-config', 'La configuration courante, dans la syntaxe du constructeur.',
     ['show running-config'], ALL),
    ('Vérification', 'exec', 'show ip interface brief', 'Les ports, leur adresse et leur état, lus dans la micro-VM.',
     ['show ip interface brief'], ALL),
    ('Vérification', 'exec', 'show ip route', 'La table de routage réelle (C, L, S, O, B).', ['show ip route'], ALL),
    ('Vérification', 'exec', 'ping A.B.C.D', 'Envoyer 5 échos ICMP depuis ce nœud (!!!!! = réponses).', ['ping {gw}'], ALL),
    ('Système', 'config', 'hostname NOM', 'Nom de l’équipement (il doit rester celui du lab).', ['hostname {name}'], ALL),
    ('Interfaces', 'config', 'interface PORT', 'Configurer un port (mode config-if).', ['interface {p0}'], ALL),
    ('Interfaces', 'config-if', 'description TEXTE', 'Commentaire sur le port.', ['interface {p0}', 'description vers-LAN'], ALL),
    ('Routage statique', 'config', 'no ip route RÉSEAU MASQUE', 'Supprimer une route statique.',
     ['ip route 10.99.0.0 255.255.0.0 {gw}', 'no ip route 10.99.0.0 255.255.0.0'], 'R'),
]
_IOS_L3 = [
    ('Interfaces', 'config-if', 'ip address A.B.C.D MASQUE', 'Adresse IPv4 du port.',
     ['interface {p0}', 'ip address {ip0} {mask0}'], 'RF'),
    ('Interfaces', 'config', 'interface PORT.N', 'Sous-interface 802.1Q (routeur sur un lien, inter-VLAN).',
     ['interface {p2}.10', 'encapsulation dot1Q 10', 'ip address 10.10.0.1 255.255.255.0'], 'RF'),
    ('Interfaces', 'config-subif', 'encapsulation dot1Q VLAN', 'Le VLAN que porte la sous-interface.',
     ['interface {p2}.20', 'encapsulation dot1Q 20', 'ip address 10.20.0.1 255.255.255.0'], 'RF'),
    ('Routage statique', 'config', 'ip route RÉSEAU MASQUE PASSERELLE', 'Route statique (0.0.0.0 0.0.0.0 pour la route par défaut).',
     ['ip route 10.99.0.0 255.255.0.0 {gw}'], 'RF'),
    ('DHCP', 'config', 'ip dhcp excluded-address A.B.C.D [A.B.C.D]', 'Adresses que le serveur DHCP ne distribue pas.',
     ['ip dhcp excluded-address {ip0}', 'ip dhcp pool LAN', 'network {net0} {mask0}'], 'RF'),
    ('DHCP', 'config', 'ip dhcp pool NOM', 'Serveur DHCP sur le réseau d’un port (mode dhcp-config).',
     ['ip dhcp pool LAN', 'network {net0} {mask0}', 'default-router {ip0}'], 'RF'),
    ('DHCP', 'dhcp-config', 'network RÉSEAU MASQUE', 'Le réseau distribué : celui d’un port du routeur.',
     ['ip dhcp pool LAN', 'network {net0} {mask0}'], 'RF'),
    ('DHCP', 'dhcp-config', 'default-router A.B.C.D', 'La passerelle donnée aux clients.',
     ['ip dhcp pool LAN', 'network {net0} {mask0}', 'default-router {ip0}'], 'RF'),
    ('DHCP', 'dhcp-config', 'dns-server A.B.C.D [A.B.C.D]', 'Les serveurs DNS donnés aux clients.',
     ['ip dhcp pool LAN', 'network {net0} {mask0}', 'dns-server {h0b}'], 'RF'),
    ('DHCP', 'dhcp-config', 'lease JOURS [HEURES [MINUTES]]', 'Durée du bail.',
     ['ip dhcp pool LAN', 'network {net0} {mask0}', 'lease 0 2'], 'RF'),
    ('DHCP', 'config', 'no ip dhcp pool NOM', 'Arrêter le serveur DHCP.', ['no ip dhcp pool LAN'], 'RF'),
]
_IOS_OSPF = [
    ('OSPF', 'exec', 'show ip ospf neighbor', 'Les voisins OSPF et l’état des adjacences (FULL).', ['show ip ospf neighbor'], 'R'),
    ('OSPF', 'config', 'router ospf N', 'Démarrer OSPF (zone 0) ; mode config-router. Retirer d’abord les routes statiques : '
     'OSPF apprend les routes.', ['router ospf 1', 'network {net1} {wild1} area 0'], 'R'),
    ('OSPF', 'config-router', 'router-id A.B.C.D', 'Identifiant OSPF du routeur.',
     ['router ospf 1', 'network {net1} {wild1} area 0', 'router-id 1.1.1.1'], 'R'),
    ('OSPF', 'config-router', 'network A.B.C.D JOKER area 0', 'Activer OSPF sur les ports de ce réseau (masque joker).',
     ['router ospf 1', 'network {net1} {wild1} area 0'], 'R'),
    ('OSPF', 'config-router', 'passive-interface PORT', 'Annoncer le réseau du port sans y former de voisinage.',
     ['router ospf 1', 'network {net0} {wild0} area 0', 'network {net1} {wild1} area 0', 'passive-interface {p0}'], 'R'),
    ('OSPF', 'config-if', 'ip ospf cost N', 'Coût OSPF du port (1..65535).',
     ['router ospf 1', 'network {net1} {wild1} area 0', 'interface {p1}', 'ip ospf cost 50'], 'R'),
    ('OSPF', 'config-if', 'ip ospf network point-to-point|broadcast', 'Type de réseau OSPF du port.',
     ['router ospf 1', 'network {net1} {wild1} area 0', 'interface {p1}', 'ip ospf network broadcast'], 'R'),
    ('OSPF', 'config-if', 'ip ospf priority N', 'Priorité pour l’élection du DR (réseau broadcast).',
     ['router ospf 1', 'network {net1} {wild1} area 0', 'interface {p1}', 'ip ospf network broadcast', 'ip ospf priority 10'], 'R'),
    ('OSPF', 'config', 'no router ospf N', 'Arrêter OSPF.', ['no router ospf 1'], 'R'),
]
_IOS_BGP = [
    ('BGP', 'exec', 'show ip bgp summary', 'Les voisins BGP, leur AS et l’état des sessions.', ['show ip bgp summary'], 'R'),
    ('BGP', 'exec', 'show ip bgp', 'La table BGP : réseaux, prochain saut, chemin d’AS.', ['show ip bgp'], 'R'),
    ('BGP', 'config', 'router bgp AS', 'Démarrer BGP dans cet AS ; mode config-router (il faut au moins un voisin).',
     ['router bgp 65001', 'neighbor {gw} remote-as 65002'], 'R'),
    ('BGP', 'config-router', 'bgp router-id A.B.C.D', 'Identifiant BGP du routeur.',
     ['router bgp 65001', 'neighbor {gw} remote-as 65002', 'bgp router-id 1.1.1.1'], 'R'),
    ('BGP', 'config-router', 'neighbor A.B.C.D remote-as AS', 'Voisin eBGP (directement connecté, autre AS).',
     ['router bgp 65001', 'neighbor {gw} remote-as 65002'], 'R'),
    ('BGP', 'config-router', 'no neighbor A.B.C.D', 'Supprimer un voisin.',
     ['router bgp 65001', 'neighbor {gw} remote-as 65002', 'neighbor {peer0} remote-as 65010', 'no neighbor {peer0}'], 'R'),
    ('BGP', 'config', 'no router bgp AS', 'Arrêter BGP.', ['no router bgp 65001'], 'R'),
]
_IOS_ACL = [
    ('ACL', 'exec', 'show access-lists', 'Les listes d’accès et leurs entrées.', ['show access-lists'], 'R'),
    ('ACL', 'config', 'ip access-list extended NOM', 'Créer une liste d’accès étendue (mode config-ext-nacl).',
     ['ip access-list extended INVITES'], 'R'),
    ('ACL', 'config-ext-nacl', '[SEQ] permit|deny ip|icmp|tcp|udp SOURCE DESTINATION [eq PORT]',
     'Une entrée : any, host A.B.C.D ou A.B.C.D JOKER ; la fin de la liste refuse tout.',
     ['ip access-list extended INVITES', 'deny tcp {net0} {wild0} host 198.51.100.10 eq 22', 'permit ip any any'], 'R'),
    ('ACL', 'config-ext-nacl', 'remark TEXTE', 'Commentaire dans la liste.', ['ip access-list extended INVITES', 'remark invites'], 'R'),
    ('ACL', 'config-ext-nacl', 'no SEQ', 'Supprimer l’entrée de ce numéro.',
     ['ip access-list extended INVITES', 'permit icmp any any', 'permit ip any any', 'no 10'], 'R'),
    ('ACL', 'config-if', 'ip access-group NOM in', 'Appliquer la liste en entrée du port.',
     ['ip access-list extended INVITES', 'permit ip any any', 'interface {p0}', 'ip access-group INVITES in'], 'R'),
    ('ACL', 'config', 'no ip access-list extended NOM', 'Supprimer la liste (et ses applications).',
     ['ip access-list extended INVITES', 'permit ip any any', 'no ip access-list extended INVITES'], 'R'),
]
_IOS_SWITCH = [
    ('VLAN', 'exec', 'show vlan brief', 'Les VLAN et leurs ports d’accès.', ['show vlan brief'], 'S'),
    ('VLAN', 'config', 'vlan N', 'Créer le VLAN N.', ['vlan 30'], 'S'),
    ('VLAN', 'config', 'no vlan N', 'Supprimer le VLAN N.', ['vlan 30', 'no vlan 30'], 'S'),
    ('VLAN', 'config-if', 'switchport mode access|trunk', 'Port d’accès (un VLAN) ou trunk 802.1Q.',
     ['interface {p2}', 'switchport mode trunk'], 'S'),
    ('VLAN', 'config-if', 'switchport access vlan N', 'Le VLAN d’un port d’accès.', ['interface {p0}', 'switchport access vlan 20'], 'S'),
    ('VLAN', 'config-if', 'switchport trunk native vlan N', 'Le VLAN natif (non étiqueté) du trunk.',
     ['interface {p2}', 'switchport mode trunk', 'switchport trunk native vlan 10'], 'S'),
    ('VLAN', 'config-if', 'switchport trunk allowed vlan LISTE|all', 'Les VLAN portés par le trunk (10,20 ou 10-20).',
     ['interface {p2}', 'switchport mode trunk', 'switchport trunk allowed vlan 10,20'], 'S'),
]


def _eos(entries):
    """EOS entries from IOS ones: prefix-length forms where EOS uses them, 'show vlan'; no access lists and no IOS DHCP pools."""
    replace = [('ip address {ip0} {mask0}', 'ip address {ip0}/{len0}'),
               ('ip address 10.10.0.1 255.255.255.0', 'ip address 10.10.0.1/24'),
               ('ip address A.B.C.D MASQUE', 'ip address A.B.C.D/N'),
               ('ip route 10.99.0.0 255.255.0.0 {gw}', 'ip route 10.99.0.0/16 {gw}'),
               ('ip route RÉSEAU MASQUE PASSERELLE', 'ip route RÉSEAU/N PASSERELLE'),
               ('no ip route 10.99.0.0 255.255.0.0', 'no ip route 10.99.0.0/16'),
               ('no ip route RÉSEAU MASQUE', 'no ip route RÉSEAU/N'),
               ('ip address 10.20.0.1 255.255.255.0', 'ip address 10.20.0.1/24'),
               ('network {net1} {wild1} area 0', 'network {net1}/{len1} area 0.0.0.0'),
               ('network {net0} {wild0} area 0', 'network {net0}/{len0} area 0.0.0.0'),
               ('show vlan brief', 'show vlan')]
    result = []
    for topic, mode, syntax, text, example, roles in entries:
        if topic in ('ACL', 'DHCP'):
            continue
        for old, new in replace:
            syntax = syntax.replace(old, new)
            example = [line.replace(old, new) for line in example]
        result.append((topic, mode, syntax, text, example, roles))
    return result


_IOS_BGP_NETWORK = [('BGP', 'config-router', 'network A.B.C.D mask MASQUE',
                     'Annoncer ce réseau (il doit être dans la table de routage, à l’identique).',
                     ['router bgp 65001', 'neighbor {gw} remote-as 65002', 'network {net0} mask {mask0}'], 'R'),
                    ('BGP', 'config-router', 'no network A.B.C.D mask MASQUE', 'Ne plus annoncer ce réseau.',
                     ['router bgp 65001', 'neighbor {gw} remote-as 65002', 'network {net0} mask {mask0}',
                      'no network {net0} mask {mask0}'], 'R')]
_EOS_BGP_NETWORK = [('BGP', 'config-router', 'network A.B.C.D/N', 'Annoncer ce réseau (présent à l’identique dans la table).',
                     ['router bgp 65001', 'neighbor {gw} remote-as 65002', 'network {net0}/{len0}'], 'R')]
_EOS_OSPF_NETWORK = [('OSPF', 'config-router', 'network A.B.C.D/N area 0.0.0.0', 'Activer OSPF sur les ports de ce réseau.',
                      ['router ospf 1', 'network {net1}/{len1} area 0.0.0.0'], 'R')]

CATALOGUES = {
    'ios': _IOS_COMMON + _IOS_L3 + _IOS_OSPF + _IOS_BGP + _IOS_BGP_NETWORK + _IOS_ACL + _IOS_SWITCH,
    'eos': _eos(_IOS_COMMON + _IOS_L3 + [e for e in _IOS_OSPF if 'JOKER' not in e[2]] + _EOS_OSPF_NETWORK + _IOS_BGP
                + _EOS_BGP_NETWORK + _IOS_SWITCH),
    'vrp': [
        ('Modes', 'user', 'system-view', 'Entrer en configuration ([R1]). Les lignes sont appliquées à « return ».', ['system-view'], ALL),
        ('Modes', 'system', 'return', 'Quitter la configuration et appliquer les lignes tapées au nœud en marche.', ['return'], ALL),
        ('Modes', 'system', 'quit', 'Remonter d’un niveau (interface, ospf, bgp…).', ['quit'], ALL),
        ('Vérification', 'user', 'display current-configuration', 'La configuration courante (syntaxe VRP).',
         ['display current-configuration'], ALL),
        ('Vérification', 'user', 'display ip interface brief', 'Les ports, leur adresse et leur état.',
         ['display ip interface brief'], ALL),
        ('Vérification', 'user', 'display ip routing-table', 'La table de routage réelle.', ['display ip routing-table'], ALL),
        ('Vérification', 'user', 'ping A.B.C.D', 'Envoyer des échos ICMP depuis ce nœud.', ['ping {gw}'], ALL),
        ('Système', 'system', 'sysname NOM', 'Nom de l’équipement (il doit rester celui du lab).', ['sysname {name}'], ALL),
        ('Interfaces', 'system', 'interface PORT', 'Configurer un port.', ['interface {p0}'], ALL),
        ('Interfaces', 'interface', 'ip address A.B.C.D MASQUE', 'Adresse IPv4 du port.',
         ['interface {p0}', 'ip address {ip0} {mask0}'], 'R'),
        ('Interfaces', 'interface', 'description TEXTE', 'Commentaire sur le port.', ['interface {p0}', 'description vers-LAN'], ALL),
        ('Routage statique', 'system', 'ip route-static RÉSEAU MASQUE PASSERELLE', 'Route statique.',
         ['ip route-static 10.99.0.0 255.255.0.0 {gw}'], 'R'),
        ('Routage statique', 'system', 'undo ip route-static RÉSEAU MASQUE', 'Supprimer une route statique.',
         ['ip route-static 10.99.0.0 255.255.0.0 {gw}', 'undo ip route-static 10.99.0.0 255.255.0.0'], 'R'),
        ('OSPF', 'user', 'display ospf peer brief', 'Les voisins OSPF.', ['display ospf peer brief'], 'R'),
        ('OSPF', 'system', 'ospf N [router-id A.B.C.D]', 'Démarrer OSPF (mode ospf). Retirer d’abord les routes statiques.',
         ['ospf 1 router-id 1.1.1.1', 'area 0', 'network {net1} {wild1}'], 'R'),
        ('OSPF', 'ospf', 'area 0', 'La zone 0 (seule zone du lab).', ['ospf 1 router-id 1.1.1.1', 'area 0', 'network {net1} {wild1}'], 'R'),
        ('OSPF', 'ospf-area', 'network A.B.C.D JOKER', 'Activer OSPF sur les ports de ce réseau.',
         ['ospf 1 router-id 1.1.1.1', 'area 0', 'network {net1} {wild1}'], 'R'),
        ('OSPF', 'ospf', 'silent-interface PORT', 'Annoncer le port sans voisinage.',
         ['ospf 1 router-id 1.1.1.1', 'area 0', 'network {net0} {wild0}', 'network {net1} {wild1}', 'quit',
          'silent-interface {p0}'], 'R'),
        ('OSPF', 'interface', 'ospf cost N', 'Coût OSPF du port.',
         ['ospf 1 router-id 1.1.1.1', 'area 0', 'network {net1} {wild1}', 'quit', 'quit', 'interface {p1}', 'ospf cost 50'], 'R'),
        ('OSPF', 'interface', 'ospf network-type p2p|broadcast', 'Type de réseau OSPF du port.',
         ['ospf 1 router-id 1.1.1.1', 'area 0', 'network {net1} {wild1}', 'quit', 'quit', 'interface {p1}',
          'ospf network-type broadcast'], 'R'),
        ('OSPF', 'interface', 'ospf dr-priority N', 'Priorité pour l’élection du DR.',
         ['ospf 1 router-id 1.1.1.1', 'area 0', 'network {net1} {wild1}', 'quit', 'quit', 'interface {p1}',
          'ospf network-type broadcast', 'ospf dr-priority 10'], 'R'),
        ('OSPF', 'system', 'undo ospf N', 'Arrêter OSPF.', ['undo ospf 1'], 'R'),
        ('BGP', 'user', 'display bgp peer', 'Les voisins BGP et l’état des sessions.', ['display bgp peer'], 'R'),
        ('BGP', 'user', 'display bgp routing-table', 'La table BGP.', ['display bgp routing-table'], 'R'),
        ('BGP', 'system', 'bgp AS', 'Démarrer BGP dans cet AS (mode bgp ; il faut au moins un voisin).',
         ['bgp 65001', 'peer {gw} as-number 65002'], 'R'),
        ('BGP', 'bgp', 'router-id A.B.C.D', 'Identifiant BGP.', ['bgp 65001', 'peer {gw} as-number 65002', 'router-id 1.1.1.1'], 'R'),
        ('BGP', 'bgp', 'peer A.B.C.D as-number AS', 'Voisin eBGP (directement connecté, autre AS).',
         ['bgp 65001', 'peer {gw} as-number 65002'], 'R'),
        ('BGP', 'bgp', 'undo peer A.B.C.D', 'Supprimer un voisin.',
         ['bgp 65001', 'peer {gw} as-number 65002', 'peer {peer0} as-number 65010', 'undo peer {peer0}'], 'R'),
        ('BGP', 'bgp', 'ipv4-family unicast', 'Famille IPv4 (mode bgp-af-ipv4).',
         ['bgp 65001', 'peer {gw} as-number 65002', 'ipv4-family unicast'], 'R'),
        ('BGP', 'bgp-af-ipv4', 'network A.B.C.D MASQUE', 'Annoncer ce réseau (présent à l’identique dans la table).',
         ['bgp 65001', 'peer {gw} as-number 65002', 'ipv4-family unicast', 'network {net0} {mask0}'], 'R'),
        ('BGP', 'system', 'undo bgp AS', 'Arrêter BGP.', ['undo bgp 65001'], 'R'),
        ('VLAN', 'user', 'display vlan', 'Les VLAN et leurs ports.', ['display vlan'], 'S'),
        ('VLAN', 'system', 'vlan batch N [N…]', 'Créer des VLAN (10 20 ou 10 to 20).', ['vlan batch 30 40'], 'S'),
        ('VLAN', 'system', 'undo vlan N', 'Supprimer un VLAN.', ['vlan batch 30', 'undo vlan 30'], 'S'),
        ('VLAN', 'interface', 'port link-type access|trunk', 'Port d’accès ou trunk.', ['interface {p2}', 'port link-type trunk'], 'S'),
        ('VLAN', 'interface', 'port default vlan N', 'Le VLAN d’un port d’accès.',
         ['interface {p0}', 'port link-type access', 'port default vlan 20'], 'S'),
        ('VLAN', 'interface', 'port trunk pvid vlan N', 'Le VLAN natif du trunk.',
         ['interface {p2}', 'port link-type trunk', 'port trunk pvid vlan 10'], 'S'),
        ('VLAN', 'interface', 'port trunk allow-pass vlan LISTE|all', 'Les VLAN portés par le trunk (10 20 ou 10 to 20).',
         ['interface {p2}', 'port link-type trunk', 'port trunk allow-pass vlan 10 20'], 'S'),
    ],
    'junos': [
        ('Modes', 'operational', 'configure', 'Entrer en configuration (admin@R1#).', ['configure'], ALL),
        ('Modes', 'configuration', 'commit', 'Appliquer les lignes au nœud en marche.', ['commit'], ALL),
        ('Modes', 'configuration', 'exit', 'Quitter la configuration (les lignes non validées sont abandonnées).', ['exit'], ALL),
        ('Vérification', 'operational', 'show configuration', 'La configuration courante (lignes set).', ['show configuration'], ALL),
        ('Vérification', 'operational', 'show interfaces terse', 'Les ports, leur adresse et leur état.', ['show interfaces terse'], ALL),
        ('Vérification', 'operational', 'show route', 'La table de routage réelle.', ['show route'], ALL),
        ('Vérification', 'operational', 'ping A.B.C.D', 'Envoyer des échos ICMP.', ['ping {gw}'], ALL),
        ('Système', 'configuration', 'set system host-name NOM', 'Nom (il doit rester celui du lab).',
         ['set system host-name {name}'], ALL),
        ('Interfaces', 'configuration', 'set interfaces PORT unit 0 family inet address A.B.C.D/N', 'Adresse IPv4 du port.',
         ['set interfaces {p0} unit 0 family inet address {ip0}/{len0}'], 'RF'),
        ('Routage statique', 'configuration', 'set routing-options static route RÉSEAU/N next-hop A.B.C.D', 'Route statique.',
         ['set routing-options static route 10.99.0.0/16 next-hop {gw}'], 'RF'),
        ('Routage statique', 'configuration', 'delete routing-options static route RÉSEAU/N', 'Supprimer une route statique.',
         ['set routing-options static route 10.99.0.0/16 next-hop {gw}', 'delete routing-options static route 10.99.0.0/16'], 'R'),
        ('Routage', 'configuration', 'set routing-options router-id A.B.C.D', 'Identifiant du routeur (OSPF et BGP).',
         ['set protocols ospf area 0.0.0.0 interface {p1}.0', 'set routing-options router-id 1.1.1.1'], 'R'),
        ('OSPF', 'operational', 'show ospf neighbor', 'Les voisins OSPF.', ['show ospf neighbor'], 'R'),
        ('OSPF', 'configuration', 'set protocols ospf area 0.0.0.0 interface PORT.0', 'Activer OSPF sur le port.',
         ['set protocols ospf area 0.0.0.0 interface {p1}.0'], 'R'),
        ('OSPF', 'configuration', 'set protocols ospf area 0.0.0.0 interface PORT.0 passive', 'Annoncer le port sans voisinage.',
         ['set protocols ospf area 0.0.0.0 interface {p1}.0', 'set protocols ospf area 0.0.0.0 interface {p0}.0 passive'], 'R'),
        ('OSPF', 'configuration', 'set protocols ospf area 0.0.0.0 interface PORT.0 metric N', 'Coût OSPF du port.',
         ['set protocols ospf area 0.0.0.0 interface {p1}.0 metric 50'], 'R'),
        ('OSPF', 'configuration', 'set protocols ospf area 0.0.0.0 interface PORT.0 interface-type p2p', 'Lien point à point.',
         ['set protocols ospf area 0.0.0.0 interface {p1}.0 interface-type p2p'], 'R'),
        ('OSPF', 'configuration', 'set protocols ospf area 0.0.0.0 interface PORT.0 priority N', 'Priorité pour l’élection du DR.',
         ['set protocols ospf area 0.0.0.0 interface {p1}.0 interface-type broadcast',
          'set protocols ospf area 0.0.0.0 interface {p1}.0 priority 10'], 'R'),
        ('OSPF', 'configuration', 'delete protocols ospf', 'Arrêter OSPF.', ['delete protocols ospf'], 'R'),
        ('BGP', 'operational', 'show bgp summary', 'Les voisins BGP et l’état des sessions.', ['show bgp summary'], 'R'),
        ('BGP', 'configuration', 'set routing-options autonomous-system AS', 'Le numéro d’AS du routeur.',
         ['set routing-options autonomous-system 65001', 'set protocols bgp group EBGP type external',
          'set protocols bgp group EBGP neighbor {gw} peer-as 65002'], 'R'),
        ('BGP', 'configuration', 'set protocols bgp group NOM type external', 'Un groupe de voisins eBGP.',
         ['set routing-options autonomous-system 65001', 'set protocols bgp group EBGP type external',
          'set protocols bgp group EBGP neighbor {gw} peer-as 65002'], 'R'),
        ('BGP', 'configuration', 'set protocols bgp group NOM neighbor A.B.C.D peer-as AS', 'Un voisin eBGP et son AS.',
         ['set routing-options autonomous-system 65001', 'set protocols bgp group EBGP neighbor {gw} peer-as 65002'], 'R'),
        ('BGP', 'configuration', 'set protocols bgp group NOM peer-as AS', 'L’AS commun aux voisins du groupe.',
         ['set routing-options autonomous-system 65001', 'set protocols bgp group EBGP peer-as 65002',
          'set protocols bgp group EBGP neighbor {gw}'], 'R'),
        ('BGP', 'configuration', 'set protocols bgp group NOM export POLITIQUE', 'Annoncer ce que la politique accepte.',
         ['set routing-options autonomous-system 65001', 'set protocols bgp group EBGP neighbor {gw} peer-as 65002',
          'set policy-options policy-statement LAN term 1 from route-filter {net0}/{len0} exact',
          'set policy-options policy-statement LAN term 1 then accept', 'set protocols bgp group EBGP export LAN'], 'R'),
        ('BGP', 'configuration', 'set policy-options policy-statement NOM term T from route-filter RÉSEAU/N exact',
         'Le réseau qu’une politique d’export annonce (présent à l’identique dans la table).',
         ['set routing-options autonomous-system 65001', 'set protocols bgp group EBGP neighbor {gw} peer-as 65002',
          'set policy-options policy-statement LAN term 1 from route-filter {net0}/{len0} exact',
          'set policy-options policy-statement LAN term 1 then accept', 'set protocols bgp group EBGP export LAN'], 'R'),
        ('BGP', 'configuration', 'set policy-options policy-statement NOM term T then accept', 'Accepter ce que le terme sélectionne.',
         ['set routing-options autonomous-system 65001', 'set protocols bgp group EBGP neighbor {gw} peer-as 65002',
          'set policy-options policy-statement LAN term 1 from route-filter {net0}/{len0} exact',
          'set policy-options policy-statement LAN term 1 then accept', 'set protocols bgp group EBGP export LAN'], 'R'),
        ('BGP', 'configuration', 'delete protocols bgp', 'Arrêter BGP.', ['delete protocols bgp'], 'R'),
    ],
    'panos': [
        ('Modes', 'operational', 'configure', 'Entrer en configuration (admin@FW1#).', ['configure'], 'F'),
        ('Modes', 'configuration', 'commit', 'Appliquer les lignes au nœud en marche.', ['commit'], 'F'),
        ('Modes', 'configuration', 'exit', 'Quitter (les lignes non validées sont abandonnées).', ['exit'], 'F'),
        ('Vérification', 'operational', 'show config running', 'La configuration courante (lignes set).', ['show config running'], 'F'),
        ('Vérification', 'operational', 'show interface all', 'Les ports et leur adresse.', ['show interface all'], 'F'),
        ('Vérification', 'operational', 'show routing route', 'La table de routage réelle.', ['show routing route'], 'F'),
        ('Vérification', 'operational', 'ping host A.B.C.D', 'Envoyer des échos ICMP.', ['ping host {gw}'], 'F'),
        ('Système', 'configuration', 'set deviceconfig system hostname NOM', 'Nom (il doit rester celui du lab).',
         ['set deviceconfig system hostname {name}'], 'F'),
        ('Interfaces', 'configuration', 'set network interface ethernet PORT layer3 ip A.B.C.D/N', 'Adresse IPv4 du port.',
         ['set network interface ethernet {p0} layer3 ip {ip0}/{len0}'], 'F'),
        ('Zones', 'configuration', 'set zone NOM network layer3 PORT', 'Une zone de sécurité (un port par zone).',
         ['set zone inside network layer3 {p0}', 'set zone outside network layer3 {p1}'], 'F'),
        ('Routage statique', 'configuration',
         'set network virtual-router default routing-table ip static-route NOM destination RÉSEAU/N nexthop ip-address A.B.C.D',
         'Route statique.', ['set network virtual-router default routing-table ip static-route vers-lab destination 10.99.0.0/16 '
                             'nexthop ip-address {gw}'], 'F'),
        ('Politique', 'configuration', 'set rulebase security rules NOM from ZONE to ZONE source any destination any '
         'application any service any|service-http|service-https|tcp-N|udp-N action allow|deny',
         'Une règle de sécurité (évaluées dans l’ordre, refus par défaut).',
         ['set zone inside network layer3 {p0}', 'set zone outside network layer3 {p1}',
          'set rulebase security rules web from inside to outside source any destination any application any '
          'service service-http action allow'], 'F'),
        ('Politique', 'configuration', 'delete rulebase security rules NOM', 'Supprimer une règle.',
         ['set zone inside network layer3 {p0}', 'set zone outside network layer3 {p1}',
          'set rulebase security rules web from inside to outside source any destination any application any '
          'service service-http action allow', 'delete rulebase security rules web'], 'F'),
    ],
    'fortios': [
        ('Vérification', 'exec', 'show full-configuration', 'La configuration courante (blocs config … end).',
         ['show full-configuration'], 'F'),
        ('Vérification', 'exec', 'get system interface', 'Les ports et leur adresse.', ['get system interface'], 'F'),
        ('Vérification', 'exec', 'get router info routing-table all', 'La table de routage réelle.',
         ['get router info routing-table all'], 'F'),
        ('Vérification', 'exec', 'execute ping A.B.C.D', 'Envoyer des échos ICMP.', ['execute ping {gw}'], 'F'),
        ('Système', 'config', 'config system global / set hostname NOM / end', 'Nom (il doit rester celui du lab).',
         ['config system global', 'set hostname {name}', 'end'], 'F'),
        ('Interfaces', 'config', 'config system interface / edit PORT / set ip A.B.C.D MASQUE / next / end', 'Adresse IPv4 du port.',
         ['config system interface', 'edit {p0}', 'set ip {ip0} {mask0}', 'next', 'end'], 'F'),
        ('Routage statique', 'config', 'config router static / edit N / set dst RÉSEAU MASQUE / set gateway A.B.C.D / '
         'set device PORT / next / end', 'Route statique.',
         ['config router static', 'edit 1', 'set dst 10.99.0.0 255.255.0.0', 'set gateway {gw}', 'set device {p1}',
          'next', 'end'], 'F'),
        ('Politique', 'config', 'config firewall policy / edit N / set srcintf / set dstintf / set srcaddr / set dstaddr / '
         'set action accept|deny / set service / set schedule always / [set nat enable] / next / end',
         'Une politique de sécurité (dans l’ordre, refus par défaut) ; nat enable masque la source.',
         ['config firewall policy', 'edit 3', 'set name web', 'set srcintf {p0}', 'set dstintf {p1}', 'set srcaddr all',
          'set dstaddr all', 'set action accept', 'set service HTTP', 'set schedule always', 'set nat enable', 'next', 'end'], 'F'),
        ('Politique', 'config', 'config firewall policy / delete N / end', 'Supprimer une politique.',
         ['config firewall policy', 'delete 1', 'end'], 'F'),
        ('NAT', 'config', 'config firewall vip / edit NOM / set extip / set mappedip / set extintf / [set portforward enable / '
         'set protocol tcp / set extport / set mappedport] / next / end', 'Une Virtual IP : NAT de destination (publication).',
         ['config firewall vip', 'edit web', 'set extip {ip1}', 'set mappedip {h0a}', 'set extintf {p1}',
          'set portforward enable', 'set protocol tcp', 'set extport 8080', 'set mappedport 80', 'next', 'end'], 'F'),
        ('DHCP', 'config', 'config system dhcp server / edit 1 / set interface / set default-gateway / set netmask / '
         'set dns-server1 / config ip-range / edit 1 / set start-ip / set end-ip / next / end / next / end',
         'Serveur DHCP sur un port (un seul serveur).',
         ['config system dhcp server', 'edit 1', 'set interface {p0}', 'set default-gateway {ip0}', 'set netmask {mask0}',
          'set dns-server1 {h0b}', 'config ip-range', 'edit 1', 'set start-ip {h0a}', 'set end-ip {h0b}', 'next',
          'end', 'next', 'end'], 'F'),
    ],
    'routeros': [
        ('Vérification', 'exec', '/export', 'La configuration courante.', ['/export'], 'RS'),
        ('Vérification', 'exec', '/interface print', 'Les ports et leur état.', ['/interface print'], 'RS'),
        ('Vérification', 'exec', '/ip address print', 'Les adresses des ports.', ['/ip address print'], 'RS'),
        ('Vérification', 'exec', '/ip route print', 'La table de routage réelle.', ['/ip route print'], 'RS'),
        ('Vérification', 'exec', '/ping A.B.C.D', 'Envoyer des échos ICMP.', ['/ping {gw}'], 'RS'),
        ('Système', 'config', '/system identity set name=NOM', 'Nom (il doit rester celui du lab).',
         ['/system identity set name={name}'], 'RS'),
        ('Interfaces', 'config', '/ip address add address=A.B.C.D/N interface=PORT', 'Adresse IPv4 du port (appliquée aussitôt).',
         ['/ip address add address={ip0}/{len0} interface={p0}'], 'R'),
        ('Routage statique', 'config', '/ip route add dst-address=RÉSEAU/N gateway=A.B.C.D', 'Route statique.',
         ['/ip route add dst-address=10.99.0.0/16 gateway={gw}'], 'R'),
        ('Routage statique', 'config', '/ip route remove [find dst-address=RÉSEAU/N]', 'Supprimer une route statique.',
         ['/ip route add dst-address=10.99.0.0/16 gateway={gw}', '/ip route remove [find dst-address=10.99.0.0/16]'], 'R'),
    ],
    'shell': [
        ('Vérification', 'shell', 'ip addr', 'Les ports et leurs adresses (sortie BusyBox).', ['ip addr'], 'H'),
        ('Vérification', 'shell', 'ip route', 'La table de routage du nœud.', ['ip route'], 'H'),
        ('Vérification', 'shell', 'ping A.B.C.D', 'Envoyer 4 échos ICMP.', ['ping {gw}'], 'H'),
        ('Système', 'shell', 'hostname', 'Le nom du nœud.', ['hostname'], 'H'),
        ('Système', 'shell', 'exit', 'Fermer le terminal.', ['exit'], 'H'),
    ],
}

# The prompt suffix and catalogue mode each context-entering line gives, per dialect (line order matters).
CONTEXTS = {
    'ios': [(r'interface \S+\.\d+', 'config-subif'), (r'interface .+', 'config-if'), (r'router (ospf|bgp) \d+', 'config-router'),
            (r'ip access-list extended \S+', 'config-ext-nacl'), (r'ip dhcp pool \S+', 'dhcp-config')],
    'vrp': [(r'interface .+', 'interface'), (r'ospf \d+.*', 'ospf'), (r'area \S+', 'ospf-area'), (r'bgp \d+', 'bgp'),
            (r'ipv4-family( unicast)?', 'bgp-af-ipv4')],
}
CONTEXTS['eos'] = CONTEXTS['ios']
VRP_PARENT = {'ospf-area': 'ospf', 'bgp-af-ipv4': 'bgp', 'interface': 'system', 'ospf': 'system', 'bgp': 'system'}


def syntax_of(node):
    """The catalogue a node uses: its vendor syntax, or 'shell' for hosts and generic Linux nodes."""
    if node.get('role') == 'host':
        return 'shell'
    return vendor_config.dialect(node) or 'shell'


def _role_letter(node):
    return {'router': ROUTER, 'switch': SWITCH, 'firewall': FIREWALL}.get(node.get('role'), 'H')


def entries(node):
    """The node's catalogue: [{'topic', 'mode', 'syntax', 'help', 'example'}], examples with its own port names."""
    syntax = syntax_of(node)
    shown = vendor_config.port_names(node) if syntax != 'shell' else {p: p for p in node.get('interfaces', {})}
    values = placeholders(node, shown)
    letter = _role_letter(node)
    found = []
    for topic, mode, text, explanation, example, roles in CATALOGUES[syntax]:
        if syntax != 'shell' and letter not in roles:
            continue
        found.append({'topic': topic, 'mode': mode, 'syntax': text, 'help': explanation,
                      'example': [line.format(**values) for line in example]})
    return found


def placeholders(node, shown):
    """The values examples are written with: the node's port names, its networks and a next hop on its second port."""
    ports = list(shown.values()) + ['PORT'] * 3
    values = {'p0': ports[0], 'p1': ports[1], 'p2': ports[2], 'name': node.get('name', 'R1')}
    found = [ipaddress.IPv4Interface(a) for a in node.get('interfaces', {}).values() if a and '/' in a]
    first = found[0] if found else ipaddress.IPv4Interface('192.0.2.1/24')
    second = found[1] if len(found) > 1 else (ipaddress.IPv4Interface('203.0.113.1/30') if not found else first)
    for index, interface in ((0, first), (1, second)):
        network = interface.network
        values.update({f'ip{index}': str(interface.ip), f'net{index}': str(network.network_address),
                       f'mask{index}': str(network.netmask), f'wild{index}': str(network.hostmask), f'len{index}': network.prefixlen})
    hosts = lambda network, own: [h for h in network.hosts() if h != own]
    values['gw'] = str((hosts(second.network, second.ip) or [second.ip])[0])
    lan = hosts(first.network, first.ip) or [first.ip]
    values['peer0'] = str(lan[0])
    values['h0a'], values['h0b'] = str(lan[min(99, len(lan) - 1)]), str(lan[min(149, len(lan) - 1)])
    return values


def topics(node):
    seen = []
    for entry in entries(node):
        if entry['topic'] not in seen:
            seen.append(entry['topic'])
    return seen


def search(node, text='', topic=None, mode=None):
    """Entries whose syntax or help contains every word of TEXT (any case), optionally of one topic or mode."""
    words = text.lower().split()
    return [e for e in entries(node) if (topic is None or e['topic'] == topic) and (mode is None or e['mode'] == mode)
            and all(w in (e['syntax'] + ' ' + e['help'] + ' ' + e['topic']).lower() for w in words)]


def context(syntax, line):
    """The catalogue mode a configuration line enters, or None."""
    low = ' '.join(line.split()).lower()
    for pattern, mode in CONTEXTS.get(syntax, []):
        if re.fullmatch(pattern, low):
            return mode
    return None


def _words(syntax):
    """The literal words of a syntax line, up to its first placeholder (A.B.C.D, PORT, NOM…)."""
    literal = []
    for word in syntax.split():
        if word.startswith('[') or any(c.isupper() for c in word) or '|' in word or '/' == word:
            break
        literal.append(word)
    return literal


def help_for(node, mode, typed):
    """Context help, IOS style: the commands of MODE that start with what is TYPED; in a sub-mode with nothing
    matching, those of the modes above it (IOS accepts global commands there and leaves the sub-mode)."""
    syntax = syntax_of(node)
    prefix = ' '.join(typed.split()).lower()

    def matching(modes):
        return [e for e in entries(node) if e['mode'] in modes and (not prefix or e['syntax'].lower().startswith(prefix)
                                                                    or ' '.join(_words(e['syntax'])).startswith(prefix))]
    visible = _modes_visible(syntax, mode)
    own = matching({mode} & visible or visible)
    if syntax in ('ios', 'eos', 'vrp') and mode not in ('exec', 'user'):
        return own or matching(visible)
    return matching(visible)


def global_command(node, low):
    """True when LOW starts like a command of the global configuration mode (IOS leaves a sub-mode for it)."""
    for entry in entries(node):
        words = ' '.join(_words(entry['syntax'])).lower()
        if entry['mode'] == 'config' and words and (low == words or low.startswith(words + ' ')):
            return True
    return False


def _modes_visible(syntax, mode):
    """Modes whose commands make sense at MODE: the mode itself, and for exec modes the show and ping commands."""
    if syntax in ('ios', 'eos'):
        sub_mode = mode.startswith('config-') or mode == 'dhcp-config'
        return {mode} | ({'exec'} if mode in ('exec', 'enable') else set()) | ({'config'} if sub_mode else set())
    if syntax == 'vrp':
        return {mode, 'system'} if mode != 'user' else {'user'}
    if syntax == 'routeros':
        return {'exec', 'config'}  # RouterOS applies each /menu line at once: no configuration mode
    return {mode}


def completions(node, mode, buffer):
    """Words that can follow BUFFER (for tab completion): the next literal word of the matching commands."""
    typed = buffer.lower().split()
    partial = '' if buffer.endswith(' ') or not buffer else typed.pop()
    result = set()
    for entry in help_for(node, mode, ''):
        words = [w.lower() for w in _words(entry['syntax'])]
        if words[:len(typed)] == typed and len(words) > len(typed) and words[len(typed)].startswith(partial):
            result.add(words[len(typed)])
    return sorted(result)


def show_commands(syntax):
    """Every show command the catalogue lists for SYNTAX (tests check each against vendor_show)."""
    return [e[4][0] for e in CATALOGUES[syntax] if e[1] in ('exec', 'user', 'operational')
            and e[0] not in ('Modes',) and not e[4][0].startswith(('ping', 'execute ping', '/ping'))]


def check_known_shows():
    """Show commands the catalogue lists that the show code does not answer (empty when consistent)."""
    missing = []
    running = {'show running-config', 'display current-configuration', 'show configuration', 'show config running',
               'show full-configuration', '/export'}
    for syntax in CATALOGUES:
        if syntax == 'shell':
            continue
        for command in show_commands(syntax):
            if command not in vendor_show.COMMANDS[syntax] and command not in running:
                missing.append((syntax, command))
    return missing
