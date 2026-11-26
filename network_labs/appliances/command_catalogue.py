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

from . import ios_store, vendor_config, vendor_show

ROUTER, SWITCH, FIREWALL = 'R', 'S', 'F'
ALL = 'RSF'

# How each mode is reached, shown above the commands of that mode.
MODES = {
    'ios': {'exec': 'au démarrage (R1>) ; « enable » donne R1#', 'config': 'configure terminal (depuis R1#)',
            'config-if': 'interface PORT (depuis config)', 'config-subif': 'interface PORT.N (depuis config)',
            'config-router': 'router ospf N ou router bgp AS (depuis config)',
            'config-ext-nacl': 'ip access-list extended NOM (depuis config)', 'dhcp-config': 'ip dhcp pool NOM (depuis config)',
            'config-line': 'line con 0 ou line vty 0 4 (depuis config)', 'config-rip': 'router rip (depuis config)',
            'config-eigrp': 'router eigrp AS (depuis config)', 'config-vlan': 'vlan N (depuis config, sur un switch)'},
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
    ('Vérification', 'exec', 'traceroute A.B.C.D', 'Le chemin jusqu’à la destination, routeur par routeur (sondes réelles '
     'depuis la micro-VM).', ['traceroute {gw}'], ALL),
    ('Accès distant', 'exec', 'telnet A.B.C.D', 'Ouvrir une session Telnet sur un équipement (line vty : login, password).',
     ['telnet {gw}'], ALL),
    ('Accès distant', 'exec', 'ssh -l NOM A.B.C.D', 'Ouvrir une session SSH (username, login local, crypto key generate rsa).',
     ['ssh -l admin {gw}'], ALL),
    ('Système', 'config', 'hostname NOM', 'Nom de l’équipement (il doit rester celui du lab).', ['hostname {name}'], ALL),
    ('Interfaces', 'config', 'interface PORT', 'Configurer un port (mode config-if).', ['interface {p0}'], ALL),
    ('Interfaces', 'config-if', 'description TEXTE', 'Commentaire sur le port.', ['interface {p0}', 'description vers-LAN'], ALL),
    ('Interfaces', 'config-if', 'no shutdown', 'Activer le port (le lien remonte dans la micro-VM).',
     ['interface {p0}', 'no shutdown'], ALL),
    ('Interfaces', 'config-if', 'shutdown', 'Désactiver le port : son lien est coupé dans la micro-VM (administratively down).',
     ['interface {p0}', 'shutdown'], ALL),
    ('Routage statique', 'config', 'no ip route RÉSEAU MASQUE', 'Supprimer une route statique.',
     ['ip route 10.99.0.0 255.255.0.0 {gw}', 'no ip route 10.99.0.0 255.255.0.0'], 'R'),
    ('Routage inter-VLAN', 'config', 'ip route RÉSEAU MASQUE SAUT-SUIVANT',
     'Route statique d’un switch de niveau 3 (ip routing) : par l’interface vlan dont le réseau contient le saut suivant.',
     ['ip route 10.99.0.0 255.255.0.0 192.0.2.254'], 'S'),
    ('Routage inter-VLAN', 'config', 'no ip route RÉSEAU MASQUE [SAUT-SUIVANT]', 'Supprimer une route statique du switch.',
     ['ip route 10.99.0.0 255.255.0.0 192.0.2.254', 'no ip route 10.99.0.0 255.255.0.0'], 'S'),
]
_IOS_L3 = [
    ('Interfaces', 'config-if', 'ip address A.B.C.D MASQUE', 'Adresse IPv4 du port.',
     ['interface {p0}', 'ip address {ip0} {mask0}'], 'RF'),
    ('Interfaces', 'config', 'interface PORT.N', 'Sous-interface 802.1Q (routeur sur un lien, inter-VLAN).',
     ['interface {p2}.10', 'encapsulation dot1Q 10', 'ip address 10.10.0.1 255.255.255.0'], 'RF'),
    ('Interfaces', 'config', 'no interface PORT.N', 'Supprimer une sous-interface.',
     ['interface {p2}.30', 'encapsulation dot1Q 30', 'ip address 10.30.0.1 255.255.255.0', 'no interface {p2}.30'], 'RF'),
    ('Interfaces', 'config-subif', 'encapsulation dot1Q VLAN', 'Le VLAN que porte la sous-interface.',
     ['interface {p2}.20', 'encapsulation dot1Q 20', 'ip address 10.20.0.1 255.255.255.0'], 'RF'),
    ('Routage statique', 'config', 'ip route RÉSEAU MASQUE PASSERELLE', 'Route statique (0.0.0.0 0.0.0.0 pour la route par défaut).',
     ['ip route 10.99.0.0 255.255.0.0 {gw}'], 'RF'),
    ('Routage statique', 'config', 'ip route RÉSEAU MASQUE PORT', 'Route par un port, sans passerelle : le routeur voisin répond '
     'par proxy ARP.', ['ip route 10.98.0.0 255.255.0.0 {p1}'], 'R'),
    ('Routage statique', 'config-if', 'ip proxy-arp', 'Répondre aux ARP pour les adresses joignables par un autre port (défaut).',
     ['interface {p0}', 'no ip proxy-arp', 'ip proxy-arp'], 'R'),
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
    ('VLAN', 'config', 'vlan N', 'Créer le VLAN N (mode config-vlan : name).', ['vlan 30'], 'S'),
    ('Gestion', 'config', 'interface vlan N', 'L’interface de gestion du switch (éteinte au départ : no shutdown).',
     ['interface vlan 1', 'ip address 192.0.2.250 255.255.255.0', 'no shutdown'], 'S'),
    ('Gestion', 'config-if', 'ip address A.B.C.D MASQUE', 'L’adresse de gestion du switch (sur interface vlan N).',
     ['interface vlan 1', 'ip address 192.0.2.250 255.255.255.0'], 'S'),
    ('Gestion', 'config', 'no interface vlan N', 'Supprimer l’interface de gestion.', ['interface vlan 1', 'no interface vlan 1'], 'S'),
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

_IOS_MORE = [
    ('HSRP', 'config-if', 'standby [N] ip A.B.C.D',
     'Passerelle virtuelle du groupe HSRP N (0 sans numéro), dans le réseau du port : le routeur actif y répond avec la MAC '
     '0000.0c07.acNN ; les PC la prennent pour passerelle.', ['interface {p0}', 'standby 1 ip {peer0}'], 'R'),
    ('HSRP', 'config-if', 'standby [N] priority N', 'Priorité dans le groupe (100 par défaut) : la plus haute devient le routeur actif.',
     ['interface {p0}', 'standby 1 ip {peer0}', 'standby 1 priority 110'], 'R'),
    ('HSRP', 'config-if', 'standby [N] preempt',
     'Reprendre le rôle actif dès que ce routeur a la plus haute priorité (sans preempt, il attend la panne de l’actif).',
     ['interface {p0}', 'standby 1 ip {peer0}', 'standby 1 preempt'], 'R'),
    ('HSRP', 'config-if', 'standby [N] timers N N',
     'Hello et hold en secondes (3 et 10 par défaut) : sans hello de l’actif pendant hold, le standby prend la relève.',
     ['interface {p0}', 'standby 1 ip {peer0}', 'standby 1 timers 1 4'], 'R'),
    ('HSRP', 'config-if', 'standby [N] authentication TEXTE', 'Mot de passe en clair du groupe (8 caractères au plus, cisco par défaut).',
     ['interface {p0}', 'standby 1 ip {peer0}', 'standby 1 authentication LAB'], 'R'),
    ('HSRP', 'config-if', 'standby version 1|2', 'Version de HSRP (2 : groupes jusqu’à 4095, MAC virtuelle 0000.0c9f.fNNN).',
     ['interface {p0}', 'standby version 2'], 'R'),
    ('HSRP', 'config-if', 'no standby [N]', 'Retirer le groupe N de ce port (sans numéro : tous ses groupes).',
     ['interface {p0}', 'standby 1 ip {peer0}', 'no standby 1'], 'R'),
    ('HSRP', 'exec', 'show standby', 'Chaque groupe HSRP : état (Active, Standby, Listen…), adresse et MAC virtuelles, routeurs actif '
     'et standby avec leur priorité (lus dans la micro-VM).', ['show standby'], 'R'),
    ('HSRP', 'exec', 'show standby brief', 'Un groupe par ligne : priorité, P (preempt), état, actif, standby, adresse virtuelle.',
     ['show standby brief'], 'R'),
    ('Services', 'exec', 'ping NOM', 'Ping vers un nom : la table « ip host », puis le serveur DNS de « ip name-server ».',
     ['ping www.lab.local'], 'RS'),
    ('Services', 'exec', 'show hosts', 'Les serveurs DNS et la table d’hôtes (ip host).', ['show hosts'], 'RSF'),
    ('Services', 'exec', 'show ntp status', 'Horloge synchronisée ou non, strate, référence (ntp server, ntp master).', ['show ntp status'], 'RSF'),
    ('Services', 'exec', 'show ntp associations', 'Le serveur NTP et son état (* : celui qu’on suit).', ['show ntp associations'], 'RSF'),
    ('Services', 'exec', 'show logging', 'Le journal en mémoire et les serveurs syslog (logging host, logging trap).', ['show logging'], 'RSF'),
    ('Services', 'exec', 'copy running-config tftp:', 'Sauvegarder la configuration sur un serveur TFTP (adresse, puis nom du fichier).',
     ['copy running-config tftp:'], 'RS'),
    ('Services', 'exec', 'copy tftp: running-config', 'Reprendre une configuration d’un serveur TFTP (ses lignes s’ajoutent, comme sur IOS).',
     ['copy tftp: running-config'], 'RS'),
    ('Vérification', 'exec', 'show version', 'Le modèle, la mémoire, les ports, la durée de fonctionnement.', ['show version'], ALL),
    ('Vérification', 'exec', 'show interfaces', 'L’état détaillé de chaque port.', ['show interfaces'], ALL),
    ('Vérification', 'exec', 'show cdp neighbors', 'Les équipements Cisco voisins, par câble.', ['show cdp neighbors'], ALL),
    ('Vérification', 'exec', 'show cdp neighbors detail', 'Les voisins CDP avec leur adresse.', ['show cdp neighbors detail'], ALL),
    ('Vérification', 'exec', 'show startup-config', 'La configuration enregistrée (copy run start).', ['show startup-config'], ALL),
    ('Vérification', 'exec', 'show history', 'Les dernières commandes tapées.', ['show history'], ALL),
    ('Vérification', 'exec', 'show clock', 'L’heure de l’équipement.', ['show clock'], ALL),
    ('Vérification', 'exec', 'show users', 'Les sessions ouvertes.', ['show users'], ALL),
    ('Vérification', 'exec', 'show privilege', 'Le niveau de privilège courant.', ['show privilege'], ALL),
    ('Vérification', 'exec', 'show ip protocols', 'Les protocoles de routage configurés.', ['show ip protocols'], 'R'),
    ('EIGRP', 'exec', 'show ip eigrp neighbors', 'Les voisins EIGRP (lus dans eigrpd de la micro-VM).', ['show ip eigrp neighbors'], 'R'),
    ('NAT', 'exec', 'show ip nat translations', 'Les traductions en cours (lues dans le noyau de la micro-VM).',
     ['show ip nat translations'], 'R'),
    ('NAT', 'exec', 'show ip nat statistics', 'Les règles de NAT actives et leurs ports.', ['show ip nat statistics'], 'R'),
    ('VLAN', 'exec', 'show interfaces trunk', 'Les trunks et leurs VLAN.', ['show interfaces trunk'], 'S'),
    ('VLAN', 'exec', 'show mac address-table', 'Les adresses MAC apprises par le switch, par VLAN et par port (lues dans la micro-VM).',
     ['show mac address-table'], 'S'),
    ('Vérification', 'exec', 'show arp', 'La table ARP : adresses IP voisines et leur adresse MAC (lue dans la micro-VM).',
     ['show arp'], 'RF'),
    ('Vérification', 'exec', 'show ip arp', 'La table ARP (même chose que show arp).', ['show ip arp'], 'RF'),
    ('Vérification', 'exec', 'show ip route connected|static|rip|eigrp|ospf|bgp', 'Seulement les routes de ce type.',
     ['show ip route static'], 'R'),
    ('DHCP', 'exec', 'show ip dhcp binding', 'Les adresses que le serveur DHCP du routeur a données (lues dans la micro-VM).',
     ['show ip dhcp binding'], 'R'),
    ('VLAN', 'exec', 'show interfaces status', 'Chaque port : état (connected, notconnect, disabled), VLAN ou trunk.',
     ['show interfaces status'], 'S'),
    ('EtherChannel', 'config-if', 'channel-group N mode active|passive|on|desirable|auto',
     'Regrouper ce port dans le Port-channel N, en LACP (active négocie, passive répond ; il faut un côté actif). '
     'Les modes on, desirable et auto (sans LACP, ou PAgP) ne sont pas pris en charge sur les switchs micro-VM.',
     ['interface {p0}', 'channel-group 1 mode active'], 'S'),
    ('EtherChannel', 'config-if', 'no channel-group', 'Sortir ce port de son Port-channel (il garde ses réglages switchport).',
     ['interface {p0}', 'channel-group 1 mode active', 'no channel-group'], 'S'),
    ('EtherChannel', 'config', 'interface port-channel N', 'Le Port-channel N : ses réglages switchport valent pour tous ses ports.',
     ['interface port-channel 1', 'switchport mode trunk'], 'S'),
    ('EtherChannel', 'config', 'no interface port-channel N', 'Supprimer le Port-channel N : ses ports redeviennent indépendants.',
     ['interface port-channel 1', 'exit', 'no interface port-channel 1'], 'S'),
    ('Sécurité des ports', 'exec', 'show port-security',
     'Les ports sécurisés : maximum, adresses, violations et action (lus dans la micro-VM).', ['show port-security'], 'S'),
    ('Sécurité des ports', 'exec', 'show port-security interface PORT',
     'Un port sécurisé : état (Secure-up ou Secure-shutdown), adresses, dernière adresse source, violations.',
     ['show port-security interface {p0}'], 'S'),
    ('Sécurité des ports', 'exec', 'show port-security address', 'La table des adresses sécurisées (configurées, sticky, apprises).',
     ['show port-security address'], 'S'),
    ('EtherChannel', 'exec', 'show etherchannel summary',
     'Chaque Port-channel et ses ports : P groupé, I indépendant, D coupé ; SU en service (lu dans les bonds LACP de la micro-VM).',
     ['show etherchannel summary'], 'S'),
    ('Spanning tree', 'exec', 'show spanning-tree [vlan N]',
     'L’arbre 802.1D du switch : la racine, le coût jusqu’à elle, le rôle et l’état de chaque port (Root, Desg, Altn BLK).',
     ['show spanning-tree'], 'S'),
    ('Spanning tree', 'config', 'spanning-tree vlan N',
     'Activer le spanning tree du switch (il l’est dès qu’un câble ferme une boucle).', ['spanning-tree vlan 1'], 'S'),
    ('Spanning tree', 'config', 'no spanning-tree vlan N priority', 'Rendre au pont la priorité par défaut (32768).',
     ['spanning-tree vlan 1 priority 4096', 'no spanning-tree vlan 1 priority'], 'S'),
    ('Spanning tree', 'config-if', 'no spanning-tree cost|port-priority', 'Rendre au port son coût (ou sa priorité) par défaut.',
     ['interface {p0}', 'spanning-tree cost 100', 'no spanning-tree cost'], 'S'),
    ('Système', 'exec', 'copy running-config startup-config', 'Enregistrer la configuration (aussi : wr).',
     ['copy running-config startup-config'], ALL),
    ('Système', 'exec', 'write memory', 'Enregistrer la configuration.', ['write memory'], ALL),
    ('Système', 'exec', 'erase startup-config', 'Effacer la configuration enregistrée.', ['erase startup-config'], ALL),
    ('Système', 'exec', 'clock set HH:MM:SS JOUR MOIS ANNÉE', 'Régler l’heure.', ['clock set 10:30:00 18 nov 2026'], ALL),
    ('Système', 'exec', 'terminal length N', 'Lignes par page (0 : sans --More--).', ['terminal length 0'], ALL),
    ('ACL', 'config', 'access-list N permit|deny SOURCE',
     'Liste d’accès standard numérotée (1-99) : filtre la source (any, host A.B.C.D ou A.B.C.D JOKER).',
     ['access-list 1 permit {net0} {wild0}'], 'R'),
    ('ACL', 'config', 'access-list N permit|deny ip|icmp|tcp|udp SOURCE DESTINATION [eq PORT]',
     'Liste d’accès étendue numérotée (100-199).', ['access-list 101 deny tcp any host 198.51.100.10 eq 22',
                                                    'access-list 101 permit ip any any'], 'R'),
    ('ACL', 'config', 'no access-list N', 'Supprimer une liste numérotée.',
     ['access-list 1 permit any', 'no access-list 1'], 'R'),
    ('Interfaces', 'config', 'interface range PORT - N', 'Configurer plusieurs ports à la fois.',
     ['interface range {p0} - 1', 'description utilisateurs'], 'S'),
]

CATALOGUES = {
    'ios': _IOS_COMMON + _IOS_L3 + _IOS_OSPF + _IOS_BGP + _IOS_BGP_NETWORK + _IOS_ACL + _IOS_SWITCH + _IOS_MORE
    + ios_store.catalogue_entries(),
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
        ('Vérification', 'user', 'tracert A.B.C.D', 'Le chemin jusqu’à la destination, routeur par routeur.', ['tracert {gw}'], ALL),
        ('Système', 'system', 'sysname NOM', 'Nom de l’équipement (il doit rester celui du lab).', ['sysname {name}'], ALL),
        ('Interfaces', 'system', 'interface PORT', 'Configurer un port.', ['interface {p0}'], ALL),
        ('Interfaces', 'interface', 'ip address A.B.C.D MASQUE', 'Adresse IPv4 du port.',
         ['interface {p0}', 'ip address {ip0} {mask0}'], 'R'),
        ('Interfaces', 'interface', 'description TEXTE', 'Commentaire sur le port.', ['interface {p0}', 'description vers-LAN'], ALL),
        ('Interfaces', 'interface', 'undo shutdown', 'Activer le port (le lien remonte dans la micro-VM).',
         ['interface {p0}', 'undo shutdown'], ALL),
        ('Interfaces', 'interface', 'shutdown', 'Désactiver le port : son lien est coupé dans la micro-VM.',
         ['interface {p0}', 'shutdown'], ALL),
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
        ('Vérification', 'shell', 'traceroute A.B.C.D', 'Le chemin jusqu’à la destination, routeur par routeur.', ['traceroute {gw}'],
         'H'),
        ('Vérification', 'shell', 'tracert A.B.C.D', 'Le même chemin, affiché comme sur un PC Windows (Packet Tracer).',
         ['tracert {gw}'], 'H'),
        ('Vérification', 'shell', 'ipconfig', 'Adresse, masque et passerelle du PC (comme sur un PC Windows).', ['ipconfig'], 'H'),
        ('Vérification', 'shell', 'ipconfig /all', 'Avec l’adresse MAC et le DHCP.', ['ipconfig /all'], 'H'),
        ('Vérification', 'shell', 'arp -a', 'La table ARP du PC (voisins et leur adresse MAC).', ['arp -a'], 'H'),
        ('Vérification', 'shell', 'ip neigh', 'La même table, comme Linux l’écrit.', ['ip neigh'], 'H'),
        ('Accès distant', 'shell', 'telnet A.B.C.D', 'Se connecter en Telnet à un routeur ou un switch (exit pour revenir).',
         ['telnet {gw}'], 'H'),
        ('Accès distant', 'shell', 'ssh -l NOM A.B.C.D', 'Se connecter en SSH (le compte username du routeur).',
         ['ssh -l admin {gw}'], 'H'),
        ('Adressage', 'shell', 'ip addr add A.B.C.D/N dev PORT', 'Donner une adresse IPv4 au port (appliquée aussitôt).',
         ['ip addr add 192.0.2.10/24 dev {p0}'], 'H'),
        ('Adressage', 'shell', 'ip addr del A.B.C.D/N dev PORT', 'Retirer l’adresse du port.', ['ip addr del {ip0}/{len0} dev {p0}'], 'H'),
        ('Adressage', 'shell', 'ip route add default via A.B.C.D', 'La passerelle par défaut (sur le réseau du port).',
         ['ip route add default via {peer0}'], 'H'),
        ('Adressage', 'shell', 'ip route add RÉSEAU/N via A.B.C.D', 'Une route statique.', ['ip route add 10.99.0.0/16 via {peer0}'], 'H'),
        ('Adressage', 'shell', 'ip route del default|RÉSEAU/N via A.B.C.D', 'Supprimer une route.',
         ['ip route del default via {peer0}'], 'H'),
        ('Services', 'shell', 'nslookup NOM [SERVEUR]', 'Demander l’adresse d’un nom au serveur DNS du poste (ou à SERVEUR).',
         ['nslookup www.lab.local'], 'H'),
        ('Services', 'shell', 'ping NOM', 'Ping vers un nom (résolu par le serveur DNS du poste).', ['ping www.lab.local'], 'H'),
        ('Services', 'shell', 'curl http://ADRESSE/PAGE', 'Afficher une page d’un serveur web (nom ou adresse ; curl -i : avec les en-têtes).',
         ['curl http://{gw}/'], 'H'),
        ('Services', 'shell', 'wget -qO- http://ADRESSE/PAGE', 'La même page, avec wget.', ['wget -qO- http://{gw}/'], 'H'),
        ('Services', 'shell', 'logread', 'Les messages reçus par le service Syslog du serveur.', ['logread'], 'H'),
        ('Services', 'shell', 'ls -l /tftpboot', 'Les fichiers du service TFTP du serveur (cat /tftpboot/NOM pour en lire un).',
         ['ls -l /tftpboot'], 'H'),
        ('Système', 'shell', 'hostname', 'Le nom du nœud.', ['hostname'], 'H'),
        ('Système', 'shell', 'exit', 'Fermer le terminal.', ['exit'], 'H'),
    ],
}

