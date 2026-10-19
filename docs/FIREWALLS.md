# Firewalls LAN : types et support réel

Deux ports Ethernet transparents, règles IPv4 source/destination, protocole et
port de service, ordre par ID, modes stateful/stateless et politique par défaut.
La page web et le GUI bureau proposent l'édition et les compteurs du même moteur.

| Type | État | Couverture |
| --- | --- | --- |
| Filtre réseau stateless | Utilisable | Transactions ICMP/TCP/UDP ; retour à autoriser explicitement |
| Firewall réseau stateful | Utilisable | Retour de la transaction courante autorisé par état |
| Firewall transparent | Utilisable | Deux ports dans le même domaine L2, sans IP de gestion virtuelle |
| Firewall routé / zones L3 | Référence | Routage/zones à implémenter |
| Firewall hôte | Référence | Politique locale du poste à implémenter |
| NGFW / UTM | Référence | Inspection applicative, IPS, antivirus et filtrage web à implémenter |
| WAF / proxy applicatif | Référence | Analyse/terminaison HTTP à implémenter |

Les identités FortiGate, Palo Alto PA, Cisco ASA, pfSense, OPNsense, Sophos,
Check Point Quantum, SonicWall TZ et Juniper SRX partagent ce moteur. Elles ne
reproduisent pas leurs systèmes ou fonctions avancées. Des sous-ensembles de
syntaxe FortiOS et PAN-OS sont disponibles : voir [FIDELITY.md](FIDELITY.md).
Les autres consoles constructeur ne sont pas implémentées.
Le catalogue n'est pas exhaustif.

## Grammaire interne du simulateur

Ces commandes servent aux imports et aux profils génériques. Elles ne sont
pas des commandes à taper dans une console FortiOS/PAN-OS.

```text
firewall mode stateful
firewall default deny
firewall rule 10 allow udp 192.168.10.10/32 192.168.10.2/32 53
firewall rule 20 allow tcp 192.168.10.10/32 192.168.10.20/32 445
firewall rule 30 deny tcp any any 554
firewall rule 40 allow icmp 192.168.10.10/32 192.168.10.20/32
show firewall
show firewall sessions
show firewall counters
firewall rule delete 20
```

IDs 1..65535 : la première règle correspondante décide, sinon la politique par
défaut s'applique. `any` représente tous les réseaux, protocoles ou ports selon
le champ. Un ID existant est remplacé après validation. L'ancienne syntaxe
`firewall rule ID allow|deny SOURCE DESTINATION` reste compatible et signifie
ICMP uniquement. Les règles persistantes contiennent protocole et port.
`tcpudp` correspond à TCP ou UDP sur le même port (par exemple DNS/53).

L'état est limité à la transaction en cours et réinitialisé au test suivant,
sans suivi de connexions réel ni timers. Le port est le port du service sur les
deux jambes, sans port client éphémère. Les compteurs mesurent les décisions de
test, pas des paquets réels. DHCP, multicast et protocoles L2 ne sont pas filtrés
par ces règles de transactions. Pas de NAT, VPN, HA, routage, IPS/antivirus ou
inspection L7. Le bridge utilise le moteur L2 pédagogique partagé ; un chemin
physique contournant le firewall contourne également sa politique.

Voir [simulation des services](SERVICES.md) et [gestion web](WEB.md).

![Éditeur web de politique](web_firewall.png)
