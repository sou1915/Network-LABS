# Network LABS

Prototype de simulateur réseau éducatif pour Linux, sans VM ni image constructeur.
Interface native Python/Tkinter et moteur indépendant de l'interface.

## Lancement sur Ubuntu

```bash
sudo apt install python3 python3-tk
git clone https://github.com/sou1915/Network-LABS.git
cd Network-LABS
python3 -m network_labs
```

Si le prototype est encore dans une pull request, sélectionner d'abord la branche
`prototype/linux-simulator` avec `git switch prototype/linux-simulator`.

## Essayer la démo

Une topologie PC1 / PC2 / SW1 / R1 apparaît au démarrage.
Sélectionner PC1, cliquer sur **Ping**, puis saisir `192.168.20.10`.
Le moteur vérifie les chemins aller et retour via les VLAN 10 et 20.
Cliquer sur un PC ou routeur : le panneau Inspecteur permet de modifier sa
configuration. Cliquer sur un câble pour modifier son mode et ses VLAN.
Choisir Câbler, puis cliquer sur deux équipements pour les relier.
Glisser les équipements pour réorganiser le schéma ; Supprimer retire la sélection.
Le ping affiche un marqueur animé sur le chemin calculé : jaune à l’aller,
vert au retour. Lecture, Pause, Étape et Rejouer contrôlent la visualisation ;
le curseur règle sa vitesse. Le tableau affiche les chemins et les diagnostics.
Les projets se sauvegardent et se rouvrent au format JSON.

## Périmètre exact

Ce premier prototype calcule la connectivité IPv4 de PC à PC avec VLAN,
liens access/trunk et routage connecté par un routeur. Il ne produit aucun
trafic sur le réseau réel. Un seul lien physique par PC/routeur est pris en
charge. Les VLAN autorisés sont modélisés sur les liens, pas encore sur deux
ports configurables séparément. Le trunk est simplifié : pas de VLAN natif.

Le résultat « ping » est une vérification de connectivité, pas encore une
simulation événementielle ICMP/ARP. Le marqueur animé représente le parcours
calculé ; il ne simule pas encore les échanges de paquets ni leur timing réel. Les tables MAC, l'apprentissage ARP,
les délais, les pertes, STP et les boucles Ethernet ne sont pas simulés.
La visite des chemins évite les boucles du graphe pour le calcul seulement.
Les passerelles elles-mêmes ne sont pas encore des cibles de ping.

À développer : interfaces physiques, moteur de trames/paquets avec horloge,
CLI, DHCP, routes statiques, OSPF, ACL/NAT, firewall et profils multi-vendeur.
Ces fonctionnalités ne sont pas annoncées comme disponibles dans cette version.

## Validation

```bash
python3 -m unittest discover -s tests -v
```
