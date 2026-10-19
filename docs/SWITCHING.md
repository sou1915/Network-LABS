# Configuration CLI dans Network LABS

La CLI est un sous-ensemble pédagogique inspiré de Cisco IOS. Ouvrir une console par
double-clic sur un équipement. L'identifiant du node reste stable ; `hostname` modifie
le nom affiché et le prompt. Aucune commande n'est exécutée sur le Linux hôte.

`?` affiche l'aide, `show capabilities` le périmètre et les limites. L'éditeur
**Coller un bloc** accepte plusieurs lignes et s'arrête à la première erreur.
Abréviations utiles : `en`, `conf t`, `int`, `sh`, `show run`, `wr`.
Depuis un mode de configuration, utiliser `do show ...`.

## 1. Modes et VLAN

```text
enable
configure terminal
hostname ACCESS-01
vlan 10
name USERS
exit
vlan 20
name SERVERS
exit
interface range gi0/1 - 2
switchport mode access
switchport access vlan 10
no shutdown
exit
interface gi0/3
switchport mode trunk
switchport trunk allowed vlan 10,20
switchport trunk native vlan 1
no shutdown
end
show vlan brief
show interfaces status
show interfaces trunk
show interfaces gi0/3 switchport
```

Chaque port est configurable indépendamment. Créer aussi les VLAN sur le switch à
l'autre extrémité du trunk. Sur le lab Inter-VLAN, gi0/1 est relié à PC1,
gi0/2 à PC2 et gi0/3 au routeur ; placer gi0/2 en VLAN 20 pour conserver cette démo.

Commandes supplémentaires :

```text
switchport trunk allowed vlan add 30-35
switchport trunk allowed vlan remove 32
switchport trunk allowed vlan all
switchport trunk allowed vlan none
no switchport trunk allowed vlan
no switchport access vlan
no switchport trunk native vlan
shutdown
no shutdown
description Uplink-vers-distribution
```

Les commandes `no ...` ci-dessus rétablissent respectivement tous les VLAN autorisés,
VLAN access 1 et VLAN natif 1. `no vlan 30` se saisit au niveau configuration globale.
Les VLAN réservés/plateformes spécifiques ne sont pas modélisés.

## 2. STP par VLAN

Charger **Boucle STP**, ouvrir les consoles des switches, observer le VLAN 10.

Sur SW1 :

```text
enable
configure terminal
spanning-tree mode rapid-pvst
spanning-tree vlan 10,20 root primary
end
show spanning-tree vlan 10
```

Sur SW2 :

```text
enable
configure terminal
spanning-tree vlan 10 priority 28672
interface gi0/1
spanning-tree cost 50
spanning-tree port-priority 64
end
show spanning-tree
```

Priorité de bridge : multiple de 4096 entre 0 et 61440. Priorité de port : multiple de
16 entre 0 et 240. Le bridge ID utilise une MAC déterministe attribuée au node.
Le moteur calcule le root et les ports ROOT / DESG / ALTN. Les ports ALTN bloquent le
chemin. Couper un câble provoque un nouveau calcul ; aucun délai STP/RSTP n'est simulé.
`spanning-tree mode pvst` utilise le même résultat convergé dans cette version.

Protection d'un port utilisateur :

```text
enable
configure terminal
interface gi0/1
spanning-tree portfast
spanning-tree bpduguard enable
end
```

Connecter un switch à ce port entraîne un état err-disabled. `shutdown` puis
`no shutdown` le réarme ; si le switch voisin reste présent, il est de nouveau bloqué.
PortFast est mémorisé, sans effet temporel dans le calcul convergé.

## 3. EtherChannel : LACP, PAgP, statique

Charger **EtherChannel**. SW1 gi0/4 et gi0/5 sont reliés à SW2 gi0/1 et gi0/2.
Deux câbles physiques sont groupés en un lien logique pour le calcul STP.

Sur SW1 :

