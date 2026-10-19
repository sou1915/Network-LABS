# Network LABS · Switching Studio

Application native Linux pour construire des labs réseau **sans VM, sans images
IOS et sans trafic sur le réseau réel**. CLI inspirée IOS sur chaque switch et
routeur, CLI réseau simplifiée sur les PC. Interface et aide en français.

![Switching Studio](docs/studio.png)

## Démarrer sous Ubuntu

```bash
sudo apt install python3 python3-tk
git clone -b prototype/linux-simulator https://github.com/sou1915/Network-LABS.git
cd Network-LABS
python3 -m network_labs
```

Pour mettre une copie existante à jour :

```bash
git switch prototype/linux-simulator
git pull --ff-only
python3 -m network_labs
```

Python 3.10+ et Tkinter suffisent : aucune dépendance pip pour l'application.

## Espace de travail

- Cliquer sur un équipement de la bibliothèque puis dans la topologie pour le placer.
- Glisser les équipements ; molette pour zoomer ; clic milieu pour déplacer la vue.
- Choisir **Câbler**, cliquer sur deux équipements, choisir les ports physiques et le mode initial.
- **Double-cliquer sur un équipement pour ouvrir sa console CLI** dans un onglet dédié.
- Cliquer sur un switch : liste de ses 24 ports. Double-cliquer sur un port pour le configurer.
- Cliquer sur un câble pour inspecter et configurer chaque extrémité indépendamment ou le couper.
- Choisir le VLAN observé : root STP, liens bloqués, liens down et liens hors VLAN sont distingués.
- Lancer le ping depuis un PC, puis utiliser Lecture, Pause, Étape, Rejouer et le curseur de vitesse.
- Le journal donne le VLAN et les ports de chaque saut. Les consoles ont aide `?`, historique,
  suggestions avec Tab et éditeur de blocs multi-lignes, avec arrêt à la première erreur.
- Sauvegarder le projet en JSON (`Ctrl+S`). Les projets de l'ancien prototype sont migrés à l'ouverture.

Trois labs intégrés : **Inter-VLAN**, **Boucle STP**, **EtherChannel**.

## Ce que le moteur prend en charge

| Fonction | Configuration et effet |
|---|---|
| VLAN | Création, noms, suppression ; isolation par VLAN |
| Ports | Ports indépendants, interfaces/ranges, description, shutdown/no shutdown |
| 802.1Q | Access/trunk, listes allowed avec add/remove/all/none, VLAN natif |
| STP | Calcul convergé par VLAN, élection root, coûts, priorités de bridge/port, ports ROOT/DESG/ALTN |
| EtherChannel | Plusieurs câbles entre switches ; LACP active/passive, PAgP desirable/auto et mode on ; validation des membres ; redondance |
| Protection L2 | Port-security maximum, MAC, sticky, violation shutdown/restrict/protect ; BPDU Guard |
| MAC | Apprentissage simplifié sur les chemins traversés, consultation/effacement de table |
| Routeur | Sous-interfaces dot1Q, adresses IPv4, shutdown, routes connectées |
| PC | IPv4/passerelle par GUI ou CLI, ipconfig, ping PC et passerelle locale |
| Inspection | Running/startup config, VLAN, interfaces, trunks, STP, EtherChannel, port-security, voisins physiques |

Exemples complets et commandes : [docs/SWITCHING.md](docs/SWITCHING.md).

## Limites explicites

Ce projet ne reproduit **pas toutes les technologies de switching**, ni un IOS constructeur.
Une commande inconnue ou une fonctionnalité non implémentée est refusée ; elle n'est pas
acceptée pour donner l'impression de fonctionner.

Le moteur vérifie des chemins et fait un apprentissage MAC pédagogique. Il ne simule pas
encore les échanges réels ARP, BPDUs, LACP/PAgP PDUs, le flooding inconnu, les délais,
la convergence temporelle, les files de transmission ou les pertes. Les marqueurs animés
représentent les chemins calculés, pas une capture réseau. Les tables MAC ne pilotent pas
encore une commutation de trames événementielle.

`pvst` et `rapid-pvst` partagent le calcul de l'état convergé ; leur différence de temporisation
n'est pas simulée. PortFast se configure, mais n'accélère rien dans ce modèle sans timers.
BPDU Guard détecte un switch voisin depuis la topologie, pas à partir d'un BPDU émis.
L'agrégation vérifie la compatibilité et fournit la redondance, sans hash de flux ni simulation
de bande passante. Les voisins `show cdp/lldp neighbors` sont déduits des câbles.

Le simulateur bloque conservativement un trunk dont les deux VLAN natifs diffèrent ;
il ne reproduit pas la traduction potentielle du trafic non tagué par des équipements réels.
Pas de VLAN voix, VTP/DTP, MSTP, QoS, IGMP snooping, DHCP snooping/DAI, 802.1X,
DHCP, ACL/NAT, OSPF/BGP ou profils constructeur exacts pour l'instant.
Le routeur a un seul uplink physique, avec routage connecté et sous-interfaces 802.1Q.
Le ping est émis par un PC ; les interfaces de routeur ciblées doivent être dans son réseau local.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Les tests GUI sont exécutés si un écran X est disponible. Pour les inclure sans écran physique :

```bash
sudo apt install xvfb
xvfb-run -a python3 -m unittest discover -s tests -v
```

Ils couvrent la configuration via console, l'effet sur le ping, le contrôle d'animation,
les onglets CLI, les dialogues de configuration, la sauvegarde et les labs intégrés.
