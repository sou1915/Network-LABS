# Exécuter le projet dans Wasm

Le backend Wasm utilise désormais **la topologie principale**, avec les noms,
adresses IPv4, ports, câbles et shutdown du projet. Il ne s'agit plus uniquement
de la démonstration séparée PC1—SW1—PC2. Les fonctions du backend sont encore
limitées à un LAN Ethernet simple ; il n'exécute aucun noyau Linux/Windows invité
ou firmware constructeur.

## Ouvrir la version intégrée

Installer le runtime facultatif selon [MICRO_APPLIANCES.md](MICRO_APPLIANCES.md),
puis lancer depuis la racine du dépôt :

```bash
.venv-micro/bin/python -m network_labs --wasm-lan
```

Le bouton **Ouvrir le LAN Wasm** produit le même projet modifiable : client
Windows, switch Cisco et serveur Linux. Ce sont des profils d'interface, sans
leurs OS. Ajouter/déplacer les nodes et câbler dans Conception, puis tester dans
Simulation ou utiliser `ping <IPv4>` dans la CLI du poste. Les commandes réseau
Windows/Linux implémentées modifient la configuration canonique, qui est appliquée
à la prochaine exécution. Les formulaires et pages web utilisent le même modèle.

Sur un autre projet, sélectionner **Moteur du projet → Wasm · LAN**. Ce choix
est sauvegardé dans le JSON ; les anciens projets restent pédagogiques par
défaut. L'import/export texte conserve la configuration canonique mais pas encore
le choix du backend : le sélectionner après un import texte.

![Projet Wasm](wasm_project.png)

## Ce qui est exécuté

Le backend instancie la composante physique contenant la source, y compris les
équipements reliés par un câble désactivé. Les autres composantes ne sont pas
exécutées. Une liaison désactivée ou un port shutdown empêche la livraison.
Les trames Ethernet, ARP, ICMP et TCP sont produites et traitées par les invités,
avec apprentissage MAC dans le switch. Aucun chemin calculé par le moteur
pédagogique ne remplace un échec du backend Wasm.

Le panneau d'explication et l'animation suivent les observations des ports,
y compris les diffusions ARP. **Paquets / PCAP** ouvre un instantané figé avec
les noms de ports du projet et l'export des octets capturés. Une même trame peut
apparaître sur plusieurs liaisons. Le temps affiché suit une horloge virtuelle,
pas une mesure de RTT matériel. La carte présente les câbles et les états
administratifs, sans annoncer de root STP.

Les instances sont **recréées à chaque test** : caches ARP et table MAC ne
persistent pas entre commandes. Les Stores sont libérés à la fin ; seuls la
capture bornée et les compteurs restent consultables. Modifier la configuration
depuis le bureau invalide la capture courante. Les anciennes fenêtres de capture
restent des instantanés, sans prétendre refléter la nouvelle configuration.

Les MAC des endpoints sont attribuées selon les noms de leur composante.
`ipconfig`, `ip addr show` et les pages web affichent la MAC prévue pour l'instance,
cohérente avec la capture. Ajouter/supprimer un équipement peut changer cette
attribution au test suivant. Le guest ne fournit pas encore sa table MAC détaillée :
`show mac address-table` donne le nombre appris dans le dernier test et annonce
cette limite, sans afficher une table provenant du moteur pédagogique.

## Limites explicites

- LAN sans boucle active, access VLAN 1, IPv4 statique /24 dans un même sous-réseau.
- Une NIC par endpoint ; jusqu'à 256 équipements dans la composante exécutée.
- ICMP echo ou une connexion TCP echo/8080 par test, charge utile bornée à 512 octets.
- Pour TCP, activer `tcp/8080` dans les services du serveur. Dans ce backend,
  ce port correspond uniquement à l'application d'écho, quel que soit son libellé.
  Sans service activé, le port est fermé ; aucun HTTP ou autre application n'est exécuté.
- Routeurs, firewalls, trunks, VLAN autres que 1, STP, EtherChannel et protections
  avancées ne sont pas encore portés. Leur présence dans la composante
  est refusée avec un diagnostic, sans repli automatique.
- DNS, DHCP, 802.1X/RADIUS et multicast ne sont pas exécutés par le moteur
  pédagogique lorsque le projet est en mode Wasm.

Pour les fonctions avancées existantes, sélectionner explicitement **Pédagogique**.
Cette première intégration ne transforme pas les consoles en shells d'un OS
invité ; les sous-ensembles de commandes restent ceux documentés dans
[FIDELITY.md](FIDELITY.md).

## Budget mémoire et cycle de vie

Le **budget cible du programme complet est 2 Gio RSS**. Une nouvelle exécution
est refusée si le RSS mesuré avant instanciation atteint déjà ce seuil. Ce
contrôle préalable n'est pas une limite système dure : Python, Tk, les captures
et les invités peuvent allouer ensuite. Les limites par Store, les files et les
événements sont décrits dans [le guide du runtime](MICRO_APPLIANCES.md).
Les futures fonctions doivent être mesurées avant de garantir leur coût total.

Un essai de 100 requêtes successives sur le même projet, sans GUI, conserve
uniquement la dernière capture de 8 observations : RSS à 43,99 Mio après la
première et 42,34 Mio après la centième, dans l'environnement d'exécution.
Ce relevé vérifie le cycle de libération ; il ne prouve pas une limite de 2 Gio.
Les mesures détaillées sont dans
[`project_lifecycle.json`](../experiments/micro_appliances/results/project_lifecycle.json).

## Essai sans écran

Exécuter un projet JSON sauvegardé dans Wasm, indépendamment du backend enregistré :

```bash
.venv-micro/bin/python -m network_labs.micro_appliances project examples/wasm_lan.json --source PC1 --target 192.168.50.20 --pcap /tmp/project.pcap --json /tmp/project.json
.venv-micro/bin/python -m network_labs.micro_appliances project examples/wasm_lan.json --source PC1 --target 192.168.50.20 --protocol tcp --port 8080
```

Le code de retour vaut 0 si l'échange est vérifié, 1 en cas d'échec ou de fonction
non prise en charge. Le rapport JSON conserve la trace, les explications, les
compteurs et le décodage des trames. Un PCAP n'est créé que si une exécution a
produit une capture ; une erreur préalable n'exporte pas la capture d'un autre test.

Validation : 154 tests, dont 24 GUI sous Tk 8.6/Xvfb. L'intégration vérifie le
choix/persistance du backend, les configurations CLI, coupures/reconnexions,
TCP ouvert/fermé, absence de repli, configurations non portées, budget préalable,
cohérence MAC, captures figées et invalidation. Interface inspectée à 1400×900
et 900×600 ; le panneau Simulation défile sur les petits écrans.