# The prompt suffix and catalogue mode each context-entering line gives, per dialect (line order matters).
CONTEXTS = {
    'ios': [(r'interface range .+', 'config-if-range'), (r'interface \S+\.\d+', 'config-subif'), (r'interface .+', 'config-if'),
            (r'line (con|console|vty|aux) .+', 'config-line'), (r'router rip', 'config-rip'), (r'router eigrp \d+', 'config-eigrp'),
            (r'vlan \d+', 'config-vlan'),
            (r'router (ospf|bgp) \d+', 'config-router'),
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


LAYER3_ONLY = ('ip routing',)  # and the « Routage inter-VLAN » topic


def entries(node):
    """The node's catalogue: [{'topic', 'mode', 'syntax', 'help', 'example'}], examples with its own port names."""
    syntax = syntax_of(node)
    shown = vendor_config.port_names(node) if syntax != 'shell' else {p: p for p in node.get('interfaces', {})}
    values = placeholders(node, shown)
    letter = _role_letter(node)
    from .svi import layer3
    layer2 = node.get('role') == 'switch' and node.get('runtime') == 'firecracker' and not layer3(node)
    found = []
    for topic, mode, text, explanation, example, roles in CATALOGUES[syntax]:
        if syntax != 'shell' and letter not in roles:
            continue
        if layer2 and (text in LAYER3_ONLY or topic == 'Routage inter-VLAN'):
            continue  # a 2960 refuses them, as on IOS; a 9200L routes
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


def expand(node, line, mode=None):
    """IOS-style abbreviations: each keyword typed as a unique prefix of the words the catalogue allows at that place
    (« int g0/0/0 », « ip add », « no shut », « sw mo acc ») becomes the full word; values are left as typed. With MODE,
    only that mode's commands count (« sh » is show in EXEC, not shutdown)."""
    syntax = syntax_of(node)
    if syntax not in ('ios', 'eos', 'vrp'):
        return line
    listed = entries(node) if mode is None else _ios_entries(node, mode, own=True)
    patterns = [v.split() for e in listed for v in _variants(e['syntax'])]  # keywords are lower case, placeholders upper case
    typed, done = line.split(), []
    for index, word in enumerate(typed):
        low = word.lower()
        options, value = set(), False
        for pattern in patterns:
            if len(pattern) <= index or any(not _fits(pattern[i], w) for i, w in enumerate(done)):
                continue
            options.update(c for c in pattern[index].split('|') if c.isascii() and c.islower() and not c.startswith('['))
            value = value or _fits(pattern[index], '\0')  # a placeholder there (« standby [N] … »: the group number)
        chosen = [o for o in options if o.startswith(low)]
        if low in options or len(chosen) != 1:
            done.append(low if low in options else word)
            if low not in options and not chosen and not value:
                done.extend(typed[index + 1:])
                break
            continue
        done.append(chosen[0])
    return ' '.join(done)


def _fits(pattern_word, word):
    """Whether a typed (expanded) word fits one word of a syntax line: a keyword, its alternatives, or a placeholder."""
    alternatives = pattern_word.split('|')
    if any(not (a.isascii() and a.islower()) or a.startswith('[') for a in alternatives):
        return True  # a placeholder (A.B.C.D, PORT, NOM…) takes any value
    return word.lower() in alternatives


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
            and e[4][0].startswith(('show ', 'display ', 'get ', '/')) and not e[4][0].startswith('/ping')]


def check_known_shows():
    """Show commands the catalogue lists that the show code does not answer (empty when consistent)."""
    missing = []
    from .ios_exec import SHOWS
    running = {'show running-config', 'display current-configuration', 'show configuration', 'show config running',
               'show full-configuration', '/export', *SHOWS}
    for syntax in CATALOGUES:
        if syntax == 'shell':
            continue
        for command in show_commands(syntax):
            if command not in vendor_show.COMMANDS[syntax] and command not in running:
                missing.append((syntax, command))
    return missing


# ---- IOS context help and errors, as Packet Tracer and the real CLI give them ----

GREEDY = {'TEXTE', 'SOURCE', 'DESTINATION'}  # take the rest of the line (free text, ACL address forms)
PLACEHOLDERS = {'A.B.C.D': ('A.B.C.D', 'Adresse IPv4'), 'MASQUE': ('A.B.C.D', 'Masque de sous-réseau'),
                'JOKER': ('A.B.C.D', 'Masque joker (inverse)'), 'PASSERELLE': ('A.B.C.D', 'Adresse du prochain saut'),
                'RÉSEAU': ('A.B.C.D', 'Réseau de destination'), 'AS': ('<1-4294967295>', 'Numéro d’AS'),
                'N': ('<1-65535>', 'Nombre'), 'VLAN': ('<1-4094>', 'Numéro de VLAN'), 'NOM': ('WORD', 'Nom'),
                'TEXTE': ('LINE', 'Texte libre'), 'SEQ': ('<1-2147483647>', 'Numéro de séquence'),
                'LISTE': ('WORD', 'Liste de VLAN (10,20 ou 10-20)'), 'JOURS': ('<0-365>', 'Jours'),
                'HEURES': ('<0-23>', 'Heures'), 'MINUTES': ('<0-59>', 'Minutes'),
                'SOURCE': ('any | host A.B.C.D | A.B.C.D JOKER', 'Source'),
                'DESTINATION': ('any | host A.B.C.D | A.B.C.D JOKER', 'Destination')}
KEYWORD_HELP = {'ip': 'Configuration IPv4', 'ospf': 'Paramètres OSPF', 'dhcp': 'Serveur DHCP', 'route': 'Route statique',
                'router': 'Protocole de routage', 'show': 'Afficher l’état du système', 'no': 'Annuler une commande',
                'interface': 'Choisir une interface', 'switchport': 'Port de switch (VLAN)', 'access-list': 'Liste d’accès',
                'access-group': 'Appliquer une liste d’accès', 'bgp': 'Paramètres BGP', 'neighbor': 'Voisin BGP',
                'network': 'Réseau annoncé', 'trunk': 'Port trunk 802.1Q', 'access': 'Port d’accès', 'mode': 'Mode du port',
                'vlan': 'VLAN', 'interface-brief': '', 'running-config': 'Configuration courante',
                'configure': 'Entrer en configuration', 'terminal': 'Depuis ce terminal', 'ping': 'Écho ICMP',
                'traceroute': 'Chemin jusqu’à une destination', 'standby': 'Groupe HSRP (passerelle de secours)'}


def _tokens(syntax):
    return syntax.split()


def _variants(syntax):
    """The flat forms of a syntax line: each optional group of several words (« [privilege N] ») typed or left out.
    One-word options, nested ones and « [eq PORT] » are matched as they are (_match)."""
    match = re.search(r'\[([^\[\]]* [^\[\]]*)\]', syntax)
    if not match or match[1].startswith('eq '):
        return [syntax]
    typed = syntax[:match.start()] + match[1] + syntax[match.end():]
    left_out = ' '.join((syntax[:match.start()] + syntax[match.end():]).split())
    return _variants(typed) + _variants(left_out)


def _keyword(token):
    """The keyword alternatives of a token ('permit|deny'), or None for a placeholder."""
    if token.startswith('['):
        return None
    alternatives = [a for a in token.split('|')]
    if all(a.isascii() and a.islower() for a in alternatives):
        return alternatives
    return None


def _match(tokens, words, i=0, k=0):
    """('ok' | 'incomplete' | 'invalid', furthest word index reached) for WORDS against one syntax's TOKENS."""
    if k == len(words):
        required = [t for t in tokens[i:] if not t.startswith('[')]
        return ('ok', k) if not required else ('incomplete', k)
    if i == len(tokens):
        return 'invalid', k
    token = tokens[i]
    if token.startswith('['):
        skipped = _match(tokens, words, i + 1, k)
        used = _match(tokens, words, i + 1, k + 1) if token.strip('[]').split('|')[0] not in ('eq',) else \
            (_match(tokens, words, i + 2, k + 2) if words[k].lower() == 'eq' else ('invalid', k))
        return max(skipped, used, key=lambda r: ({'ok': 2, 'incomplete': 1, 'invalid': 0}[r[0]], r[1]))
    keyword = _keyword(token)
    if keyword is None:
        if token in GREEDY:
            return 'ok', len(words)
        return _match(tokens, words, i + 1, k + 1)
    if words[k].lower() in keyword:
        return _match(tokens, words, i + 1, k + 1)
    return 'invalid', k


def _ios_entries(node, mode, own=False):
    """The commands typed at MODE; for a check, a sub-mode also takes global commands (IOS leaves the sub-mode for
    them), while « ? » (OWN) lists the sub-mode's own."""
    visible = {mode} if own and mode not in ('exec', 'enable', 'config') else _modes_visible(syntax_of(node), mode)
    if not own and mode not in ('exec', 'enable'):
        visible |= {'config'}
    return [e for e in entries(node) if e['mode'] in visible]


def ios_check(node, mode, line):
    """('ok' | 'incomplete' | 'invalid' | 'ambiguous', detail): detail is the character index of the faulty word for
    'invalid', the typed text for 'ambiguous'."""
    words = line.split()
    if not words:
        return 'ok', None
    results = [_match(_tokens(v), words) for e in _ios_entries(node, mode) for v in _variants(e['syntax'])]
    if any(status == 'ok' for status, _ in results):
        return 'ok', None
    if any(status == 'incomplete' for status, _ in results):
        return 'incomplete', None
    furthest = max((index for _, index in results), default=0)
    if furthest < len(words):
        options = {o for e in _ios_entries(node, mode) for v in _variants(e['syntax'])
                   for o in _next_keywords(_tokens(v), words[:furthest])}
        if len([o for o in options if o.startswith(words[furthest].lower())]) > 1:
            return 'ambiguous', line
    position = 0
    for index, word in enumerate(words):
        position = line.index(word, position)
        if index == furthest:
            break
        position += len(word)
    return 'invalid', position


def _next_keywords(tokens, words):
    """The keywords a syntax allows right after WORDS (empty if WORDS do not fit it)."""
    found = set()

    def walk(i, k):
        if k == len(words):
            while i < len(tokens):
                keyword = _keyword(tokens[i].strip('[]')) if tokens[i].startswith('[') else _keyword(tokens[i])
                if keyword:
                    found.update(keyword)
                if not tokens[i].startswith('['):
                    break
                i += 1
            return
        if i >= len(tokens):
            return
        token = tokens[i]
        keyword = _keyword(token)
        if token.startswith('['):
            walk(i + 1, k)
            walk(i + 1, k + 1)
        elif keyword is None:
            if token not in GREEDY:
                walk(i + 1, k + 1)
        elif words[k].lower() in keyword:
            walk(i + 1, k + 1)
    walk(0, 0)
    return found


def ios_help(node, mode, typed):
    """What « ? » shows on IOS: after a space, the next words with what they do (and <cr> when the command can end);
    right after a word, the keywords that complete it."""
    words = typed.split()
    if typed and not typed.endswith(' '):
        partial, words = words[-1].lower(), expand(node, ' '.join(words[:-1]), mode).split()  # « sh ip ro? »: abbreviations too
        options = sorted({o for e in _ios_entries(node, mode, own=True) for v in _variants(e['syntax'])
                          for o in _next_keywords(_tokens(v), words)
                          if o.startswith(partial)})
        return '  '.join(options) if options else '% Unrecognized command'
    words = expand(node, ' '.join(words), mode).split()  # « sh mac address-table ? » as « show mac address-table ? »
    rows, complete = {}, False
    for entry, tokens in [(e, _tokens(v)) for e in _ios_entries(node, mode, own=True) for v in _variants(e['syntax'])]:
        status, _ = _match(tokens, words)
        if status == 'ok' and words:
            complete = True
        for word in _next_keywords(tokens, words):
            rows.setdefault(word, KEYWORD_HELP.get(word) or entry['help'])
        if status in ('incomplete', 'ok'):
            index = _position(tokens, words)
            if index is not None and index < len(tokens) and _keyword(tokens[index].strip('[]')) is None:
                name = tokens[index].strip('[]').split('|')[0]
                shown, text = PLACEHOLDERS.get(name, (name, entry['help']))
                if name == 'PORT.N':
                    continue
                if name == 'PORT':
                    for label in vendor_config.port_names(node).values():
                        rows.setdefault(vendor_config.ios_name(label) if syntax_of(node) == 'ios' else label, 'Interface')
                else:
                    rows.setdefault(shown, text)
    if not rows and not complete:
        return '% Unrecognized command'
    width = max([len(k) for k in rows] + [4]) + 2
    lines = [f'  {word:<{width}}{text}' for word, text in sorted(rows.items())]
    if complete:
        lines.append('  <cr>')
    return '\n'.join(lines)


def _position(tokens, words):
    """The index of the token right after WORDS in one syntax, following its simplest path (None if it does not fit)."""
    i = 0
    for word in words:
        while i < len(tokens) and tokens[i].startswith('[') and not (_keyword(tokens[i].strip('[]')) or [None])[0] == word:
            if len(words) and i + 1 < len(tokens):
                break
            i += 1
        if i >= len(tokens):
            return None
        keyword = _keyword(tokens[i].strip('[]'))
        if keyword is not None and word.lower() not in keyword:
            return None
        if tokens[i].strip('[]') in GREEDY:
            return None
        i += 1
    return i