```text
enable
configure terminal
interface range gi0/4 - 5
switchport mode trunk
switchport trunk allowed vlan 10,20
channel-group 1 mode active
end
show etherchannel summary
```

Sur SW2 :

```text
enable
configure terminal
interface range gi0/1 - 2
switchport mode trunk
switchport trunk allowed vlan 10,20
channel-group 1 mode passive
end
show etherchannel summary
```

| Modes des partenaires | État calculé |
|---|---|
| active + active / passive | Agrégation LACP |
| passive + passive | Suspendu |
| desirable + desirable / auto | Agrégation PAgP |
| auto + auto | Suspendu |
| on + on | Agrégation statique |
| on + active / autres mélanges | Suspendu |

Les membres doivent avoir une configuration cohérente : mode, VLAN access, VLAN
natif et allowed. Un groupe local ne peut pas relier plusieurs partenaires.
`P` dans le résumé signifie agrégé, `s` suspendu. `no channel-group 1` retire le port.

L'interface logique `interface port-channel 1` (ou `interface po1`) permet de configurer
mode, VLAN et shutdown des membres déjà affectés. Configurer d'abord les membres et
leur channel-group ; la création seule d'un port-channel ne groupe pas des câbles.
Pas de simulation de hash, de débit, de PDUs ou de timers de négociation.

## 4. Port-security

Sur SW1, gi0/1 est le port de PC1 dans la démo Inter-VLAN :

```text
enable
configure terminal
interface gi0/1
switchport mode access
switchport port-security
switchport port-security maximum 1
switchport port-security mac-address sticky
switchport port-security violation shutdown
end
show port-security interface gi0/1
```

Lancer un ping de PC1 pour apprendre sa MAC. Pour provoquer une violation sans
changer de node, configurer à l'avance une MAC autorisée différente sur un port
sans apprentissage précédent :

```text
switchport port-security mac-address 00:11:22:33:44:55
```

`shutdown` : err-disabled ; `restrict` : rejet et compteur ; `protect` : rejet sans
incrément de compteur. Les notifications SNMP et syslog constructeurs ne sont pas
simulées. Les MAC sticky sont enregistrées avec le projet, les MAC sécurisées
apprises sans sticky sont un état d'exécution. Réarmer : `shutdown` / `no shutdown`.
Port-security est limité aux ports access.

## 5. Apprentissage et inspection

```text
show mac address-table
show mac address-table dynamic
clear mac address-table dynamic
show interfaces status
show cdp neighbors
show lldp neighbors
show running-config
show startup-config
write memory
```

Les MAC sont apprises sur le parcours du test de connectivité ; pas encore de
flooding de trames ou de vieillissement. `write memory` enregistre un snapshot
textuel dans le projet : sauvegarder le JSON pour l'écrire sur disque. Les commandes
CDP/LLDP montrent seulement les voisins câblés, sans échange de protocole.

## 6. Routeur et PC

Sur R1 dans la démo :

```text
enable
configure terminal
interface gi0/0.10
encapsulation dot1Q 10
ip address 192.168.10.1 255.255.255.0
no shutdown
exit
interface gi0/0.20
encapsulation dot1Q 20
ip address 192.168.20.1/24
no shutdown
end
show ip interface brief
show ip route
show running-config
```

Sur PC1 :

```text
ip address 192.168.10.10/24
ip gateway 192.168.10.1
ipconfig
ping 192.168.10.1
ping 192.168.20.10
```

PC2 doit disposer d'une adresse 192.168.20.0/24 et de la passerelle 192.168.20.1.
Le test valide aussi le retour. Les routes statiques, protocoles de routage, SVI de
management et ping émis par un switch/routeur ne sont pas implémentés.

## 7. DTP : négociation du trunk

Sur deux switches reliés, sélectionner le port du câble :

```text
enable
configure terminal
interface gi0/1
switchport mode dynamic desirable
end
show dtp interface gi0/1
show interfaces gi0/1 switchport
```

