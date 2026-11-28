# Network LABS 1.0

La première version de Network LABS : construire un réseau dans l'atelier, comme dans Packet Tracer, puis le faire
tourner pour de vrai. Chaque équipement est une vraie machine Linux (une micro-VM Firecracker) ; les paquets traversent
de vrais noyaux, de vrais pare-feu et de vrais démons de routage.

## Ce qu'on peut faire

- **Construire** : poser des routeurs, switchs, pare-feu, postes et serveurs en un clic (56 modèles de 36 marques),
  les câbler en deux clics, enregistrer le projet.
- **Configurer** dans la CLI de chaque équipement (double-clic), avec l'aide « ? », la complétion et les messages
  d'erreur d'IOS : adresses, routes, VLAN et trunks, sous-interfaces (router-on-a-stick), SVI, OSPF, RIP, EIGRP, BGP,
  ACL, NAT statique et PAT, pools DHCP et relais DHCP, HSRP et VRRP, spanning tree, EtherChannel (LACP), port security
  et BPDU guard, services (DNS, web, NTP, Syslog, TFTP). Les CLI parlent aussi FortiOS, Junos, RouterOS et PAN-OS.
- **Gérer par le web** : chaque équipement a sa page de gestion, copie de celle du produit (IOS-XE, Catalyst,
  FortiGate, pfSense, OPNsense, PAN-OS, J-Web, WebFig…), et les postes ont un bureau Windows ou GNOME.
- **Tester** : ping, traceroute, nslookup, navigateur, capture de paquets (PCAP), et le **mode simulation**, qui montre
  chaque trame d'un ping câble par câble, couche par couche.
- **S'entraîner** : 12 missions guidées, notées sur la configuration et sur de vrais pings, et un mode panne
  (1 200 scénarios) où il faut trouver l'erreur.
- **Sans KVM** (Windows, macOS, ou Linux sans virtualisation) : l'atelier, les CLI, les `show`, le ping et la
  simulation fonctionnent sur le modèle du réseau ; seul le démarrage des vraies micro-VM demande Linux avec KVM.

## Installer

Ubuntu 24.04 (ou plus récent) avec la virtualisation activée (`/dev/kvm`), Python 3.12 ou plus récent :

```bash
sudo apt install -y git python3 python3-tk
```

```bash
git clone https://github.com/sou1915/Network-LABS.git
```

```bash
sudo apt install -y busybox-static e2fsprogs gcc libc6-dev iptables bird2 frr keepalived dnsmasq-base chrony
```

```bash
cd Network-LABS && python3 -m network_labs.appliances setup --download
```

```bash
python3 -m network_labs
```

`setup` vérifie la machine, télécharge Firecracker et le noyau des micro-VM (sommes SHA-256 contrôlées), construit le
disque des équipements et affiche les commandes `sudo` à copier s'il en manque. chrony devient aussi le client NTP de
la machine (à la place de systemd-timesyncd). Le même travail se lance depuis l'atelier : onglet Scénarios,
« 🛠 Préparer cet ordinateur ».

## Limites connues

- Pas encore d'IPv6 dans les micro-VM, ni de RADIUS, SNMP ou HTTPS à l'intérieur (ils existent sur l'ancien moteur à
  conteneurs).
- OSPF : zone 0 seulement, pas sur les sous-interfaces ; OSPF et BGP pas encore ensemble sur un même routeur.
- Switchs : spanning tree classique (pas Rapid PVST+ ni MST) ; pas encore de DHCP snooping, DAI ni IP Source Guard.
- Les règles de pare-feu ne s'appliquent qu'aux ports physiques, pas aux sous-interfaces.
- Les vraies micro-VM demandent Linux avec KVM.

La liste à jour : [STATUS.md](STATUS.md).

## Licence

GNU GPL, version 3 ou ultérieure. Les polices, icônes et feuilles de style reprises d'autres projets, avec leurs
licences, et les marques citées : [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
