# Network LABS

> Architecture cible : **une micro-VM Linux par nœud**, ressources réelles,
> CLI/web de l’équipement traduites vers le guest, et connexion future aux
> machines VMware/VirtualBox. Voir la [vision clarifiée](docs/PROJECT_VISION.md).
> La couverture OCI actuelle ne certifie pas encore cette architecture.


Laboratoire réseau pédagogique pour Linux : chaque équipement est une vraie
micro-VM Firecracker (routeurs, switches, firewalls, postes) avec la CLI et les
`show` de son constructeur, le terminal de chaque nœud, les missions, les pannes
et les scénarios générés. `python3 -m network_labs` ouvre directement l'atelier
(l'ancien simulateur « Switching Studio » a été retiré).

## Installation et lancement

Python **3.12 ou plus récent**, Tkinter et un environnement graphique Linux.
Sous Ubuntu/Debian/Mint :

```bash
sudo apt update
sudo apt install -y git python3 python3-tk
git clone https://github.com/sou1915/Network-LABS.git
cd Network-LABS
python3 -m network_labs
```

Pour une copie déjà installée :

```bash
git switch main
git pull --ff-only
python3 -m network_labs
```

Aucune dépendance pip/npm pour l'utilisation normale. Le navigateur local du
système ouvre les pages de gestion ; le logiciel doit rester actif.

Ou comme paquet Python (commandes `network-labs` pour l'atelier, `network-labs-lab` pour la ligne de commande) :

```bash
python3 -m venv --system-site-packages ~/.venv-network-labs
~/.venv-network-labs/bin/pip install ./Network-LABS
~/.venv-network-labs/bin/network-labs
```

### Windows et macOS : le mode modèle

L'atelier s'ouvre aussi sous Windows et macOS (Python 3.12 de python.org, qui inclut Tkinter), sans KVM :

```bash
git clone https://github.com/sou1915/Network-LABS.git
cd Network-LABS
python -m network_labs
```

(`py -m network_labs` sous Windows.) Le lab s'y construit et se configure comme dans Packet Tracer : double-clic sur
un équipement pour sa CLI (configuration IOS, `show`, `ping`, `traceroute`) et **✉ Simulation**, tout étant calculé
par le modèle du réseau. ▶ Démarrer, qui lance les vraies micro-VM, demande Linux avec KVM ; ailleurs, il explique le
mode modèle. Même chose sous Linux sans KVM pour un lab de micro-VM.

### Premier lancement des micro-VM (missions, pannes, scénarios)

Une seule commande vérifie la machine, télécharge Firecracker et le noyau
officiels épinglés (sommes SHA-256 contrôlées), construit un disque unique pour
tous les labs (agent, iptables, BIRD, FRR, keepalived, dnsmasq, chrony) et retient les chemins pour l'atelier. Elle
ne demande aucun droit : ce qui exige `sudo` est affiché comme commande à copier. chrony devient aussi le client NTP de
cette machine (à la place de systemd-timesyncd, comme sur Ubuntu 25.10).

```bash
sudo apt install -y busybox-static e2fsprogs gcc libc6-dev iptables bird2 frr keepalived dnsmasq-base chrony
python3 -m network_labs.appliances setup --download
```

Le même travail se lance depuis l'atelier : onglet Scénarios, bouton
« 🛠 Préparer cet ordinateur ». Il faut Linux avec `/dev/kvm` (virtualisation
activée dans le BIOS). Les scénarios VLAN demandent en plus le noyau Network LABS
(`tools/guest_kernel/build.sh`).

### Utilisation, comme dans Packet Tracer

L'atelier s'ouvre dans le design **noir & blanc** : fond blanc, équipements en tuiles noires (icône blanche), câbles
noirs ; à gauche une barre d'icônes (Topologie, Équipements · JSON, Scénarios, Outils, Simulation, Journal, ⚙
réglages) ; en haut le projet, le mode (Concevoir · Simuler · Lab en direct) et le grand bouton « ▶ Démarrer le lab » ;
sous le plan, le dock des équipements par catégorie, avec une recherche ; sur le plan, les outils (sélection, câble,
supprimer, zoom, tout afficher). Le voyant au coin de chaque tuile est plein quand l'équipement tourne, vide sinon.
« Lab en direct » remplace le dock par le journal (événements, sorties des commandes).
C'est le seul design : les anciens designs sombre (« Studio ») et clair en couleurs ont été retirés, et les pages web
de Network LABS (vue Network LABS, design Simple, bureau des PC) sont elles aussi en noir & blanc ; seules les copies des
interfaces des produits gardent leurs couleurs. `python3 -m network_labs --open projet.json` ouvre un projet au démarrage.

Une fois la machine préparée (`setup`, ci-dessous) :

1. **Ajouter** : cliquer (ou glisser sur le plan) un équipement du dock : routeur Cisco, Juniper, Huawei…, switch,
   pare-feu, PC. Il apparaît aussitôt, sans formulaire, ses ports non configurés.
2. **Câbler** : « Connecter un câble », puis cliquer les deux équipements (premiers ports libres ; Ctrl+clic pour
   choisir les ports).
3. **▶ Démarrer** (le projet s'enregistre tout seul dans `~/.local/share/network-labs/projects/`).
4. **Configurer** : double-clic sur un équipement ouvre sa CLI, tout de suite, même avant ▶ Démarrer : on tape ce
   qu'on veut. Lab arrêté, la configuration va dans le projet (appliquée au démarrage) et `show`/`ping` sont
   calculés par le modèle du réseau ; lab démarré, chaque commande s'applique à la micro-VM réelle (aucun autre
   mot de passe ; ↑/↓ historique, Tab complète, « ? » aide). Sur un routeur Cisco :
   `en`, `conf t`, `int g0/0/0`, `ip add 192.168.1.1 255.255.255.0`, `no shut`, `end` ; sur un PC :
   `ip addr add 192.168.1.10/24 dev eth0` et `ip route add default via 192.168.1.1`. Tout s'applique sur
   l'équipement en marche, sans redémarrer.

La fenêtre CLI se comporte comme celle de Packet Tracer : « Press RETURN to get started! », les ports d'un
nouveau routeur sont « administratively down » jusqu'au `no shutdown`, chaque ligne s'applique aussitôt,
`?` donne les mots suivants (`<cr>` quand la commande est complète), les erreurs sont celles d'IOS
(`% Invalid input detected at '^' marker.`, `% Incomplete command.`), Ctrl+Z, `wr`, `--More--`.
Les commandes Cisco du CCNA sont reconnues : configuration de base et sécurité (`hostname`, `enable secret`,
`service password-encryption`, `banner motd`, `line con 0` / `line vty`, `username`, SSH), interfaces
(`interface range`, `description`, `speed`, `duplex`), adressage, routes statiques, OSPF, BGP, DHCP, VLAN et
trunks, listes d'accès nommées et numérotées, `show version`, `show cdp neighbors`, `show interfaces`,
`copy run start`, `show startup-config`, `| include` / `| section`, RIP (`router rip`, `network`,
`passive-interface`, routes `R` dans `show ip route`), le NAT statique (`ip nat inside source static`), les pools
(`ip nat pool`, `… list N pool P [overload]`) et le PAT (`ip nat inside` / `outside`,
`ip nat inside source list N interface X overload`, `show ip nat translations`) et, sur un switch en marche,
`vlan N` / `name`, `switchport access vlan N`, `shutdown`, l'interface de gestion `interface vlan 1` / `ip default-gateway`
(`show vlan brief`, `show interfaces status`), et `traceroute`
(routeurs) / `tracert` (PC, comme dans Packet Tracer), `ipconfig` / `arp -a` sur les PC, `show arp` / `show mac address-table`, `telnet` / `ssh -l` vers un routeur ou un switch
(`line vty`, `login local`, `username`, `crypto key generate rsa`, `access-class`), et le relais DHCP `ip helper-address` (avec un pool pour un LAN
distant, `show ip dhcp binding`), qui agissent pour de vrai. Un routeur sert un pool DHCP par LAN ou par VLAN (plusieurs
`ip dhcp pool`, par exemple un par sous-interface d'un router-on-a-stick), modifiables à chaud.
EIGRP (`router eigrp`, routes `D`, `show ip eigrp neighbors`) agit aussi pour de vrai, comme le spanning tree des
switchs : un second câble entre deux switchs ferme une boucle et allume le STP 802.1D du noyau de chaque switch (un port
passe en `BLK`, orange sur le schéma ; un port `shutdown` y est rouge), `spanning-tree vlan 1 root primary` / `priority N`, `spanning-tree cost` / `port-priority` changent
l'arbre, `show spanning-tree` le montre (calculé d'après les câbles tant que le lab est arrêté), et couper le port racine
fait passer le câble de secours en `FWD`. Un seul arbre pour tous les VLAN (celui du VLAN 1), en STP classique (pas de
Rapid PVST+). Chaque port de micro-VM a une adresse MAC fixe, d'un démarrage à l'autre.
Chaque micro-VM a jusqu'à 16 ports (un 2960 de la bibliothèque arrive avec Fa0/1 à Fa0/16) ; un port sans câble
est `notconnect`, comme sur un vrai switch.
Le bouton **✉ Simulation** fait comme le mode simulation de Packet Tracer : choisir la source et l'adresse de
destination, puis « Capture / Avancer » (ou « Lecture ») : chaque trame du ping avance sur les câbles du schéma
(ARP en orange, puis ICMP en magenta ; une croix rouge là où le paquet est abandonné), avec la liste des événements,
les en-têtes de chaque trame (MAC, 802.1Q, IP, TTL, ICMP) et ce que fait l'équipement qui la reçoit. Le chemin est
celui que calcule `ping` (routes, VLAN, trunks, spanning tree, NAT, ACL), lab arrêté ou en marche.
L'EtherChannel aussi : `channel-group 1 mode active` (ou `passive`) sur deux ports, `interface port-channel 1` pour
ses réglages, `show etherchannel summary` (Po1(SU), ports (P)) ; les deux câbles forment un seul port pour le
spanning tree, et le LACP tourne pour de vrai entre les micro-VM (noyau Network LABS). Le groupe se met en place au
▶ Démarrer (pas encore à chaud) ; seulement en LACP (pas de mode on ni PAgP).
Un Catalyst 9200L est un switch de niveau 3 : `ip routing` et une `interface vlan N` par VLAN routent entre les VLAN
sans routeur (routage inter-VLAN, `show ip route` avec ses réseaux `C`, `ip route` vers un routeur) ; un 2960 reste
de niveau 2 et refuse `ip routing`, comme dans Packet Tracer.
La sécurité des ports agit pour de vrai sur les switchs : `switchport port-security` (`maximum`, `mac-address sticky`,
`mac-address H.H.H`, `violation shutdown|restrict|protect`) met un port en `err-disabled` (ou écarte le PC en trop),
`spanning-tree bpduguard enable` coupe un port qui reçoit un BPDU ; `show port-security [interface | address]`,
`show interfaces status`, et `shutdown` puis `no shutdown` pour rétablir le port, comme sur IOS.
HSRP aussi, sur les routeurs : `standby 1 ip 192.168.1.1`, `standby 1 priority 110`, `standby 1 preempt`
(`timers`, `authentication`, `standby version 2`) ; les routeurs élisent l'actif pour de vrai, il répond pour l'adresse
virtuelle avec la MAC 0000.0c07.ac01, et le standby prend la relève si l'actif tombe (`show standby`, `show standby brief`).
VRRP de même (`vrrp 1 ip 192.168.1.1`, `vrrp 1 priority 110`, `no vrrp 1 preempt`, `timers advertise`, `authentication
text`, `description`, `shutdown`) : le master annonce le groupe (protocole IP 112), répond avec la MAC 0000.5e00.0101, et un
backup prend la relève s'il se tait ou démissionne ; l'adresse même du port fait du routeur le propriétaire (priorité 255)
(`show vrrp`, `show vrrp brief`).
Celles qui n'agissent pas encore sur le trafic du lab (portfast, IPv6, NTP, SNMP, logging…) sont
acceptées et gardées dans la configuration ; le catalogue de commandes le précise. Pour **toutes** les commandes d'un vrai Cisco, il faudra une image Cisco
officielle (étape suivante : images constructeur sous QEMU).
Les abréviations du constructeur sont acceptées (`int`, `ip add`, `no shut`, `sh ip int br`, `do …`), comme
les noms de ports usuels (`g0/0/0`, `gi0/0/0`, `GigabitEthernet0/0/0`). Le formulaire complet reste disponible
par un clic droit sur la bibliothèque ou « Édition › Ajouter (options avancées)… ».

### Taper les commandes : terminal et catalogue de commandes

Chaque nœud micro-VM se configure à la main dans son terminal (onglet CLI, « Ouvrir le terminal de … »), avec
l'invite et les modes de son constructeur (`R1(config-if)#`, `[R1-GE0/0/1]`, `admin@R2#`). Pour trouver une
commande :

- dans le terminal : `?` liste les commandes du mode, `show ip ?` celles qui commencent ainsi, `help bgp` un
  sujet avec ses exemples, Tab complète les mots ;
- dans l'atelier : « 📖 Catalogue de commandes » (sous le bouton du terminal) liste toutes les commandes du nœud
  sélectionné, par sujet, avec recherche et un exemple écrit avec ses ports et ses adresses, à copier.

Le catalogue ne contient que des commandes réellement acceptées : les tests passent chaque exemple dans
l'analyseur du terminal.

## Pages de gestion des équipements

Chaque équipement a sa page de gestion web locale (double-clic ou « Gestion web »), servie par le logiciel tant qu’il
reste ouvert ; elle partage le même projet que l’atelier et que la CLI.

**Gestion web**, dans le panneau du dispositif natif, ouvre une vraie page
locale dans le navigateur : interfaces, nom/IP/passerelle et état administratif
partagent le même brouillon que la GUI ; routes et politique pare-feu sont
modifiables dans les éditeurs dédiés : filtrage IPv4 ordonné, NAT, routes,
VLAN/access/trunk/SVI, STP/protections BPDU, LACP apparié, LLDP, admission MAC, DHCP snooping/DAI/IP Source Guard,
sous-interfaces, IPv6 et DHCP/DNS selon le rôle.
Enregistrer puis arrêter / démarrer pour activer les changements.
Par défaut, la page est une copie de l'interface du produit réel (design **Constructeur**) : ses menus, ses mots,
ses tableaux, ses fenêtres d'édition et sa façon d'enregistrer :

| Produits | Interface reproduite | Enregistrement |
|---|---|---|
| Cisco ASA | ASDM (Access Rules, NAT Rules, interfaces nommées) | Apply |
| Cisco ISR 4331, Catalyst 9200L | WebUI IOS-XE | « Update & Apply to Device » (commandes IOS) |
| Cisco Catalyst 2960 | Device Manager (Port Settings, VLANs, Port Membership) | Submit (commandes IOS) |
| pfSense, OPNsense | leur interface web avec leurs propres feuilles de style publiées (pfSense : Bootstrap 3 + pfSense.css, Apache 2.0 ; OPNsense : son thème, BSD) : tableau de bord, Rules par interface, NAT Port Forward / Outbound, Assignments, Routing (Gateways, Static Routes), DHCP Server, General Setup | « Apply Changes » |
| Palo Alto | PAN-OS (Security, NAT Policy Rule, interfaces, zones) | Commit |
| Juniper SRX, EX, MX | J-Web (politiques, Source / Destination NAT, VLAN) | Commit |
| Sophos | Control center, Rules and policies, NAT rules, Network, Routing | Save |
| Check Point | Gaia Portal (IPv4 Static Routes) et SmartConsole (Policy, NAT) | Publish puis Install Policy |
| SonicWall | SonicOS (Access Rules, NAT Rules, Interfaces, Route Policies) | OK / Add |
| WatchGuard | Fireware Web UI (Firewall Policies, NAT, Routes) | SAVE |
| MikroTik | WebFig (`/ip address`, `/ip route`, Bridge) | OK (commandes RouterOS) |
| Huawei | web (interfaces, routes statiques, VLAN) | commandes VRP |
| Ubiquiti | EdgeOS (EdgeRouter, routes statiques), UniFi Network (switch) | Save / Apply Changes |
| TP-Link, NETGEAR, D-Link | Easy Smart, ProSAFE / Smart Pro, Web Smart (802.1Q VLAN, PVID) | Apply |
| Aruba | AOS-CX, Instant On | Apply |
| FortiGate | FortiOS | OK |
| Synology, QNAP | DSM (Control Panel › Network), QTS (Network & Virtual Switch) | OK / Apply |
| HP, Brother | Embedded Web Server (Networking), Web Based Management (TCP/IP Wired) | Apply / Submit |
| Axis, Yealink | AXIS OS (System › Network), page du téléphone (Network › Basic) | Save / Confirm |
| Dell, HPE, Lenovo | iDRAC, iLO, XClarity Controller (tableau de bord, inventaire, journal) | Virtual / Remote Console |
| Windows 11, Windows 10, Windows Server 2022 | bureau Windows : Paramètres › Réseau et Internet › Ethernet, Panneau de configuration › Connexions réseau › Propriétés TCP/IPv4, Invite de commandes (`ipconfig`, `ping`, `tracert`, `nslookup`, `curl`), Navigateur web, Gestionnaire de serveur | Enregistrer / OK |
| PC, serveur Linux | bureau du poste (Packet Tracer) : Configuration IP (DHCP ou fixe, passerelle, serveur DNS), Invite de commandes, Navigateur web ; sur un serveur, Services : HTTP (pages), DNS (enregistrements A, CNAME), NTP, SYSLOG, TFTP | Appliquer / Enregistrer |

**Services des serveurs (micro-VM).** Un serveur offre, comme celui de Packet Tracer, un site web, un serveur DNS
(enregistrements A et CNAME, réponses inverses), l'heure (NTP) et un collecteur Syslog ; un routeur Cisco aussi, en IOS
(`ip host` + `ip dns server`, `ntp master`, `ip http server`). Tout est réel dans la micro-VM : un PC fait `nslookup`,
`ping www.lab.local`, `curl http://www.lab.local/` ou ouvre la page dans son navigateur ; un routeur avec `ip name-server`
traduit les noms (`ping NOM`, `show hosts`), se synchronise avec `ntp server` (`show ntp status`, `show clock` sans « * ») et
envoie ses messages au serveur avec `logging host` (`show logging` ; `logread` ou l'onglet SYSLOG du serveur les affiche).
Le serveur a aussi un service TFTP : `copy running-config tftp:` sauvegarde la configuration d'un routeur (adresse puis nom du
fichier, comme sur IOS) et `copy tftp: running-config` la reprend. Sur un PC Windows, l'invite de commandes répond à `ping`,
`nslookup` et `curl` comme Windows.

Chaque page s'ouvre d'abord sur la page de connexion du produit, une fois par équipement et par onglet, avec ses
identifiants d'usine (admin / pfsense, root / calvin, ubnt / ubnt…) rappelés sous le formulaire.
Les produits sans interface web (VyOS, Nokia SR OS, Arista EOS, Dell OS10, Cisco NX-OS, Extreme EXOS) montrent leur
console et leur configuration. Les NAS, imprimantes, caméras et téléphones enregistrent leur adresse (DHCP ou fixe,
masque, passerelle) comme la « Configuration IP » d'un PC ; les cartes de gestion des serveurs ouvrent la console du
serveur. Les PC et serveurs Windows s'ouvrent sur leur bureau Windows : écran de verrouillage (un clic ou une touche),
fenêtres déplaçables, agrandies ou réduites dans la barre des tâches, clic droit, notifications, Terminal et
Explorateur à onglets. Polices et icônes libres publiées par Microsoft : Selawik (pour Segoe UI), Cascadia Mono (le
Terminal) et les Fluent UI System Icons (licence MIT) ; le bouton Démarrer dessine le logo Windows (quatre carrés ;
marque de Microsoft) ; le fond d'écran officiel n'est pas copié.
Ouverte sur un PC Windows, la page dessine les icônes système (boutons de fenêtre, zone de notification, menus, barres
d'outils, Paramètres) avec la police d'icônes de ce PC : Segoe Fluent Icons (Windows 11) ou Segoe MDL2 Assets
(Windows 10), les icônes mêmes de Windows ; la police n'est jamais copiée ni distribuée.
Les PC Linux s'ouvrent sur leur bureau GNOME : Ubuntu 24.04 avec ses icônes Yaru, la police Ubuntu Sans, son dock et son
fond d'écran ; Debian, Fedora et Rocky Linux avec le GNOME d'origine (icônes Adwaita, son fond d'écran, Cantarell). Ce sont
les fichiers mêmes des distributions, repris de leurs paquets avec leurs licences (assets/linux). Barre du haut et réglages
rapides, Paramètres › Réseau (connexion câblée : IPv4 automatique (DHCP) ou manuel, DNS) enregistrés dans le projet,
Terminal dont chaque ligne s'exécute sur le PC (ip a, ip route, ping -c, traceroute, nslookup, curl), Fichiers et navigateur.
Le menu Network LABS est dans la zone de notification ; clic droit sur Démarrer : le menu Win+X (Connexions réseau,
Terminal, Exécuter…) ; « Exécuter » ouvre ncpa.cpl, cmd, control. Les autres PC gardent le bureau Network LABS. Dessinées par
Network LABS, sans logo ni image du constructeur ; chaque modification passe par les mêmes vérifications que le reste
du laboratoire. Le bouton « ◉ Network LABS » (en bas à droite) ouvre le terminal, le design **Simple** (noir & blanc,
comme l'atelier) ou la vue Network LABS.
[Couverture par type de node et options restantes](docs/NODE_MANAGEMENT_ROADMAP.md).

## Documentation

- [Par où commencer](docs/README.md) : le plan de toute la documentation.
- [État actuel](docs/STATUS.md) : ce qui marche aujourd’hui, par fonction, et ce qui manque.
- [Release 1](docs/RELEASE_1.md) : le périmètre de la première version.
- [Conteneurs (OCI) et ligne de commande](docs/CONTAINERS.md) : l’autre moteur, gelé pendant la release 1.
- [Contribuer](CONTRIBUTING.md) : langues, style, tests et vérifications.

## Tests

Toute la suite (environ 1 500 tests ; ceux qui demandent KVM, root, un affichage ou Chromium s’ignorent seuls) :

```bash
xvfb-run -a python3 -m unittest discover -s tests
```

Les micro-VM réelles (KVM, Firecracker), les conteneurs, le fuzzing de l’agent invité et les pages dans Chromium sont
vérifiés par la CI ; [CONTRIBUTING.md](CONTRIBUTING.md) donne les commandes pour les lancer en local.

## Licence

Network LABS est un logiciel libre : GNU General Public License, version 3 ou (au choix) toute version ultérieure
([LICENSE](LICENSE)). Les polices, icônes, feuilles de style et images reprises d'autres projets gardent leur licence :
voir [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), qui liste aussi les marques citées.