Sur le partenaire, utiliser `switchport mode dynamic auto` : le lien devient trunk.
Deux ports auto restent access ; desirable/auto et desirable/desirable deviennent trunk.
Un routeur ou PC ne négocie pas DTP. Les domaines VTP et timers ne sont pas modélisés.

Pour figer le trunk et désactiver la négociation :

```text
switchport mode trunk
switchport nonegotiate
```

Configurer alors le partenaire en trunk statique aussi. `no switchport nonegotiate`
réactive la négociation. Nonegotiate est refusé sur un port en mode dynamique.

## 8. DHCP, snooping, DAI et IP Source Guard

Le lab **DHCP / Sécurité** inclut deux pools et les ports trusted déjà configurés.
Les PC n'ont pas d'adresse. Dans chacune des consoles PC :

```text
ip dhcp
ipconfig
```

Puis PC1 peut pinguer l'adresse attribuée à PC2 (par défaut `192.168.20.21`).
La commande `ip release` ou `ipconfig /release` libère le bail ; `ipconfig /renew`
renouvelle la demande. Les phases DHCP sont des événements logiques, pas des paquets.

Configuration équivalente du pool VLAN 10 sur R1 :

```text
enable
configure terminal
ip dhcp excluded-address 192.168.10.1 192.168.10.20
ip dhcp pool USERS
network 192.168.10.0 255.255.255.0
default-router 192.168.10.1
dns-server 1.1.1.1 8.8.8.8
lease 0 1
end
show ip dhcp pool
show ip dhcp binding
```

`lease` accepte jours, heures, minutes. `no service dhcp` désactive le serveur,
`service dhcp` le réactive. L'interface routeur 802.1Q doit être configurée et joignable.
Le serveur n'alloue pas d'adresse exclue, déjà attribuée, de routeur, réseau ou broadcast.

Sur SW1 :

```text
enable
configure terminal
ip dhcp snooping
ip dhcp snooping vlan 10,20
ip arp inspection vlan 10,20
interface gi0/3
ip dhcp snooping trust
ip arp inspection trust
exit
interface range gi0/1 - 2
ip verify source
end
show ip dhcp snooping
show ip dhcp snooping binding
show ip arp inspection statistics
show ip verify source
```

Le port gi0/3 est l'uplink serveur ; si on retire `ip dhcp snooping trust`, les réponses
DHCP sont rejetées et aucun nouveau bail n'est attribué. Les ports utilisateurs restent
untrusted. Sur un réseau de plusieurs switches, configurer les trusts nécessaires sur
le parcours de retour du serveur.

DAI et Source Guard nécessitent une association valide IP/MAC/VLAN/port. Après `ip dhcp`,
changer l'adresse du PC avec `ip address 192.168.10.99/24` fait rejeter son test de
connectivité. Un poste configuré statiquement sans binding est aussi rejeté ; les ARP ACL
statiques ne sont pas implémentées. Le port routeur doit être trusted pour DAI car il
n'a pas de bail DHCP utilisateur. Les commandes `no ip dhcp snooping trust`,
`no ip arp inspection trust` et `no ip verify source` retirent les options sur un port.

Les étapes DHCP, la négociation DTP et les contrôles DAI/IPSG sont simplifiés, sans
véritables trames/paquets ni timers automatiques. Les baux/bindings ne sont pas sauvegardés ;
renouveler les adresses après réouverture. Voir les limites dans le README.

## Références de conception

Le comportement de vrais équipements est plus riche que ce modèle pédagogique :

- [Cisco — rôles et élection STP](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/lan-wan/b-lan-wan/m_lsw-span-tree-prot.html)
- [Cisco — EtherChannel / modes LACP](https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/lyr2-fwd/etherchannel/etherchannel-configuration-guide/m_ethernetchannel.html)
- [Cisco — trunks et VLAN autorisés](https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/lyr2-fwd/vlan/vlan-configuration-guide/configure-vlan-trunks.html)
