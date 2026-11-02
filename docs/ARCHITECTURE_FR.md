# Comprendre les moteurs et la fidélité

Network LABS est un logiciel de simulation que nous programmons. Il ne contient
pas Windows, Ubuntu, IOS ou FortiOS. Le nom d'un modèle dans le catalogue ne
charge pas le système du fabricant.

Un laboratoire **natif expérimental séparé** permet maintenant d'exécuter des
containers Linux OCI/crun et de lancer des guests Firecracker fournis par
l'utilisateur. Ce mode utilise de vrais processus et un fabric veth/TAP ; il
ne convertit pas automatiquement les nodes du canvas ni leurs CLI constructeur.
Voir [micro-nodes natifs : installation et limites](HYBRID_APPLIANCES.md).

## Les trois couches

| Couche | Travail effectué | Ce qu'elle ne fournit pas automatiquement |
| --- | --- | --- |
| Python / Tk et pages web | Dessiner les nodes, formulaires, terminaux et gérer les projets | L'interface officielle de chaque firmware |
| Configuration et interpréteurs CLI | Lire les commandes implémentées et modifier les mêmes paramètres que la GUI | Un shell Windows/Linux ou un interpréteur IOS/FortiOS complet |
| Moteur réseau sélectionné | Calculer les transactions pédagogiques, ou exécuter les appliances Rust/Wasm compatibles | Tous les protocoles et toutes les fonctions des constructeurs |

## Ce qu'est Wasm ici

Nous écrivons une petite appliance en Rust. Elle est compilée en WebAssembly,
puis exécutée par Wasmtime. Chaque équipement possède sa mémoire et son état
séparés. Les endpoints utilisent smoltcp pour ARP, IPv4, ICMP et TCP. Le switch
exécute notre apprentissage MAC et notre commutation Ethernet.

Exemple : PC1 produit une requête ARP ; le câble virtuel transporte les octets
vers SW1 ; SW1 apprend une MAC et diffuse la trame ; PC2 répond avec sa pile
réseau. Python transporte les octets entre les ports et programme l'horloge.
Il ne remplace pas cette conversation par un résultat « ping réussi » calculé.

Wasm est donc une **machine d'exécution pour notre code**, avec limites mémoire
et fuel. Ce n'est pas une VM matérielle contenant un noyau ou un firmware de
marque. Il n'apporte ni le bureau Windows ni les pages FortiGate ni la CLI IOS.
Ces interfaces et leurs comportements doivent être programmés séparément.

Le backend Wasm actuel couvre un LAN simple, access VLAN 1, IPv4 statique /24,
ICMP et TCP echo/8080. Les instances sont recréées par test. Le moteur pédagogique
couvre davantage de fonctions LAN, mais par transactions abstraites. Les deux
backends sont explicitement sélectionnés ; une fonction Wasm absente ne bascule
pas silencieusement vers le modèle. Voir [WASM_PROJECT.md](WASM_PROJECT.md).

## Pourquoi des commandes manquent

Une commande réaliste a trois obligations : syntaxe correspondant au matériel,
validation des paramètres et effet correct sur la configuration ou le trafic.
Un terminal qui imprime simplement une réponse plausible n'est pas suffisant.
Le projet ne doit pas annoncer une commande comme fonctionnelle si son effet
n'est pas implémenté. Les syntaxes couvertes sont des sous-ensembles ; `help`
et [FIDELITY.md](FIDELITY.md) donnent leur périmètre.

Exemple FortiOS : `move 10 before 50` doit changer l'ordre d'évaluation des
policies sans changer leurs IDs. Le moteur applique maintenant cette séquence.
Une édition d'objet adresse reconvertit les règles qui le référencent. `set nat
enable` reste refusé car le NAT n'est pas implémenté.

Les commandes internes `firewall rule` et `firewall order` servent au format texte
canonique du simulateur et à ses formulaires génériques. Elles ne sont pas
proposées comme commandes FortiOS. Le formulaire FortiGate dédié transmet des
blocs `config firewall policy` ou `config firewall address` et en affiche l'équivalent CLI.

## Pourquoi toutes les GUI ne sont pas identiques au matériel

Changer une couleur ou le nom du menu ne suffit pas. Une reconstitution doit
fixer une référence de produit/version, retrouver sa navigation, ses formulaires,
ses objets, son ordre d'application et ses messages. Les étapes de travail doivent
agir sur les mêmes données que la CLI. Chaque famille demande donc un travail
distinct, en plus du moteur réseau.

La première page spécialisée est maintenant **FortiGate → Firewall Policy et
Addresses**, référencée à la famille FortiOS 7.4 : liste By Sequence, création,
édition, suppression, déplacement et objets IPv4 nommés. Elle est une
reconstitution partielle, pas une copie intégrale du firmware. Les autres pages
et familles conservent encore largement des formulaires partagés.

Le budget cible de 2 Gio RAM nous donne de la marge pour développer les moteurs
et interfaces. Il ne fournit pas les fonctions manquantes et ne garantit pas que
tous les OS/firmwares réels pourraient tourner ensemble dans ce budget.
