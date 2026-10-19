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
Double-cliquer sur un PC pour changer son IP ou sa passerelle ; double-cliquer
sur le routeur pour modifier ses sous-interfaces. Glisser les équipements pour
réorganiser le schéma. Le bouton Relier accepte par exemple
`PC3 SW1 access 10` ou `SW2 SW1 trunk 10,20`.
Les projets se sauvegardent et se rouvrent au format JSON.

## Périmètre exact

Ce premier prototype calcule la connectivité IPv4 de PC à PC avec VLAN,
liens access/trunk et routage connecté par un routeur. Il ne produit aucun
trafic sur le réseau réel. Un seul lien physique par PC/routeur est pris en
charge. Les VLAN autorisés sont modélisés sur les liens, pas encore sur deux
ports configurables séparément. Le trunk est simplifié : pas de VLAN natif.

Le résultat « ping » est une vérification de connectivité, pas encore une
simulation événementielle ICMP/ARP. Les tables MAC, l'apprentissage ARP,
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
