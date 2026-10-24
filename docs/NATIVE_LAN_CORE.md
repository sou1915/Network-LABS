# Premier moteur LAN natif — sans dépendance à la GUI

Objectif de ce jalon : une configuration de base qui agit correctement sur de
vrais paquets, avec erreurs explicites et sauvegarde/restauration. Le scénario
de référence contient **8 containers** : 4 PC, 2 switches, un routeur et un serveur
DHCP. La validation à 20 nodes et le budget global de 2 Gio restent des étapes
ultérieures ; les allocations du manifest ne constituent pas un benchmark.

## Architecture et périmètre

| Fonction | Exécution |
| --- | --- |
| IP, routes connectées, interfaces | Pile réseau Linux dans chaque namespace |
| Switch access/trunk | Bridge Linux avec VLAN filtering ; PVID et egress tagging configurés par port |
| Routage inter-VLAN | Interfaces Linux 802.1Q et forwarding IPv4 dans R1 |
| DHCP | Serveur BusyBox `udhcpd` et client `udhcpc` persistants dans les containers |
| Configuration IOS-style | Adaptateur explicite `ios-basic`, traduit vers le manifest puis le kernel |
| Lecture opérationnelle | `inspect` retourne interfaces/routes/VLAN/FDB réels du kernel |
| Sauvegarde | Manifest startup durable dans `/var/lib/network-labs/<lab>/startup.json` |

Ni Cisco IOS ni les images jointes par l'utilisateur ne sont exécutés par ce
mode. Les noms et commandes suivent un **sous-ensemble documenté** ; ce jalon ne
revendique pas la conformité complète à un modèle/version Cisco. Les moteurs
pédagogique et Wasm ne sont pas utilisés pour décider si un ping natif réussit.

## Lancer le scénario de référence

Utiliser le même dossier du dépôt et le rootfs BusyBox déjà préparé lors du
premier essai. Le rootfs précédent reste utilisable : DHCP appelle directement
`/bin/busybox`, sans imposer de le reconstruire.

```bash
cd ~/Network-LABS
git fetch origin
git switch feature/hybrid-appliance-runtime
git pull --ff-only

python3 -m network_labs.appliances example --campus \
  --rootfs "$HOME/network-labs-rootfs" > campus-lan.json
python3 -m network_labs.appliances plan campus-lan.json
sudo python3 -m network_labs.appliances start campus-lan.json
sudo python3 -m network_labs.appliances inspect campus-lan PC1
sudo python3 -m network_labs.appliances exec campus-lan PC3 -- /bin/ping -c 3 10.20.20.40
```

DHCP est asynchrone : PC1 peut encore attendre une offre au retour de `start`.
Reconsulter `status`/`inspect` ; un tableau DHCP vide n'est pas un bail réussi.
Le client continue ses tentatives et renouvelle son bail tant que le lab tourne.

### Adressage et câblage

| Node | Interface / alias | Configuration |
| --- | --- | --- |
| PC1 | eth0 → SW1 fa0/1 | DHCP, VLAN 10, pool 10.10.10.100–150 |
| PC2 | eth0 → SW1 fa0/2 | 10.20.20.20/24, passerelle 10.20.20.1, VLAN 20 |
| PC3 | eth0 → SW2 fa0/1 | 10.10.10.30/24, passerelle 10.10.10.1, VLAN 10 |
| PC4 | eth0 → SW2 fa0/2 | 10.20.20.40/24, passerelle 10.20.20.1, VLAN 20 |
| SW1 ↔ SW2 | fa0/3 ↔ fa0/3 | Trunk, VLAN 10 et 20 autorisés ; native VLAN 1 non autorisée |
| R1 → SW1 | fa0/0 → fa0/4 | Trunk, R1 fa0/0.10 et fa0/0.20 |
| R1 | fa0/0.10 / fa0/0.20 | 10.10.10.1/24 et 10.20.20.1/24 |
| SRV1 → SW2 | eth0 → fa0/4 | 10.10.10.2/24, DHCP pour le VLAN 10 |

Dans les switches, fa0/1..fa0/4 correspondent à eth0..eth3. Les alias ne changent
pas le nom réel du device Linux. Le numéro de sous-interface et son VLAN sont
deux valeurs distinctes ; l'encapsulation doit être configurée pour être active.

## Configurer le réseau pendant qu'il tourne

Chaque bloc est parsé et validé **entièrement avant tout changement**. Une
commande inconnue, un champ erroné ou une configuration finale invalide interdit
son application. Une erreur système pendant l'application déclenche une tentative
de rollback du node ; si celle-ci échoue, l'état reste explicitement en échec.

Exemple : couper le trunk vers le routeur avec une commande IOS-style supportée :

```bash
cat > trunk-down.cfg <<'IOS'
enable
configure terminal
interface FastEthernet0/4
shutdown
end
IOS
sudo python3 -m network_labs.appliances configure campus-lan SW1 --file trunk-down.cfg
sudo python3 -m network_labs.appliances exec campus-lan PC3 -- /bin/ping -c 1 -W 1 10.20.20.40
```

Le ping inter-VLAN doit échouer. Le même bloc avec `no shutdown` rétablit le
trunk. Aucune animation ou commande « lancer simulation » n'est nécessaire.

### Sous-ensemble `ios-basic`

| Contexte | Commandes couvertes |
| --- | --- |
| Navigation | `enable`, `configure terminal`/`conf t`, `interface <alias>`, `vlan <id>`, `exit`, `end` |
| Switch access | `switchport mode access`, `switchport access vlan <id>` |
| Switch trunk | `switchport mode trunk`, `switchport trunk native vlan <id>`, `switchport trunk allowed vlan <liste|all|none>` |
| Interface | `shutdown`, `no shutdown` |
| Routeur | `ip routing`, `no ip routing`, `ip address <IPv4> <masque>`, `no ip address` |
| Sous-interface routeur | `interface fa0/0.<numéro>`, `encapsulation dot1Q <VLAN>`, puis adresse IPv4 |

Les VLAN access doivent être déclarés dans `vlans` (ou créés par `vlan <id>` dans
le bloc). Un trunk ne transmet que l'intersection de sa liste autorisée et des
VLAN déclarés. Son native VLAN sert de PVID/egress untagged seulement si autorisée.
La création d'une sous-interface sans encapsulation est conservée comme état
déclaré incomplet ; aucun device VLAN actif ni adresse n'est revendiqué pour elle.

Différences/limites explicites :

- Pas d'abréviations IOS générales, d'aide `?`, de shell IOS interactif, de
  fidélité exhaustive des messages `show`, d'authentification console ou de firmware.
- Passer de access à trunk ou inversement réinitialise ici les attributs propres
  au mode ; les paramètres inactifs conservés par un vrai IOS ne sont pas modélisés.
- Pas de `allowed vlan add/remove/except`, de `encapsulation ... native`,
  ni de pools DHCP en syntaxe IOS dans ce jalon. Les routes statiques CLI et les SVI Linux sont décrites plus bas.
- DHCP se configure dans le manifest. Le live adapter refuse les nodes qui
  portent eux-mêmes un service/client DHCP ; il ne prétend pas reconfigurer ce daemon.
- Le bridge Linux ne reproduit pas tous les détails d'acceptation des trames d'un
  ASIC Cisco. L'encodage d'une commande n'est pas une preuve de conformité matérielle.
- RSTP nécessite le backend OVS optionnel décrit plus bas ; les autres constructeurs restent à porter. DNS local et LLDP sont décrits plus bas. LACP et STP classique Linux sont décrits plus bas. Le firewall/NAT
  Linux IPv4 est décrit plus bas ; il n’utilise pas la syntaxe IOS.
  Les boucles avec STP désactivé restent refusées ; les activer via un manifest STP cohérent, jamais par commandes brutes.

## Manifest étendu

Le scénario généré sert de référence complète. Les anciens manifests v1 restent
lisibles ; le scénario étendu utilise v2. Les principaux champs sont :

```json
{
  "vlans": [1, 10, 20],
  "switchports": {
    "eth0": {"mode": "access", "vlan": 10},
    "eth1": {"mode": "trunk", "native_vlan": 1, "allowed": [10, 20]}
  },
  "shutdown": [],
  "dialect": "ios-basic",
  "interface_aliases": {"fa0/1": "eth0", "fa0/2": "eth1"}
}
```

Pour un routeur :

```json
{
  "forwarding": true,
  "subinterfaces": {
    "eth0.10": {"parent": "eth0", "vlan": 10, "address": "10.10.10.1/24"}
  }
}
```

Un serveur DHCP expose un objet `dhcp_server` : interface numérotée, `start`,
`end`, `router` optionnel, `dns` optionnel et `lease_seconds`. Un client utilise
`dhcp_clients: ["eth0"]`, avec adresse vide et sans passerelle statique.
La première version limite le pool à 256 adresses et le client à une interface.
Le relay DHCPv4 limité est décrit plus bas. Pas de DHCPv6 ou serveur DNS fourni automatiquement. Les réservations explicites MAC/IP sont décrites plus bas.

## Sauvegarder, arrêter et restaurer

```bash
sudo python3 -m network_labs.appliances save campus-lan
sudo python3 -m network_labs.appliances export campus-lan --startup > campus-saved.json
sudo python3 -m network_labs.appliances stop campus-lan
sudo python3 -m network_labs.appliances restore campus-lan
```

`save` vérifie les adresses, état administratif, forwarding, routes et memberships
VLAN gérés avant d'écrire le manifest startup. Un changement effectué directement
avec `exec ... ip ...` est une opération avancée hors suivi déclaratif : s'il
diverge de ces paramètres, `save`/`export` refusent une sauvegarde périmée.
Ils ne reconstruisent pas automatiquement une configuration constructeur depuis
toute modification arbitraire du kernel. Les scripts `startup` personnalisés qui
modifient le réseau doivent également rester cohérents avec le manifest.

`stop` supprime l'état d'exécution dans `/run` et les overlays/disques temporaires.
Le manifest sauvegardé dans `/var/lib` survit ; `restore` recrée le réseau depuis
ce manifest et les assets de base toujours disponibles. Les fichiers écrits à la
main dans les containers, les leases, compteurs et sessions ne sont pas snapshotés.
Les modifications faites après le dernier `save` sont perdues au restore.
Le `start fichier.json` explicite utilise ce fichier, pas automatiquement le startup.

En cas d'échec ou d'interruption de la configuration :

```bash
sudo python3 -m network_labs.appliances status campus-lan
sudo python3 -m network_labs.appliances recover campus-lan
```

`recover` tente de réappliquer le dernier état déclaré avant l'opération interrompue.
Cela peut interrompre brièvement les liens ; aucune atomicité sans coupure réseau
n'est annoncée. Si le problème persiste, inspecter les erreurs avant `stop`.

## Critères de validation réelle

Le job CI natif exécute les opérations suivantes, sans moteur pédagogique :

1. Démarrer les huit containers et obtenir un bail DHCP réel dans le pool.
2. Vérifier connexions dans le même VLAN et routage entre VLAN 10 et 20.
3. Désactiver le routage : inter-VLAN échoue, même VLAN continue.
4. Mettre un PC dans le mauvais VLAN : même sous-réseau IP ne contourne pas l'isolation.
5. Retirer VLAN 20 du trunk du routeur : trajet routé échoue, trajet L2 valide continue.
6. Vérifier coupure/reprise par `shutdown`/`no shutdown`.
7. Refuser un bloc invalide sans appliquer son `shutdown` précédent.
8. Sauvegarder, détecter une modification IPv4 brute non suivie, arrêter et restaurer
   le startup sauvegardé avec de nouveaux processus et un nouveau bail DHCP.
9. Vérifier que les routes de l'hôte et les ressources hors lab restent intactes.

```bash
python3 -m unittest discover -s tests -p test_native_lan.py -v
sudo env NETWORK_LABS_NATIVE_TESTS=1 python3 -m unittest discover \
  -s tests -p test_native_integration.py -v
```

## Références techniques

- [Cisco Catalyst 2960, IOS 15.2(2)E — VLAN trunks](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst2960/software/release/15-2_2_e/configuration/guide/b_1522e_2960_2960c_2960s_2960sf_2960p_cg/b_1522e_2960_2960c_2960s_2960sf_2960p_cg_chapter_01101.html)
- [Cisco IOS 12.4 — Routing between VLANs](https://www.cisco.com/en/US/docs/ios/12_4/lan_switch/configuration/guide/confvlan.html)
- [Linux bridge, VLAN/PVID/untagged](https://man7.org/linux/man-pages/man8/bridge.8.html)
- [Linux ip-link, VLAN et bridge](https://man7.org/linux/man-pages/man8/ip-link.8.html)
- [BusyBox, commandes et DHCP](https://busybox.net/downloads/BusyBox.html)

Les références Cisco guident le sous-ensemble syntaxique et ses résultats
attendus ; les versions/plateformes ne sont pas interchangeables et aucun test
comparatif sur IOS réel n'est revendiqué ici.

## Managed Linux firewall: IPv4 forwarding and NAT

The `firewall` node policy drives real nftables inside that node's owned network
namespace. It is a Linux policy backend, not vendor firmware or a FortiOS/ASA
command emulator. Input/output filtering, IPv6, VPN, application inspection,
hardware offload and vendor-specific features are not implemented here.

Host prerequisites: `nftables` (`nft`); install `conntrack` for session inspection
and clearing. Node rootfs does not need either host binary or its libraries.
Policy installation precedes links and IPv4 forwarding during startup; failure
aborts startup and cleans up. No host firewall table is modified.

```bash
python3 -m network_labs.appliances example --firewall --rootfs /opt/network-labs/busybox-rootfs > firewall-lan.json
sudo python3 -m network_labs.appliances start firewall-lan.json
sudo python3 -m network_labs.appliances exec firewall-lan PC1 -- /bin/ping -c 3 198.51.100.10
sudo python3 -m network_labs.appliances inspect firewall-lan FW1
sudo python3 -m network_labs.appliances sessions firewall-lan FW1
sudo python3 -m network_labs.appliances save firewall-lan
sudo python3 -m network_labs.appliances stop firewall-lan
sudo python3 -m network_labs.appliances restore firewall-lan
```

The sample has PC1 → FW1 → SRV1, with no LAN return route on SRV1. Outbound
ICMP and TCP/80 are allowed; other new forwarded traffic is dropped. Source
masquerading supplies the WAN return path. WAN TCP/8080 is translated to
PC1 TCP/80; an HTTP server must actually be started on PC1 to serve requests.
The sample deliberately starts no HTTP services automatically.

Each policy has `default` (`drop` or `accept`), `stateful` (boolean), ordered
`rules` and ordered `nat` arrays. A filter rule has a unique `name`, an `action`
(`accept` or `drop`) and optional `in`, `out`, `source`, `destination`,
`protocol` (`any`, `tcp`, `udp`, `icmp`) and `dport`. IPv4 CIDRs are normalized;
ports require TCP or UDP. Rules match forwarded packets after DNAT and before
source NAT. Invalid conntrack state is dropped first. With `stateful: true`,
established/related packets are accepted before user rules, including replies.

NAT entries share the match fields and have a unique `name` and `type`:

| Type | Required fields | Current scope |
| --- | --- | --- |
| `masquerade` | `out` | Source address selected from numbered/DHCP outbound interface |
| `snat` | `out`, `to` | Explicit configured outbound interface IPv4 address |
| `dnat` | `in`, `destination`, `to` | Optional `to_port` with TCP/UDP `dport`; no `out` match before routing |

To update, write the **policy object only** to a JSON file, then run:

```bash
sudo python3 -m network_labs.appliances firewall firewall-lan FW1 --file policy.json
```

The validated policy is checked and replaced with one nftables batch. Updates
retain conntrack entries; existing established flows and NAT mappings may keep
their previous behavior. To deliberately disrupt/reset sessions for a test:

```bash
sudo python3 -m network_labs.appliances clear-sessions firewall-lan FW1
```

NAT itself uses conntrack even when `stateful` automatic reply acceptance is
disabled. NAT counters count flow setup rather than every translated packet.
`inspect` exposes actual kernel rules and counters. Save/export detect ruleset
changes across the firewall namespace, including extra tables, while ignoring
traffic counter increments. Saved startup includes policy, not sessions,
counters, DHCP leases or filesystem contents. Untracked `startup` commands
cannot be combined with a managed firewall policy. Legacy explicit-startup
firewall nodes remain available without declarative firewall guarantees.

The opt-in native integration test starts real HTTP servers and checks default
deny, ordered deny, established replies, masquerade, explicit SNAT, DNAT,
policy edits, drift refusal, startup restore and preservation of host rules/routes.
The total-application 2 GiB target remains unverified; the 20-node headless
benchmark below reports narrower, explicitly scoped measurements.

Primary references: [nftables manual](https://netfilter.org/projects/nftables/manpage.html),
[atomic replacement](https://wiki.nftables.org/wiki-nftables/index.php/Atomic_rule_replacement),
[NAT semantics](https://wiki.nftables.org/wiki-nftables/index.php/Performing_Network_Address_Translation_(NAT)),
[conntrack](https://www.netfilter.org/projects/conntrack-tools/conntrack-manpage.html).

## Scénario intégré à 20 nodes et mesure RAM/CPU

`example --enterprise` génère **12 PC + 4 switches + R1 + FW1 + DHCP1 + WAN1**.
Les switches sont reliés en chaîne sans boucle, avec trunks VLAN 10/20.
Les PC impairs sont dans VLAN 10, les pairs dans VLAN 20. PC1 reçoit son adresse
par DHCP ; les autres ont une adresse statique. DHCP1 est en `10.10.10.2/24`.
R1 porte les passerelles `.1` des deux VLAN et route vers FW1 par le transit
`172.31.255.0/30`. FW1 possède les deux routes de retour vers R1, filtre les
flux sortants et fait du masquerade vers WAN1 (`198.51.100.10/24`). WAN1 n'a
pas de route de retour LAN. Le port FW1 TCP/8080 publie DHCP1 TCP/80 ; le
serveur HTTP doit être démarré explicitement. Aucun accès Internet n'est requis.

```bash
cd ~/Network-LABS
git fetch origin
git switch feature/hybrid-appliance-runtime
git pull --ff-only
sudo apt install -y crun iproute2 busybox-static nftables conntrack
python3 -m network_labs.appliances example --enterprise \
  --rootfs "$HOME/network-labs-rootfs" > enterprise-20.json
python3 -m network_labs.appliances plan enterprise-20.json

# Crée le lab, attend DHCP, mesure 5 s au repos puis 5 s sous ICMP, arrête le lab.
# Le fichier de rapport doit être nouveau ; choisir un autre nom pour répéter.
sudo python3 -m network_labs.appliances benchmark enterprise-20.json \
  --seconds 5 --target 198.51.100.10 --output benchmark-20.json
```

Cette commande refuse un lab déjà démarré, pour ne pas interrompre son travail.
Le rootfs doit avoir été préparé comme décrit plus haut. Pour des résultats
comparables, fermer les applications lourdes et arrêter les autres labs avant
le benchmark. La mesure ne ferme aucun autre programme. `--seconds` accepte
1 à 30 secondes **par phase** ; les sources par défaut sont les hôtes dont le
nom commence par PC. `--source PC1 --source PC12` permet une sélection explicite,
avec 16 sources maximum. La cible doit être une adresse statique déclarée dans
ce même lab. Chaque source envoie 10 pings/s pendant la durée demandée : avec
12 PC et 5 secondes, cela fait 600 requêtes ICMP, et leurs réponses attendues.
Ce test mesure une charge de connectivité limitée, pas le débit maximal.

Le résumé terminal donne le pic échantillonné de RAM des cgroups, CPU au repos
et sous charge, résultat des paquets et nettoyage. Le JSON complet inclut :

| Mesure | Ce qu'elle couvre | Limite d'interprétation |
| --- | --- | --- |
| Cgroup parent du lab | `memory.current`, swap et `cpu.stat` avec descendants | Ne pas ajouter une seconde fois les valeurs par node ; certaines allocations réseau/kernel et helpers sont ailleurs |
| PSS et CPU du runner | Processus Python de mesure | Pas la GUI finale ni tous les helpers transitoires ; PSS et mémoire cgroup ne sont pas deux termes directement additionnables |
| Host avant/après et pendant | `MemAvailable`, swap, ticks CPU globaux | Comprend les autres applications et l'activité de fond ; delta bruité, non attribuable exclusivement au lab |
| Chaque node après charge | Mémoire courante, swap, CPU cumulé et événements OOM | Photo après charge, pas un pic de RAM de chaque node |
| Paquets | Code retour, compteurs envoyés/reçus, sortie réelle de ping | Une perte rend le test négatif même si ping reçoit quelques réponses |

CPU du lab : `100 × Δusage_usec / (durée × 1 000 000)` ; **100 % = un cœur**,
et plusieurs cœurs peuvent dépasser 100 %. CPU host : pourcentage de capacité
CPU globale occupée, avec idle/iowait exclus. Les deux pourcentages n'ont pas
le même dénominateur. Les échantillons sont espacés d'environ 200 ms, excluent
le démarrage et peuvent manquer des pics brefs. Le temps de démarrage inclut
l'attente de disponibilité DHCP. La commande nettoie le lab même si la mesure
ou le trafic échoue ; en cas d'échec du nettoyage, l'état reste pour diagnostic.

Les limites configurées font 20 × 64 Mio + 512 Mio de réserve = **1792 Mio** ;
c'est une vérification d'allocation, pas une consommation mesurée ni une limite
globale imposée. Le rapport garde `total_application_under_target: unverified`,
même si le pic cgroup est inférieur à 2048 Mio. Il faut encore mesurer la GUI,
les services plus lourds et les futurs backends avant de valider le budget total.
Le benchmark ne sauvegarde aucune session ni configuration de lab à sa fermeture.

### Routes statiques du manifest

Un node OCI numéroté ou un switch Linux avec SVI peut déclarer jusqu'à 128 routes IPv4 :

```json
"routes": [
  {"destination": "10.10.10.0/24", "gateway": "172.31.255.2", "interface": "eth0"},
  {"destination": "10.20.20.0/24", "gateway": "172.31.255.2", "interface": "eth0"}
]
```

La passerelle doit être un voisin utilisable sur l'interface indiquée. Les
préfixes sont uniques, sans remplacement d'un réseau directement connecté.
La route par défaut reste le champ `gateway`. Les routes sont appliquées au
kernel et vérifiées avant `save`/`export`, puis recréées par `restore`. L’adaptateur
`ios-basic` fournit maintenant le sous-ensemble `ip route` décrit ci-dessous. Les
commandes brutes `exec ... ip route` ne modifient pas le manifest.

Références : [cgroup v2 : mémoire et CPU](https://docs.kernel.org/admin-guide/cgroup-v2.html),
[/proc : MemAvailable, CPU et PSS](https://docs.kernel.org/filesystems/proc.html).

### Première mesure CI (20 octobre 2026)

[Rapport complet](benchmarks/enterprise-20-ci.json), commit `f0f9e86`,
[Actions 39469314404](https://github.com/sou1915/Network-LABS/actions/runs/39469314404).
Linux `7.0.0-1017-azure`, x86_64, 4 CPU logiques ; 2 secondes par phase :

| Mesure échantillonnée | Repos | ICMP parallèle |
| --- | ---: | ---: |
| RAM du cgroup parent du lab, pic | 4,953 Mio | 7,910 Mio |
| CPU du cgroup du lab, moyenne (100 % = un cœur) | 0 % | 1,036 % |
| PSS du runner Python, pic séparé | 19,882 Mio | 19,884 Mio |

Les 12 PC reçoivent 20/20 réponses chacun : **240/240** au total. Aucun OOM ni
swap du lab n'est observé ; démarrage avec disponibilité DHCP en 3,83 secondes.
Le delta global de RAM du host est négatif sur ce court essai, ce qui illustre
le bruit de fond et ne permet aucune attribution de mémoire totale au lab.
Ces chiffres portent sur BusyBox et une charge faible, sans GUI ni firmware ;
ils ne prédisent pas la consommation sur le PC de l'utilisateur ni sous charge lourde.

## Port-channels LACP Linux et trunks VLAN

Le scénario `example --lacp` crée **4 PC + 2 switches**. Chaque switch a un
port access VLAN 10, un port access VLAN 20 et deux liens physiques membres de
`bond1` (port-channel 1). Les VLAN 10/20 passent sur le trunk logique. Les
membres ne sont pas attachés individuellement au bridge et n'ont pas de
configuration `switchports` autonome. SW1 est LACP active, SW2 passive.

```bash
cd ~/Network-LABS
git switch feature/hybrid-appliance-runtime
git pull --ff-only
# Prérequis explicite : charger le driver sans créer bond0 sur l'hôte.
sudo modprobe bonding max_bonds=0
python3 -m network_labs.appliances example --lacp \
  --rootfs "$HOME/network-labs-rootfs" > lacp-lan.json
sudo python3 -m network_labs.appliances start lacp-lan.json
# Attendre quelques secondes pour la négociation, puis inspecter.
sudo python3 -m network_labs.appliances inspect lacp-lan SW1
sudo python3 -m network_labs.appliances inspect lacp-lan SW2
sudo python3 -m network_labs.appliances exec lacp-lan PC1 -- /bin/ping -c 3 192.0.2.20
sudo python3 -m network_labs.appliances exec lacp-lan PC2 -- /bin/ping -c 3 198.18.0.20
```

Le gestionnaire exige un driver bonding déjà chargé et ne lance pas `modprobe`.
Il ne décharge pas un module utilisé par d'autres réseaux et ne configure aucun
bond dans le namespace de l'hôte. Un kernel/iproute2 sans prise en charge des
options demandées fait échouer le démarrage avec nettoyage, sans substitution.
Le driver nécessite un support vitesse/duplex des interfaces (veth dans ce lab).

Extrait du manifest d'un switch :

```json
"port_channels": {
  "bond1": {"members": ["eth2", "eth3"], "mode": "active", "min_links": 1}
},
"switchports": {
  "eth0": {"mode": "access", "vlan": 10},
  "eth1": {"mode": "access", "vlan": 20},
  "bond1": {"mode": "trunk", "native_vlan": 1, "allowed": [10, 20]}
}
```

Port-channels : `bond1` à `bond32`, au plus 16 par switch, 2 à 8 membres chacun,
mode active ou passive, `min_links` entre 1 et le nombre de membres. Chaque
membre doit être relié à un membre du même port-channel voisin ; pas de MLAG,
de membre sans lien ni de paire passive/passive. Les numéros de groupe sont
locaux et peuvent différer entre les deux switches. Les liens d'un bundle
complet sont traités comme une seule arête pour le contrôle de cycles. Tout
cycle L2 nécessite le STP commun sur tout le composant (section suivante).
**RSTP est disponible uniquement via le backend OVS optionnel décrit plus bas.**

Le backend configure bonding en mode 802.3ad, miimon 100 ms, lacp_rate fast,
xmit_hash_policy layer2+3. `inspect` lit `/proc/net/bonding/bond1` et netlink,
expose les états actor/partner, `negotiated_members`, `ready` et la sortie kernel
complète. Un membre n'est déclaré négocié que si actor et partner sont tous
deux synchronisés et en Collecting/Distributing, avec lien opérationnel/MII up
et appartenance à l'agrégateur actif. Les anciens bits LACP conservés par le
kernel sur un lien tombé ne suffisent pas. `ready` demande aussi le seuil
min-links et le carrier du bond. Ce résultat est lu du kernel, pas inféré d'un
ping ou des seuls paramètres du manifest. Le démarrage `running` n'attend pas
la convergence LACP. Le benchmark ICMP générique n'attend que DHCP et les
processus : inspecter la convergence avant les tests manuels LACP.

### Configuration live partielle

Les membres sont définis dans le manifest au démarrage. La CLI partielle peut
éditer la politique VLAN et shutdown du port-channel, le shutdown de chaque
membre, le seuil et le mode d'un bundle existant. Elle ne crée/supprime pas ses
membres pendant le fonctionnement. `channel-group ... mode` s'applique au mode
du bundle Linux entier, pas à un mode distinct pour chaque membre. Un changement
de mode/min-links interrompt temporairement ce bond (DOWN, paramètres, état
administratif déclaré) et peut nécessiter une nouvelle négociation ; les autres
interfaces ne sont pas volontairement interrompues.

```bash
# Couper un membre ; l'autre doit continuer à transporter les deux VLAN.
sudo python3 -m network_labs.appliances configure lacp-lan SW1 \
  --text $'configure terminal\ninterface fa0/3\nshutdown\nend'

# Exiger 2 membres : avec un membre coupé, le port-channel perd son carrier.
sudo python3 -m network_labs.appliances configure lacp-lan SW1 \
  --text $'configure terminal\ninterface port-channel1\nport-channel min-links 2\nend'

# Revenir au seuil 1 et réactiver le membre.
sudo python3 -m network_labs.appliances configure lacp-lan SW1 \
  --text $'configure terminal\ninterface po1\nno port-channel min-links\ninterface fa0/3\nno shutdown\nend'
sudo python3 -m network_labs.appliances save lacp-lan
sudo python3 -m network_labs.appliances stop lacp-lan
sudo python3 -m network_labs.appliances restore lacp-lan
```

Le mode d'un bundle existant se règle depuis un de ses membres avec
`channel-group 1 mode active` ou `passive`. Une édition qui créerait
passive/passive est rejetée avant mutation. Les commandes switchport se font
sur `interface port-channel1`/`po1`. Save/export vérifient les masters des liens,
les paramètres bonding, les VLAN et états administratifs ; les états négociés
et compteurs ne sont pas sauvegardés et peuvent évoluer sans dérive déclarative.

Il s'agit du comportement du bonding Linux, pas d'un ASIC Cisco ni d'un IOS
complet. PAgP, agrégation statique, hot-standby, priorités LACP, MLAG et garanties
de débit matériel ne sont pas fournis. Le fallback du driver lorsque son voisin
ne négocie plus dépend du kernel ; ce jalon ne configure pas `lacp_strict` et
ne revendique pas la politique Cisco de suspension d'un port individuel.
Un flux unique n'utilise pas simultanément tous les membres ; les tests ne
prouvent pas un doublement de débit ni une absence totale de perte à la panne.

Références : [Linux bonding](https://docs.kernel.org/networking/bonding.html),
[Cisco IOS XE 17 : EtherChannel](https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/lyr2-fwd/etherchannel/etherchannel-configuration-guide/m_ethernetchannel.html).

## STP commun 802.1D du kernel : boucles, root et chemins de secours

`example --stp` crée **6 PC et 3 switches** en triangle, avec les VLAN 10/20.
Chaque switch porte un PC par VLAN. Un arbre commun s'applique aux deux VLAN,
avec de vrais BPDUs, l'élection et les états de port du kernel Linux.
Aucun calcul de chemin dans Python ne décide quel port bloque ou transmet.

| Lien | Ports |
| --- | --- |
| SW1 ↔ SW2 | eth2/fa0/3 ↔ eth2/fa0/3 |
| SW1 ↔ SW3 | eth3/fa0/4 ↔ eth2/fa0/3 |
| SW2 ↔ SW3 | eth3/fa0/4 ↔ eth3/fa0/4 |
| PC de chaque switch | eth0/fa0/1 : VLAN 10 ; eth1/fa0/2 : VLAN 20 |

Les priorités 4096/8192/12288 font élire SW1. Avec les coûts égaux, le port
SW3 eth3 vers SW2 bloque les données. PC1/PC3/PC5 sont respectivement
192.0.2.10/.20/.30 ; PC2/PC4/PC6 sont 198.18.0.10/.20/.30.
Le scénario utilise hello=1 s, max_age=6 s et forward_delay=4 s pour raccourcir
les essais. **Cela reste du STP classique**, avec listening puis learning,
pas du RSTP. La convergence initiale prend environ deux forward_delay, et une
panne peut ajouter des délais de détection/expiration. `running` ne garantit
pas que l'arbre a convergé ; inspecter les états avant les pings.

```bash
cd ~/Network-LABS
git switch feature/hybrid-appliance-runtime
git pull --ff-only
python3 -m network_labs.appliances example --stp \
  --rootfs "$HOME/network-labs-rootfs" > stp-lan.json
sudo python3 -m network_labs.appliances start stp-lan.json
# Attendre environ 10 secondes, puis :
sudo python3 -m network_labs.appliances inspect stp-lan SW1
sudo python3 -m network_labs.appliances inspect stp-lan SW3
sudo python3 -m network_labs.appliances exec stp-lan PC1 -- /bin/ping -c 3 192.0.2.30
sudo python3 -m network_labs.appliances exec stp-lan PC2 -- /bin/ping -c 3 198.18.0.30

# Couper le chemin direct SW1–SW3 ; SW3 passe ensuite par SW2.
sudo python3 -m network_labs.appliances configure stp-lan SW1 \
  --text $'configure terminal\ninterface fa0/4\nshutdown\nend'
# Attendre la convergence et vérifier les deux VLAN, puis rétablir :
sudo python3 -m network_labs.appliances configure stp-lan SW1 \
  --text $'configure terminal\ninterface fa0/4\nno shutdown\nend'
```

### Manifest, configuration et inspection

```json
"spanning_tree": {
  "mode": "stp",
  "priority": 4096,
  "hello_time": 1,
  "max_age": 6,
  "forward_delay": 4,
  "ports": {
    "eth2": {"cost": 100, "priority": 128},
    "eth3": {"cost": 100, "priority": 128}
  }
}
```

`mode` vaut `off` (défaut) ou `stp`, exclusivement sur les switches OCI.
Les priorités de bridge sont des multiples de 4096, de 0 à 61440 ; celles des
ports des multiples de 16, de 0 à 240. Le coût vaut 1..65535. Les ports non
précisés reçoivent coût=100, priorité=128 lorsque STP est activé ; les membres
physiques d'un bond n'ont pas de politique propre, seule l'interface logique en a.
Linux encode la priorité des ports avec 10 bits de numéro de port : le backend
traduit la priorité proposée en priorité kernel divisée par 4 (128 → 32).
L'inspection expose la valeur normalisée et `kernel_priority` séparément.

Bornes des timers en secondes : hello=1..10, max_age=6..40, forward_delay=4..30,
avec `2*(hello+1) <= max_age <= 2*(forward_delay-1)`. Les défauts hors exemple
sont 2/20/15. Cette première version exige le même mode et les mêmes timers
sur tous les switches d'un composant connecté, même sans cycle, pour garder
un domaine de contrôle explicite et des vérifications de timers non ambiguës.
Un composant cyclique n'est accepté qu'avec STP activé partout. Les arêtes LACP
restent regroupées en une seule arête logique avant cette validation.

Le bridge est créé sans ports actifs, STP est activé et l'état kernel 1 vérifié
**avant** d'attacher/activer les ports. Les éditions ne passent pas par un
`stp_state 0` intermédiaire sur un bridge STP déjà activé. Root, root port et
blocking/forwarding restent le résultat des échanges et des timers du kernel.
Le gestionnaire ne démarre pas de service STP dans le namespace de l'hôte et
n'altère pas `/sbin/bridge-stp`. Aucun nouveau paquet Python n'est requis.

Changer la priorité d'un bridge :

```bash
sudo python3 -m network_labs.appliances spanning-tree stp-lan SW3 --priority 0
```

Une édition explicite de priorité/coût/politique STP invalide la FDB dynamique
du seul switch édité pour éviter de réutiliser une destination MAC sur un ancien
chemin. Les entrées statiques/permanentes restent en place. Une panne de lien
seule ne déclenche pas ce flush dans le gestionnaire : le kernel gère STP/TCN.

Une politique complète peut être fournie par `--file policy.json` à cette même
commande, avec validation du composant avant mutation, journal, rollback et
`recover` communs à la configuration réseau. Changer la priorité peut provoquer
une réélection ; le retour de la commande confirme l'application, pas la convergence.
Un changement de mode/timers incompatible avec les autres switches est refusé ;
modifier le manifest entier et recréer le lab pour changer le domaine complet.

Les commandes d'interface partiellement compatibles IOS sont également couvertes :

```bash
sudo python3 -m network_labs.appliances configure stp-lan SW2 \
  --text $'configure terminal\ninterface fa0/4\nspanning-tree cost 1000\ninterface fa0/3\nspanning-tree port-priority 64\nend'
```

Elles agissent sur ce **common spanning tree Linux**, pas sur une instance PVST
par VLAN. `spanning-tree mode rapid-pvst`, PVST/MSTP et PortFast ne sont pas fournis
dans ce jalon. Les protections BPDU/root du kernel sont décrites ci-dessous. Tous les VLAN d'un port bloqué
partagent son état : des listes VLAN divergentes peuvent rendre un VLAN inaccessible.
La GUI constructeur et un shell IOS complet restent hors de ce backend.

`inspect` ajoute `spanning_tree` : protocole effectif du kernel, bridge_id,
root_id, `is_root`, root_port, root_path_cost et états/cost/priorité de chaque
port. `local_state_settled` indique seulement l'absence de listening/learning
sur les ports locaux opérationnels ; ce n'est pas une preuve globale de
convergence. Les IDs sont lus dans sysfs du namespace (certaines versions de JSON iproute2
répètent l'ID local dans root_id), les états dans netlink. Aucun arbre n'est
déduit du dessin ou d'un résultat de ping.
Save/export détectent des différences de contrôleur STP, priorité, timers,
coûts et priorités de ports. Une réélection ou transition de port ne constitue
pas une dérive de configuration. Restore relance une nouvelle élection et ne
sauvegarde pas les MAC temporaires, rôles ou timers en cours.

Le benchmark générique attend DHCP et les processus, pas la convergence STP.
Pour mesurer ce scénario accéléré, une phase idle suffisamment longue est
nécessaire (par exemple `--seconds 20`) ; une phase trop courte peut mesurer
une perte pendant la convergence. Une réélection peut aussi nécessiter l'expiration des anciennes entrées FDB.
Les tests vérifient la récupération bornée de paquets après convergence.
Les tests de panne ne revendiquent ni
bascule instantanée, ni absence de perte sur un flux continu.

### Protections BPDU Guard et Root Guard du bridge Linux

Chaque port de `spanning_tree.ports` accepte deux booléens indépendants,
`bpdu_guard` et `root_guard`, tous deux désactivés par défaut. Ils nécessitent
STP actif et s'appliquent au port logique du bridge, donc au bond entier pour
un port-channel, jamais à ses membres physiques. Aucun daemon supplémentaire.

- `bpdu_guard: true` applique `bridge link ... guard on`. Une BPDU reçue
  désactive réellement le port dans le moteur STP Linux : `state: disabled`.
  Le lien peut rester administrativement UP. Ce n'est pas une émulation de
  l'état Cisco err-disabled et aucun timer de récupération automatique n'est fourni.
- `root_guard: true` applique `root_block on`. Le port ne peut devenir root port.
  Avec des BPDUs supérieures répétées, le kernel peut le maintenir en
  listening en réarmant forward_delay : il ne transmet alors pas les données.
  Ce mécanisme peut aussi laisser un port en blocking ; une autre voie reste
  utilisable si elle existe. Il ne désactive pas toute réception de BPDUs.

Le cas habituel est de protéger les ports vers des équipements en aval non
fiables, sans empêcher les uplinks prévus d'atteindre le root. Activer ces
protections sur tous les uplinks peut isoler le switch. `inspect` expose les
flags effectifs du kernel et l'état du port, sans inventer une cause ou un
compteur de déclenchement. `local_state_settled` reste faux lorsqu'un port
opérationnel est désactivé par le moteur ou maintenu en listening par Root Guard ;
examiner les protections et les liens.

Exemple de déclenchement volontaire sur le lien redondant de SW3 :

```bash
sudo python3 -m network_labs.appliances configure stp-lan SW3 \
  --text $'configure terminal\ninterface fa0/4\nspanning-tree bpduguard enable\nend'
# Après réception d'une BPDU, inspect SW3 : eth3 doit être disabled.
# Retirer la protection, puis cycler explicitement le lien pour récupérer :
sudo python3 -m network_labs.appliances configure stp-lan SW3 \
  --text $'configure terminal\ninterface fa0/4\nspanning-tree bpduguard disable\nshutdown\nend'
sudo python3 -m network_labs.appliances configure stp-lan SW3 \
  --text $'configure terminal\ninterface fa0/4\nno shutdown\nend'
# Après convergence, eth3 redevient blocking dans le triangle initial.
```

Les commandes d'interface `spanning-tree guard root` et `spanning-tree guard none`
activent/retirent Root Guard ; `no spanning-tree guard root` retire également
cette protection. `no spanning-tree bpduguard enable` retire BPDU Guard.
Le parseur valide tout le bloc avant application. Les flags sont persistés dans
startup et vérifiés contre la configuration kernel lors de save/export.
L'état disabled/blocking déclenché par le protocole n'est pas une dérive.
Restore recrée les ports et attend de nouvelles BPDUs pour déclencher la protection.
Ne pas supposer qu'un port précédemment désactivé restera tel quel après restore.

L'intégration privilégiée teste une vraie isolation par Root Guard sur les deux
uplinks, puis par BPDU Guard, des pings négatifs et positifs dans les VLAN 10/20,
la récupération, la détection de drift et le déclenchement après save/restore.
Les tests STP et STP/LACP précédents restent exécutés sans protection par défaut.
Référence : [attributs de ports du bridge Linux](https://docs.kernel.org/networking/bridge.html#bridge-port-netlink-attributes),
`IFLA_BRPORT_GUARD` et `IFLA_BRPORT_PROTECT`, et
[br_root_port_block du kernel](https://github.com/torvalds/linux/blob/master/net/bridge/br_stp.c).

### Limite du backend Linux bridge pour RSTP

Le bridge Linux historique implémente STP classique. Un daemon tel que `mstpd`
implémente RSTP, mais requiert un bridge en mode **userspace STP**, différent
`stp_state=2` du `stp_state=1` kernel. Le mécanisme traditionnel `/sbin/bridge-stp`
n'est appelé que dans le namespace réseau initial ; un simple `stp_state 1`
dans nos namespaces peut donc rester en STP classique malgré la présence de mstpd.
Les kernels récents proposent `IFLA_BR_STP_MODE=user` pour cette situation.
Il reste à valider ce support dans les couples kernel/iproute2 ciblés, puis la
supervision isolée de mstpd, sa défaillance, la mesure de ressources et de vrais
tests de BPDUs/reconvergence RSTP. Le backend Linux bridge refuse `mode: rstp` explicitement,
sans fallback silencieux, sans mise à niveau automatique du kernel de l'utilisateur.

Références primaires : [bridge Linux](https://docs.kernel.org/networking/bridge.html),
[encodage des priorités de port](https://github.com/torvalds/linux/blob/master/net/bridge/br_stp_if.c),
[mstpd : utilisation avec VLANs](https://github.com/mstpd/mstpd/blob/master/README.VLANs.md),
[mstpctl](https://github.com/mstpd/mstpd/blob/master/utils/mstpctl.8).


## Diagnostic passif lisible : explain

Le diagnostic lit les mêmes états réels que `inspect`, plus `crun state` pour
vérifier que le conteneur tourne. Il ne démarre pas de lab, ne change pas la
configuration, ne cycle aucun port, n'écrit pas de rapport persistant et n'envoie
ni ping ni requête applicative. Les protocoles du lab continuent normalement.

```bash
# Un switch, en français lisible :
sudo python3 -m network_labs.appliances explain stp-lan SW3
# Tous les nodes du lab :
sudo python3 -m network_labs.appliances explain stp-lan
# Données structurées pour scripts et future interface :
sudo python3 -m network_labs.appliances explain stp-lan SW3 --json
sudo python3 -m network_labs.appliances explain lacp-lan SW1
```

Le texte regroupe les observations par équipement, avec INFO/WARNING/UNKNOWN :
interfaces manquantes, état administratif et carrier, root/chemin STP observés,
ports forwarding/blocking/listening/disabled, flags BPDU/root guard, membres
LACP réellement négociés et min-links, VLAN kernel/PVID/untagged, IPv4, adresses
présentes/absentes des clients DHCP, forwarding/routes et compteurs nftables.
Un lien de secours en blocking est informatif, pas automatiquement une panne.
Un LACP prêt avec moins de membres négociés est signalé comme dégradé.
Les données nftables se limitent à la table IPv4 gérée `network_labs`.

Ce diagnostic explique un **état courant**, pas une histoire d'événements :

- `bpdu_guard=true` avec `state=disabled` et un lien opérationnel est une
  corrélation observée, pas un événement de déclenchement certifié.
- Root Guard actif avec listening peut correspondre à des BPDUs supérieures ;
  ce seul relevé ne prouve pas la cause de l'état.
- Une IPv4 sur un client DHCP ne prouve pas son origine ni la validité du bail.
- Les compteurs firewall sont cumulatifs. Ils ne prouvent pas l'autorisation
  ou le rejet d'un ping précis ; les routes ne prouvent pas la joignabilité.
- `running`, des ports forwarding et un LACP prêt ne constituent pas une preuve
  de livraison. `packet_delivery` reste toujours `not_tested`.

Le JSON version 1 contient des timestamps UTC de début/fin, la révision, la phase,
`passive=true`, la source et le périmètre, `observation_complete`, les nodes et
leurs findings `{code, severity, message, evidence}`. Les codes sont destinés aux
scripts ; les messages sont en français (`language=fr`). Les relevés sont
successifs, pas atomiques entre équipements, sans certificat global de convergence.
`observation_complete` signifie seulement que les lectures sélectionnées ont
abouti, jamais que le réseau est sain ou conforme à toute sa configuration.
Utiliser save/export pour les contrôles de dérive existants.

Un conteneur arrêté, une lecture en échec ou un runtime sans agent invité reste
explicitement indisponible ; les autres nodes continuent à être décrits. Un lab
hors phase running n'est pas inspecté dans ses namespaces. Un nom de node inconnu
ou l'absence de fichier d'état du lab reste une erreur de commande.
Le code retour est 0 lorsqu'un rapport est produit, même avec des alertes ou
observations indisponibles, et 1 pour une erreur empêchant de produire le rapport.

Les tests natifs vérifient les explications contre de vrais états Root/BPDU Guard
et LACP prêt/dégradé/non prêt. Ils continuent à tester séparément les paquets et
à vérifier la récupération, la persistance et le nettoyage du lab.


## Capture PCAP réelle et bornée

`capture LAB NODE INTERFACE` lance le tcpdump de l'hôte dans le **namespace réseau
possédé par ce node OCI**. Installer les outils sur l'hôte, pas dans chaque rootfs :

```bash
sudo apt-get install tcpdump util-linux coreutils
python3 -m network_labs.appliances doctor
```

`doctor` liste `tcpdump`, `nsenter` et `timeout` parmi les outils détectés. Ils sont optionnels
pour le fonctionnement des labs ; seule la commande capture les exige. Aucun
fallback vers le réseau hôte et aucune installation automatique.

Terminal 1, avec le lab STP déjà running :

```bash
cd ~/Network-LABS
sudo python3 -m network_labs.appliances capture stp-lan PC1 eth0 \
  --seconds 15 --packets 100 --filter 'arp or icmp' --output pc1-lan.pcap
```

Attendre le message **Capture active** sur stderr, puis dans le terminal 2 :

```bash
cd ~/Network-LABS
sudo python3 -m network_labs.appliances exec stp-lan PC1 -- /bin/ping -c 3 192.0.2.30
```

La commande libère le verrou du lab pendant l'enregistrement : exec, configure,
explain et stop restent utilisables. Une fois terminée, le résumé JSON indique
le nombre de paquets réellement présents, la taille, le linktype, la limite,
le filtre et la raison d'arrêt. Lire le fichier dans Wireshark, ou avec :

```bash
tcpdump -nn -r pc1-lan.pcap
# Des BPDUs STP sur un trunk, sans générer de paquets de test :
sudo python3 -m network_labs.appliances capture stp-lan SW1 eth2 \
  --seconds 5 --packets 5 --filter 'ether dst 01:80:c2:00:00:00' --output stp-bpdu.pcap
```

Les paramètres sont contrôlés avant lancement :

| Option | Défaut | Limite |
| --- | --- | --- |
| `--seconds` | 10 | entier 1–60 s, démarrage inclus, puis nettoyage borné |
| `--packets` | 1000 | entier 1–10000 |
| `--snaplen` | 2048 | entier 64–65535 octets par paquet |
| `--filter` | vide | expression BPF de 512 caractères maximum, passée comme argument, jamais au shell |
| `--output` | obligatoire | nouveau fichier ; existant ou symlink refusé |

Le budget théorique PCAP `24 + packets * (16 + snaplen)` doit rester sous ou égal
à **16 MiB**. Aucune rotation ni écriture sans limite. Le fichier est créé en 0600 ;
sous sudo, son propriétaire devient SUDO_UID/SUDO_GID pour permettre la lecture
par l'utilisateur appelant. Sans ces variables, il reste au propriétaire du processus.
Une erreur de démarrage peut laisser un fichier vide ou partiel, jamais déclaré
comme une capture réussie. Choisir un autre nom lors d'un nouvel essai.

Le parent ouvre le descripteur du namespace sous le verrou du lab et le transmet
à `nsenter --net=/proc/self/fd/...` avant tcpdump, sous un watchdog GNU timeout indépendant. Ce descripteur empêche de capturer
accidentellement un autre namespace si stop supprime le nom pendant le démarrage.
Après stop, le namespace peut rester temporairement référencé par le processus
capture jusqu'à sa terminaison bornée. La suppression du port peut provoquer
une erreur libpcap et laisser une capture partielle ; aucun basculement vers l'hôte.
Le délai de fin envoie SIGINT, puis SIGKILL au groupe de capture si le processus
ne répond pas sous 2 s, avec une seconde attente de nettoyage de 2 s. Le watchdog
applique aussi le délai si le parent Python est tué ; stderr est conservé dans
un fichier temporaire anonyme pour éviter un SIGPIPE après cette disparition. Tuer le watchdog lui-même
est hors de cette garantie. Le code 124 du watchdog est interprété comme une fin
par durée, après validation du PCAP. Le parent attend ce watchdog avec 3 s de
grâce sans envoyer un deuxième SIGINT au même instant ; si le watchdog ne
termine pas, il tue le groupe puis retourne une erreur avec fichier partiel.
Ctrl-C après démarrage conserve un
PCAP valide si tcpdump le ferme correctement, avec `stop_reason=interrupted` et
un code retour CLI 130. Les erreurs retournent 1.

La capture ne demande pas le mode promiscuous (`-p`) et ne modifie pas les adresses,
VLANs, routes ou policies. Un bridge peut déjà avoir mis un port en promiscuous
pour son fonctionnement normal. Les interfaces acceptées sont celles déclarées
et présentes dans le node, ses bonds/sous-interfaces effectifs, lo et br0 pour un
switch ; `any` et les interfaces de l'hôte ne sont pas acceptées. Les invités VM
restent sans adaptateur de capture dans ce jalon.

Ce fichier décrit le trafic observé **au point de capture**. Snaplen peut tronquer
les données, le filtre peut les exclure, les offloads peuvent modifier la visibilité
des tags/checksums et br0/bond/membre physique peuvent donner des vues différentes.
Capturer sur un membre physique pour étudier ses trames de contrôle LACP ; ne pas
supposer qu'un capture point voit tous les échanges. Aucun replay ni analyse de
chemin globale n'est fourni. tcpdump consomme des ressources hôte hors des cgroups
des appliances ; le budget total application 2 GiB reste non validé.

Les tests natifs capturent de vrais ICMP request/reply pendant un exec CLI simultané,
relisent les trames avec tcpdump, capturent une vraie BPDU kernel, vérifient une
capture vide bornée et un filtre invalide, tuent le parent CLI pour vérifier le
watchdog, puis arrêtent un lab pendant capture.
Ils comparent routes/interfaces hôte et vérifient le maintien du mode promiscuous.
Références : [tcpdump](https://github.com/the-tcpdump-group/tcpdump/blob/master/tcpdump.1.in),
[format PCAP](https://github.com/the-tcpdump-group/libpcap/blob/master/pcap-savefile.manfile.in),
[nsenter](https://man7.org/linux/man-pages/man1/nsenter.1.html),
[GNU timeout](https://www.gnu.org/software/coreutils/manual/html_node/timeout-invocation.html).


## Compteurs de ports et comparaison VLAN entre switches

`inspect` lit maintenant les statistiques standard avec `ip -j -s -d link show`.
`explain` présente RX/TX paquets et octets, ainsi que les compteurs errors/dropped
non nuls, pour les interfaces déclarées, bonds, sous-interfaces effectives et br0.
Les données viennent de `stats64`, avec repli sur `stats` 32 bits s'il est absent.
Un champ absent/invalide reste `null` dans le JSON et `?` dans le texte ; une
lecture manquante ne devient jamais un zéro. Aucun compteur n'est réinitialisé.

```bash
# Compteurs et état d'un équipement :
sudo python3 -m network_labs.appliances explain stp-lan SW1
# Tous les équipements + comparaison des deux extrémités des liens switch-switch :
sudo python3 -m network_labs.appliances explain stp-lan
sudo python3 -m network_labs.appliances explain lacp-lan --json
```

Ces totaux sont cumulatifs, sans taux, différence temporelle ou pourcentage de
perte. Un RX ou TX positif ne certifie pas la réception par l'autre équipement.
Les drops/errors n'identifient ni leur cause ni un ping précis. Un drop VLAN ou
STP n'est pas forcément comptabilisé comme rx_dropped par le driver ; comparer
les paquets avec capture et les règles effectives si nécessaire. Ne pas sommer
les compteurs d'un bond, de ses membres, de br0 et des sous-interfaces : ils
peuvent compter les mêmes échanges à différents niveaux. Les totaux d'octets ne
constituent pas une mesure de consommation RAM ni de débit applicatif.

En sélection complète, `explain LAB` ajoute `link_checks` : une comparaison
passive des memberships VLAN **observés dans le kernel** aux deux extrémités de
chaque lien switch-switch déclaré. Les membres LACP sont regroupés sur leurs
ports logiques ; un bond à deux câbles donne une comparaison et deux liens
physiques dans l'evidence. La topologie provient du manifest : aucun voisinage
n'est découvert, aucun câble réel n'est certifié et aucun paquet n'est injecté.
Les liens vers PC/routeur/firewall, Q-in-Q, vlan_tunnel et la disponibilité globale
des chemins restent hors du périmètre de cette comparaison.

Pour chaque sens, la comparaison distingue :

| Code | Observation |
| --- | --- |
| `VLAN_TAGGED_NOT_ADMITTED` | Un VID envoyé taggé manque dans les memberships du port récepteur. |
| `VLAN_UNTAGGED_NO_PVID` | La sortie émet sans tag mais aucun PVID d'entrée n'est observé en face. |
| `VLAN_UNTAGGED_RECLASSIFIED` | Une trame untagged passe d'un VID local au PVID différent du récepteur ; vérifier si c'est intentionnel. |
| `VLAN_NO_MEMBERSHIP` | Une liste explicitement vide ne fournit aucun VLAN de données au port. |
| `VLAN_MEMBERSHIPS_COMPATIBLE` | Les memberships et le traitement tag/untagged comparés ne révèlent pas ces différences. |
| `VLAN_LINK_UNKNOWN` | Relevé absent, port détaché, filtrage désactivé, protocole non supporté ou données contradictoires. |

Un même VID des deux côtés ne suffit pas : egress untagged et ingress PVID sont
indépendants. Inversement, deux ports access de VID locaux différents peuvent
échanger des trames sans tag ; le rapport signale cette reclassification à
vérifier, sans affirmer automatiquement une panne. Une range VLAN est développée
avec ses flags PVID/untagged. Une absence d'enregistrement n'est pas interprétée
comme une liste vide connue. Le contrôleur doit confirmer br0, son master, le
filtrage actif et le protocole 802.1Q avant toute conclusion de compatibilité.
La comparaison porte sur les trames de données VLAN, pas les BPDUs/LACP réservés.

Le statut `compatible` porte uniquement sur ces memberships : un port STP blocking,
un bond non prêt, une interface arrêtée ou une autre règle peut toujours empêcher
le trafic. Les états STP/LACP/carrier observés figurent dans l'evidence pour le
contexte et restent expliqués séparément. `packet_delivery` demeure `not_tested`.
Les relevés sont successifs, sans snapshot atomique entre équipements.

Le JSON version 1 est enrichi de manière additive avec `selection`,
`link_check_scope`, `link_checks` et `link_checks_complete`. Ce dernier signifie
que toutes les comparaisons du périmètre ont abouti sans unknown, pas qu'elles
sont toutes compatibles. En sélection d'un node, il vaut `null`, la liste est
vide et aucun peer supplémentaire n'est lu ; utiliser la commande sans node
pour comparer les deux côtés. Les compteurs des findings incluent maintenant
également ceux des liens. Les observations indisponibles restent explicites.

Les tests natifs confrontent ces explications à une vraie perte du VLAN 20 après
restriction du trunk, à une sortie untagged sans PVID, puis à des PVID divergents.
Ils vérifient le retour des pings après correction, la réduction d'un LACP en une
seule comparaison et la présence de compteurs RX/TX réels. Les tests unitaires
couvrent ranges, reclassification voulue, observations partielles et compteurs
64/32 bits sans valeurs inventées.
Références : [statistiques Linux](https://docs.kernel.org/networking/statistics.html),
[bridge/PVID](https://docs.kernel.org/networking/bridge.html),
[flags VLAN iproute2](https://man7.org/linux/man-pages/man8/bridge.8.html).


## Débits passifs sur un intervalle

```bash
sudo python3 -m network_labs.appliances monitor stp-lan SW1 --seconds 5
sudo python3 -m network_labs.appliances monitor stp-lan PC1 eth0 --seconds 10 --json
```

Après le message de première lecture sur stderr, générer du trafic dans un autre
terminal avec `exec ... /bin/ping`. La commande lit deux fois les compteurs Linux
sans injecter de paquets ni modifier la configuration. Elle affiche les différences
RX/TX (paquets, octets, erreurs et drops) et des moyennes approximatives en pkt/s
et bit/s pour les ports gérés du node OCI. Sans interface, tous ses ports gérés
sont présentés séparément ; aucun total bond/membres/bridge n'est calculé.

`--seconds` attend de 1 à 30 secondes entre lectures. Le calcul utilise l'intervalle
monotone réellement observé entre les milieux des deux lectures, pas la durée
demandée. Les timestamps UTC, durées de lecture et révisions figurent dans le JSON.
Les snapshots sont successifs, pas atomiques. Les différences sont soustraites en
entiers avant le calcul des taux, même au-delà de 2**53. Ce ne sont ni un débit
applicatif, ni une mesure exacte du trafic sur le câble, ni un pourcentage de perte.
Une augmentation des erreurs/drops ne fournit pas sa cause ou le flux concerné.

Chaque lecture utilise un nouveau gestionnaire sous verrou ; le verrou est libéré
pendant l'attente pour laisser passer les commandes `exec`, `configure` et `stop`.
PID/starttime du conteneur, device/inode du namespace et ifindex/adresse/type/kind
de l'interface servent à détecter les changements d'identité. Une identité changée,
un ifindex manquant ou une source de compteurs 32/64 bits différente invalide les
taux du port. Toute diminution d'un compteur connu invalide toutes ses différences,
sans inventer une correction de wrap. Une métrique absente reste `null` ; les autres
peuvent être calculées avec statut `partial`. Deux relevés ne détectent pas un reset
suivi d'un rattrapage des valeurs, ni toutes les réutilisations d'identité.

Si la seconde lecture échoue, par exemple après `stop`, le rapport indique
`observation_unavailable` et laisse les différences/taux à `null`, sans remplacer
l'absence par zéro. Ce rapport reste une observation valide (code de sortie 0) ;
un démarrage invalide échoue avec code 1. Ctrl+C interrompt avec code 130 sans
fabriquer de rapport partiel. Aucun daemon, fichier d'historique ou dépendance
supplémentaire n'est ajouté. `packet_delivery` reste `not_tested`.

La validation native mesure de vrais pings pendant l'attente et arrête le lab
entre les deux lectures pour vérifier l'indisponibilité explicite. Les tests
unitaires couvrent les identités modifiées, diminutions, sources 32/64 bits,
valeurs manquantes, grands entiers et l'absence de verrou pendant l'attente.

## Port security statique sur ports access

Le sous-ensemble natif accepte une liste de **MAC source statiques** par port
access physique OCI. Il installe une table nftables `bridge
network_labs_port_security`, dans le namespace du switch, avec hook `prerouting`
avant la décision FDB. Pour chaque port protégé, une règle compte les trames dont
la source est autorisée ; la suivante compte et droppe les autres. Aucun filtre
IP n'est nécessaire : les trames de données ARP, IPv4 et IPv6 traversant ce hook
sont concernées. Les ports sans politique gardent leur comportement habituel.
Aucune règle du firewall de l'hôte n'est modifiée.

C'est une admission MAC statique, pas une implémentation complète de Cisco IOS :

- `maximum` vaut 1..64, et **exactement ce nombre de MAC statiques doit être
  fourni**. Les slots restants ne sont pas appris automatiquement. Un bloc
  incomplet est refusé avant mutation, même s'il contient `shutdown`.
- Seul `violation restrict` est implémenté : rejet et compteurs, sans shutdown,
  err-disable, syslog/SNMP ou timer de récupération synthétique. Ce sous-ensemble
  choisit restrict par défaut, contrairement au défaut de certains matériels.
- MAC unicast non nulle, format `aa:bb:cc:dd:ee:ff` ou `aabb.ccdd.eeff` ; une MAC
  ne peut pas être déclarée sur deux ports protégés du même switch/VLAN.
- Trunks, port-channels et membres LACP sont refusés. Dynamic learning, sticky,
  aging, voice VLAN et apprentissage sécurisé/FDB statique ne sont pas ajoutés.
- La règle contrôle la **source en entrée**, pas les destinations ou l'identité
  authentifiée d'une machine. Une MAC autorisée peut être usurpée. Les paquets
  de contrôle réservés que le bridge traite hors de ce hook ne sont pas couverts ;
  BPDU Guard reste une fonctionnalité séparée.

### Exemple prêt à tester

```bash
python3 -m network_labs.appliances example --port-security \
  --rootfs "$HOME/network-labs-rootfs" > port-security-lan.json
sudo python3 -m network_labs.appliances start port-security-lan.json
sudo python3 -m network_labs.appliances exec port-security-lan PC1 -- \
  /bin/ping -c 3 192.0.2.20
sudo python3 -m network_labs.appliances explain port-security-lan SW1
```

PC1 porte la MAC explicite `02:00:00:00:01:10`, autorisée sur SW1 fa0/1 (=eth0).
Changer réellement la source du PC simule une autre identité sur le même câble :

```bash
sudo python3 -m network_labs.appliances exec port-security-lan PC1 -- \
  /bin/ip link set dev eth0 address 02:00:00:00:01:99
sudo python3 -m network_labs.appliances exec port-security-lan PC1 -- \
  /bin/ping -c 3 -W 1 192.0.2.20
sudo python3 -m network_labs.appliances explain port-security-lan SW1
```

Le ping doit échouer et le compteur de rejet augmenter ; le port reste UP.
Autoriser explicitement cette seconde MAC dans un seul bloc :

```bash
sudo python3 -m network_labs.appliances configure port-security-lan SW1 \
  --text $'configure terminal\ninterface fa0/1\nswitchport port-security maximum 2\nswitchport port-security mac-address 0200.0000.0199\nswitchport port-security violation restrict\nend'
sudo python3 -m network_labs.appliances exec port-security-lan PC1 -- \
  /bin/ping -c 3 192.0.2.20
```

Le trafic doit reprendre. Pour retirer la politique : `no switchport
port-security` dans le contexte interface. Pour remplacer une MAC sans garder
l'ancienne, utiliser `no switchport port-security mac-address ANCIENNE`, puis
`switchport port-security mac-address NOUVELLE` dans le même bloc.

### Manifest, observations et persistance

```json
{
  "port_security": {
    "eth0": {
      "maximum": 1,
      "mac_addresses": ["02:00:00:00:01:10"],
      "violation": "restrict"
    }
  }
}
```

Sur les nodes OCI, `interface_macs` peut fixer les MAC physiques dès la création,
hors membres LACP (leur MAC appartient au bonding), par exemple
`"interface_macs": {"eth0": "02:00:00:00:01:10"}` sur PC1. Sans ce
champ, Linux choisit l'adresse ; un redémarrage peut donc la changer. La MAC
explicite est appliquée avant UP, vérifiée par save/export et réappliquée au
restore. Elle ne se configure pas dans cette CLI IOS partielle. La suppression
live d'une MAC explicite exige de recréer le lab.

`inspect` fournit la table effective, les compteurs de paquets/octets acceptés
et rejetés, et `fingerprint_matches`. La conformité compare la table à la
référence après application, en ignorant compteurs et handles ; des règles
absentes/modifiées font refuser save/export. L'existence d'une table seule ne
prouve pas sa conformité. `explain` expose `PORT_SECURITY_POLICY`,
`PORT_SECURITY_UNVERIFIED`, `PORT_SECURITY_COUNTERS` et `PORT_SECURITY_DROPS`.
Un compteur représente des trames cumulées, pas des équipements distincts, un
nombre de violations constructeur ou le résultat d'un ping précis. Les valeurs
indisponibles restent inconnues.

Une modification de politique remplace **atomiquement toute cette table du
switch**, et remet donc à zéro ses compteurs de port security. Un changement
sans modification de politique conserve les compteurs. Les autres tables nft
restent intactes. L'application participe au journal/rollback réseau existant ;
un rollback peut également remettre ces compteurs à zéro. Save/restore conserve
les listes statiques et les MAC déclarées, pas les compteurs. Après un changement
MAC expérimental hors manifest, remettre PC1 à sa MAC déclarée avant save :

```bash
sudo python3 -m network_labs.appliances exec port-security-lan PC1 -- \
  /bin/ip link set dev eth0 address 02:00:00:00:01:10
sudo python3 -m network_labs.appliances save port-security-lan
sudo python3 -m network_labs.appliances stop port-security-lan
sudo python3 -m network_labs.appliances restore port-security-lan
```

La validation native vérifie pings autorisés/refusés, absence d'apprentissage FDB
de la source rejetée, ajout d'une deuxième MAC, maintien du port UP, compteurs,
drift/refus de sauvegarde, retrait de politique et save/restore avec MAC stable.
Elle vérifie également l'intégrité des liens/routes/règles nft de l'hôte.
Références : [hook bridge nftables](https://wiki.nftables.org/wiki-nftables/index.php/Bridge_filtering),
[syntaxe nftables](https://netfilter.org/projects/nftables/manpage.html),
[port security Cisco, périmètre de comparaison](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/configuration_guide/sec/b_179_sec_9300_cg/port_security.html).

## DHCP snooping IPv4 : confiance et bindings observés

Le premier backend fonctionne sur **un switch OCI à ports access physiques**,
avec sélection de VLANs. Il combine deux fonctions distinctes :

- Filtre nftables `bridge network_labs_dhcp_snooping`, avant la décision FDB.
  Un port non déclaré trusted est untrusted. Sur un port untrusted appartenant
  aux VLANs sélectionnés, les datagrammes UDP source 67 et BOOTREPLY vers 67/68
  sont rejetés et comptés. Le serveur légitime doit entrer par un port trusted.
- Un observateur Python persistant par switch activé, dans son namespace, lit
  les paquets DHCP réels avec AF_PACKET et filtre BPF kernel, sans mode promiscuous
  demandé. Il corrèle DHCPREQUEST du client sur un port untrusted et DHCPACK sur
  un port trusted, avec VLAN, xid, chaddr, IP demandée et server identifier.

Les trames taggées 802.1Q/802.1ad sur les ports surveillés sont refusées par ce
backend access-only. Les fragments IPv4 UDP sur ports untrusted sont également
refusés pour empêcher le contournement des vérifications de ports ; cela peut
rejeter **d'autres UDP fragmentés** sur ces ports. Les trames de données non-DHCP
non concernées continuent de suivre les autres politiques. Trunks, LACP, DHCP
relay/giaddr, Option 82, option overload, DHCPv6, rate limiting et filtrage complet
de tous les champs DHCP constructeur restent non implémentés. L'activation sur
un switch contenant un trunk/LACP est refusée, même si le trunk n'est pas dans
le VLAN sélectionné. L'inspection ARP et IP Source Guard sont des options séparées décrites ci-dessous.

### Essai avec un serveur malveillant réel

```bash
python3 -m network_labs.appliances example --dhcp-snooping \
  --rootfs "$HOME/network-labs-rootfs" > dhcp-snooping-lan.json
sudo python3 -m network_labs.appliances start dhcp-snooping-lan.json
# Attendre quelques secondes pour DORA / validation ARP de BusyBox.
sudo python3 -m network_labs.appliances inspect dhcp-snooping-lan PC1
sudo python3 -m network_labs.appliances explain dhcp-snooping-lan SW1
sudo python3 -m network_labs.appliances exec dhcp-snooping-lan PC1 -- \
  /bin/ping -c 3 10.10.0.2
```

Le lab démarre quatre containers : PC1, SW1, DHCP1 et ROGUE. Les deux serveurs
BusyBox tournent réellement. DHCP1, sur fa0/2 (=eth1), est trusted et distribue
10.10.0.100–110 ; ROGUE, sur fa0/3 (=eth2), distribue 10.10.0.200–210 mais ses
réponses sont bloquées. PC1, sur fa0/1 (=eth0), doit recevoir une IP du serveur
légitime. `inspect SW1` contient `dhcp_snooping`, la table effective, compteurs
par règle et bindings. Un binding confirme un échange REQUEST/ACK observé,
**pas l'installation de l'IP sur le PC** : vérifier aussi `inspect PC1`.

### Configuration IOS partielle et manifest

```text
configure terminal
ip dhcp snooping
ip dhcp snooping vlan 10
interface fa0/2
ip dhcp snooping trust
end
```

`no ip dhcp snooping trust` remet un port en untrusted. `no ip dhcp snooping`
désactive la fonction tout en conservant VLANs/trust déclarés pour réactivation.
`no ip dhcp snooping vlan 10` retire un VLAN. Le bloc entier est validé avant
mutation ; relay/Option 82/rate limiting et autres commandes non supportées sont
refusés. Les paramètres du manifest sont :

```json
{
  "dhcp_snooping": {
    "enabled": true,
    "vlans": [10],
    "trusted": ["eth1"]
  }
}
```

Il n'y a ni `trusted` implicite pour les nodes de rôle serveur, ni inspection de
leurs fichiers de baux pour fabriquer les bindings. La confiance est celle du
**port d'entrée**, pas celle de la marque ou du nom du node. Un serveur sur un
port trusted peut fournir une mauvaise configuration ; le snooping ne constitue
pas son authentification.

### Durée de vie et limites des observations

Le tableau est volatile : MAC, IPv4, port, VLAN, serveur, durée de lease et temps
restant proviennent des paquets. L'expiration utilise le temps monotone. Renewal
remplace la durée après un nouvel échange corrélé ; RELEASE/DECLINE cohérents et
NAK corrélés retirent le binding. Des requests ambiguës sur plusieurs ports sont
refusées. Les messages tronqués, fragments, tags, relay et options ambiguës ne
créent pas de binding. L'observateur vérifie les checksums IPv4 et UDP hors offload ; il s'appuie sur
les métadonnées kernel pour les checksums UDP offloadés. Il ne certifie ni
admission par toutes les règles, ni livraison, ni installation par le client.
L'option d'inspection ARP décrite ci-dessous peut en dériver des permissions
courtes ; elle n'active pas IP Source Guard.

L'observateur borne les requests en attente (60 s, 1024) et bindings (1024). Une
saturation refuse de nouvelles observations plutôt que d'évincer silencieusement
un binding existant. Les pertes AF_PACKET sont comptées ; une perte signalée
vide les corrélations/bindings avant reconstruction pour éviter de les conserver
à travers un trou connu. L'absence de pertes signalées ne prouve pas une capture
complète. Un port client down invalide ses observations. La perte du lien serveur ne
révoque pas un lease client déjà observé et non expiré. Une identité d'interface
changée ou manquante arrête l'observateur.
Un snapshot est périodique, pas une transaction atomique avec l'état des ports.

Le worker a une identité PID/starttime/token, vérifiée à la lecture, un heartbeat
et une vérification de propriété du lab/namespace. Il est démarré prêt avant les
services DHCP, redémarré quand VLANs/trust changent, et arrêté avant la destruction
des namespaces. Une modification sans changement de périmètre conserve le worker
et les bindings ; si le worker est mort, une nouvelle configuration réseau le
relance. Les changements de périmètre réinitialisent bindings et compteurs de la
table de snooping. Un observateur absent/périmé, un token incorrect ou une politique
non conforme rend `bindings: null`, jamais une fausse table vide saine. La mort
du worker ne retire pas les règles de rejet du kernel.

Save/export vérifient la conformité de la table nft gérée en ignorant ses
compteurs. Save/restore conserve VLANs/trust et recrée le worker ; **aucun binding,
lease, compteur ou fichier runtime n'est persisté dans startup**. Les journaux et
snapshots privés du worker restent dans le répertoire runtime du lab et sont
supprimés au stop. L'application utilise le journal/rollback existant ; une reprise
peut vider les observations. Les processus Python d'observation vivent côté hôte,
hors cgroups OCI : leur mémoire/CPU doit être incluse dans une future mesure de
l'application entière. Aucun résultat global « sous 2 GiB » n'est établi ici.

`explain` distingue `DHCP_SNOOPING_POLICY`, `DHCP_SNOOPING_UNVERIFIED`,
`DHCP_SNOOPING_BINDINGS`, `DHCP_SNOOPING_OBSERVER_UNAVAILABLE` et
`DHCP_SNOOPING_DROPS`. Les compteurs sont cumulatifs par règle, pas un nombre de
serveurs attaquants ou une preuve de résultat d'un ping particulier.

La validation native démarre deux vrais serveurs DHCP concurrents, vérifie le
bail installé et le binding du serveur trusted, capture les rejets de réponses
rogue (y compris source UDP modifiée et tags), puis vérifie un vrai passage après
changement de trust. Elle contrôle stop/restore, perte/redémarrage du worker,
maintien des rejets sans worker, refus de save après drift et absence de
modification des liens/routes/règles nft de l'hôte.
Références : [RFC 2131](https://www.rfc-editor.org/rfc/rfc2131.html),
[DHCP snooping Cisco](https://www.cisco.com/c/en/us/td/docs/switches/datacenter/sw/4_0/dcnm/security/configuration/guide/sec_dcnm_config/sec_dhcpsnoop.html),
[bridge nftables](https://wiki.nftables.org/wiki-nftables/index.php/Bridge_filtering).

## Inspection ARP dynamique sur ports access

`example --arp-inspection` étend le lab DHCP snooping avec une politique ARP
réelle dans `bridge network_labs_arp_inspection`, priorité -290. Elle s'applique
après les filtres DHCP et port security, sur les VLANs access sélectionnés.
Les VLANs inspectés doivent déjà avoir DHCP snooping actif ; trunks/LACP restent
refusés. Les ports **ARP trusted sont indépendants des ports DHCP trusted**.
Leur trafic ARP n'est pas inspecté. Ne marquer trusted que des liens autorisés à
émettre librement des annonces ARP.

Sur un port untrusted, le kernel vérifie le format Ethernet/IPv4 ARP, les longueurs
et les opérations request/reply. Les admissions dynamiques utilisent une clé
concaténée **MAC Ethernet + MAC sender ARP + IP sender ARP**, dans un set propre
au port/VLAN. Les deux MAC doivent donc correspondre à la même identité autorisée.
Une simple correspondance IP seule ou MAC ARP seule ne suffit pas. Les paquets
non admis sont droppés et comptés. Les règles ne filtrent pas les paquets IPv4 de
données : **ce n'est pas IP Source Guard**. Une connexion avec une entrée voisin
encore en cache peut continuer sans générer d'ARP ; vider les voisins pour tester
la résolution ARP elle-même.

### Origine et durée des autorisations

Le worker DHCP existant ajoute, quand cette option est active, un renouvellement
atomique des sets ARP depuis les échanges DHCPREQUEST/DHCPACK observés. Il vérifie
les définitions des politiques DHCP et ARP avant chaque renouvellement. Des
bindings dynamiques contradictoires pour une même IP/VLAN sont tous refusés ;
un binding statique explicite ne peut pas être remplacé par un binding dynamique.
Les bindings DHCP restent des attributions **observées sur un port serveur
trusted**, pas une preuve d'installation chez le client ni une authentification
cryptographique du serveur. L'admission ARP ne contourne pas les autres filtres.

Le parseur DHCP vérifie désormais le checksum IPv4, le checksum UDP non nul hors
offload, et la cohérence IP source/server identifier pour les réponses directes.
Un checksum UDP IPv4 nul est autorisé ; pour les statuts checksum-offload/valid
signalés par le kernel AF_PACKET, le worker s'appuie sur ces métadonnées au lieu
de rejeter un checksum partiel. Les autres restrictions de parsing précédentes
restent applicables.

Un grant dynamique dure **au plus 2000 ms après son installation kernel**, avec
renouvellement normalement toutes les 0,5 s. Le calcul réserve 2 s avant la fin
observée du lease pour le budget d'installation : la fin du bail peut donc
entraîner un refus anticipé. Si le worker est tué, les grants cessent d'être
renouvelés et expirent dans le kernel. Un enfant `nft` en cours reçoit aussi un
signal de mort du parent. Un arrêt normal vide les sets ; une politique absente
ou modifiée interrompt les renouvellements. Les règles statiques et trusted
restent actives indépendamment du worker. Les timeouts ne sont pas une garantie
de planification temps réel de l'hôte.

Les probes ARP source 0.0.0.0 ne sont acceptées que pour une MAC déjà autorisée
(dynamique ou statique), en request broadcast, avec target hardware nul et
IP cible non nulle/non multicast. Les probes d'une MAC inconnue avant DHCP ne
sont pas admises. Les gratuitous ARP revendiquant une IP normale passent par la
même validation de binding. La validation de la MAC destination des replies,
les rate limits, ARP ACLs constructeur et IPv6/NDP ne sont pas
implémentés.

### Configuration et adresses statiques

```text
configure terminal
ip dhcp snooping
ip dhcp snooping vlan 10
ip arp inspection vlan 10
ip source binding 0200.0000.1003 vlan 10 10.10.0.3 interface fa0/3
interface fa0/2
ip dhcp snooping trust
ip arp inspection trust
end
```

`ip source binding` est ici un sous-ensemble pour admission ARP statique, sans
activation implicite d'IP Source Guard. La MAC/IP/port/VLAN doit être explicite,
unicast et sans ambiguïté dans le VLAN. Les adresses du manifest des PCs ne sont
pas automatiquement transformées en permissions. `no ip source binding ...`
retire l'entrée exacte, `no ip arp inspection trust` retire la confiance ARP et
`no ip arp inspection vlan 10` désactive ce VLAN. Retirer l'inspection ARP avant
de désactiver DHCP snooping sur un VLAN dépendant. Tout le bloc est validé avant
mutation.

```json
{
  "arp_inspection": {
    "vlans": [10],
    "trusted": ["eth1"],
    "bindings": [
      {"port": "eth2", "vlan": 10, "mac": "02:00:00:00:10:03", "address": "10.10.0.3"}
    ]
  }
}
```

Un changement de politique ARP redémarre le worker et vide les attributions
volatiles : relancer une acquisition DHCP si les clients ont déjà un bail.
Aucun binding n'est fabriqué depuis leur IP actuelle pour rétablir le trafic.
`inspect` affiche les **sets et compteurs du kernel**, plus la conformité des
définitions. `explain` distingue `ARP_INSPECTION_POLICY`,
`ARP_INSPECTION_UNVERIFIED`, `ARP_INSPECTION_DYNAMIC_WINDOW` et
`ARP_INSPECTION_DROPS`. Les compteurs sont cumulatifs ; ils ne certifient pas
l'absence de spoofing ni le résultat d'un paquet précis.

Save/export vérifient la politique, y compris ses règles statiques, en ignorant
les éléments DHCP temporaires et leurs expirations. Restore recrée les règles
et laisse DHCP reconstruire les permissions dynamiques. Les noms/formats des
sets sont internes ; modifier une table à la main constitue du drift et ne doit
pas être utilisé comme configuration persistante. Le journal/rollback existant
s'applique aux politiques ; il peut réinitialiser les grants et observations.

### Test du scénario natif

```bash
python3 -m network_labs.appliances example --arp-inspection \
  --rootfs "$HOME/network-labs-rootfs" > arp-inspection-lan.json
sudo python3 -m network_labs.appliances start arp-inspection-lan.json
# Attendre DORA et le premier renouvellement des sets ARP.
sudo python3 -m network_labs.appliances explain arp-inspection-lan SW1
sudo python3 -m network_labs.appliances exec arp-inspection-lan PC1 -- \
  /bin/ping -c 3 10.10.0.2
# BusyBox arping exige une IP source locale : ajout temporaire dans ROGUE.
sudo python3 -m network_labs.appliances exec arp-inspection-lan ROGUE -- \
  /bin/ip addr add 10.10.0.2/32 dev eth0
sudo python3 -m network_labs.appliances exec arp-inspection-lan ROGUE -- \
  /bin/busybox arping -U -c 3 -w 3 -I eth0 -s 10.10.0.2 10.10.0.2
sudo python3 -m network_labs.appliances exec arp-inspection-lan ROGUE -- \
  /bin/ip addr del 10.10.0.2/32 dev eth0
sudo python3 -m network_labs.appliances explain arp-inspection-lan SW1
```

Le lab conserve les deux serveurs DHCP réels du scénario précédent. DHCP1 sur
eth1 est trusted pour DHCP et ARP ; ROGUE sur eth2 est untrusted pour les deux,
avec une permission ARP statique limitée à sa propre MAC/IP 10.10.0.3. PC1 reçoit
une autorisation ARP dynamique depuis son bail légitime. Le test natif vérifie
les pings après résolution ARP, les captures négatives pour requests/replies
spoofées et MAC Ethernet/ARP incohérentes, un passage statique positif, le maintien du LAN après perte du lien DHCP, puis
l'expiration des permissions dynamiques après SIGKILL du worker avec voisins
vidés. Il contrôle également la reprise DHCP, le drift/refus de save, restore,
le nettoyage des processus et l'intégrité des liens/routes/règles nft de l'hôte.
Références : [ARP et concaténations nftables](https://netfilter.org/projects/nftables/manpage.html),
[principe DAI Cisco](https://www.cisco.com/c/en/us/support/docs/switches/lan-switch-software/222274-troubleshoot-dynamic-arp-inspection-dai.html),
[RFC 5227 ARP probes](https://www.rfc-editor.org/rfc/rfc5227.html).

## IP Source Guard IPv4 sur ports access

`ip_source_guard` active un filtre **réel de paquets IPv4 entrants** dans le
namespace du switch, avant l'apprentissage/FDB du bridge. Il complète DAI :
une entrée ARP déjà connue ne permet plus de contourner la validation de source.
Il ne faut pas activer DAI pour l'utiliser.

```json
"ip_source_guard": {"eth0": "ip-mac", "eth2": "ip-mac"}
```

- `ip` vérifie l'IP source et le port/VLAN du binding ; il ne vérifie pas la MAC.
- `ip-mac` vérifie ensemble MAC Ethernet, IP source et port/VLAN du binding.
- Les ports doivent être physiques, access et non trusted DHCP, avec snooping
  actif sur leur VLAN. Les trunks et LACP restent hors périmètre de ce filtre.
- Les bindings dynamiques viennent des corrélations REQUEST/ACK du même
  observateur supervisé de DHCP snooping. Aucun processus supplémentaire par
  port/node n'est ajouté. Ce worker Python tourne dans le namespace du switch,
  hors cgroup OCI : son coût doit entrer dans une future mesure de l'application
  entière, qui reste à faire pour le budget de 2 GiB.
- Les bindings statiques partagent **`arp_inspection.bindings`**, conservé pour
  compatibilité des manifests. `arp_inspection.vlans: []` permet de les utiliser
  sans activer l'inspection ARP. Il n'existe pas deux bases statiques à synchroniser.
  Les propriétaires statiques du même VLAN empêchent les autorisations dynamiques
  ambiguës, y compris sur un port non protégé par IPSG.

### DHCP initial et durée des autorisations

Avant le binding, le filtre laisse passer uniquement le bootstrap DHCP IPv4
source **0.0.0.0**, destination **255.255.255.255**, UDP 68→67, sans fragmentation,
avec longueur UDP suffisante, en-tête BOOTREQUEST Ethernet/6 octets/hops 0 et
cookie DHCP. Il ne s'agit pas d'une exemption générale UDP 68→67 : une source
non nulle non autorisée reste bloquée, même avec un payload DHCP. Ce contrôle
kernel de forme ne valide pas intégralement les options/checksums DHCP ; le
parseur de l'observateur les valide séparément avant d'apprendre un binding.

Les données et renouvellements depuis une IP attribuée passent par leur binding.
Une machine sans autorisation utilisable doit recommencer une acquisition avec
source 0.0.0.0 ; INIT-REBOOT/renewal non nul sans binding n'est pas exempté.
Le snooping conserve ses restrictions de tags et fragments UDP non trusted.

Comme pour DAI, les autorisations dynamiques sont des sets nftables avec timeout
kernel de **2 secondes maximum**, renouvelés par l'observateur. Le calcul réserve
2 secondes sur la fin du bail pour le budget d'installation et peut refuser
prématurément une fin de bail. Les conflits IP/port/MAC, une perte de capture ou
la chute du port client retirent les bindings ; la perte du serveur DHCP ne
révoque pas un bail client encore valable. Un observateur mort/bloqué ou une
politique gérée modifiée cesse de renouveler les autorisations, qui expirent ;
les règles statiques persistent. Un enfant nft reçoit SIGKILL si son parent
observateur meurt. Ce délai n'est pas une garantie temps réel de l'hôte.

### CLI partielle et vérification

```text
configure terminal
ip source binding 0200.0000.1003 vlan 10 10.10.0.3 interface fa0/3
interface fa0/1
ip verify source port-security
interface fa0/3
ip verify source
end
```

`ip verify source` sélectionne le mode IP ; `ip verify source port-security`
sélectionne IP+MAC. `no ip verify source` et `no ip verify source port-security`
retirent le filtre du port. Ces syntaxes suivent les deux types de validation
[décrits par Cisco](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst2960/software/release/12-2_55_se/configuration/guide/scg_2960/swdhcp82.html),
mais cet adaptateur est **partiel** : le mode IP+MAC utilise directement le tuple
nftables et ne reproduit ni Option 82, ni apprentissage secure-MAC constructeur,
ni toutes les dépendances Port Security du matériel Cisco. Les autres variantes
sont rejetées avant toute mutation. La port-security statique séparée continue
à s'appliquer si elle est explicitement configurée.

```bash
python3 -m network_labs.appliances example --ip-source-guard \
  --rootfs "$HOME/network-labs-rootfs" > source-guard-lan.json
sudo python3 -m network_labs.appliances start source-guard-lan.json
# Attendre l'acquisition DHCP et le renouvellement des sets (quelques secondes).
sudo python3 -m network_labs.appliances exec source-guard-lan PC1 -- /bin/ping -c 3 10.10.0.2
sudo python3 -m network_labs.appliances exec source-guard-lan ROGUE -- /bin/ping -c 3 10.10.0.2
sudo python3 -m network_labs.appliances inspect source-guard-lan SW1
sudo python3 -m network_labs.appliances explain source-guard-lan SW1
sudo python3 -m network_labs.appliances save source-guard-lan
sudo python3 -m network_labs.appliances stop source-guard-lan
sudo python3 -m network_labs.appliances restore source-guard-lan
```

Ce scénario combine DAI et IPSG : PC1 est autorisé dynamiquement, ROGUE seulement
avec sa source statique 10.10.0.3/MAC configurée, DHCP1 est sur le port serveur
non protégé. Son serveur DHCP rogue reste bloqué par le snooping.
`inspect.ip_source_guard` rapporte les définitions kernel, sets, compteurs et
conformité ; `explain` les interprète sans prétendre prouver la livraison d'un
flux. `save` refuse une table supprimée/modifiée ; les éléments temporaires et
compteurs ne sont pas une dérive de configuration. Les baux ne sont pas sauvegardés :
`restore` réapplique la politique puis les clients acquièrent de nouveaux bindings.

Le test natif injecte de vrais paquets et capture sur le destinataire : bonne
source, mauvais IP, mauvaise MAC, tuple correct sur mauvais port, faux DHCP,
mode IP sans validation MAC. Des voisins permanents excluent la résolution ARP
comme cause de l'échec après mort du worker. Il vérifie aussi la source statique,
la reprise DHCP, la dérive, la sauvegarde/restauration et le nettoyage sans
modifier routes/liens/firewall de l'hôte.

Périmètre : IPv4 ingress, pas IPv6/NDP, pas authentification des utilisateurs,
pas vérification de destination ni ACL applicative. Un clone du tuple complet
IP+MAC sur le même port ne peut pas être distingué de son propriétaire par ce
filtre. Ce n'est pas un firmware constructeur.

## Multicast LAN : IGMPv2 snooping et querier Linux

La politique optionnelle `multicast` configure le **bridge Linux réel**, sans
nouveau daemon permanent. Ce premier périmètre exige des ports access physiques
sur **un seul VLAN commun**, sans trunk/LACP ni commandes startup non suivies.
Un manifeste sans cette politique conserve le comportement précédent du kernel.

```json
"multicast": {
  "snooping": true,
  "querier": true,
  "ports": {
    "eth0": {"router": "auto", "flood": true, "fast_leave": false},
    "eth1": {"router": "off", "flood": true, "fast_leave": true},
    "eth2": {"router": "permanent", "flood": false, "fast_leave": false}
  }
}
```

Les ports omis reçoivent `router: auto`, `flood: true`, `fast_leave: false`.
`router` vaut `off`, `auto` ou `permanent` et pilote le flag kernel du port
multicast-router. Un port routeur permanent reçoit aussi des flux sans listener
local. `flood` contrôle la diffusion des **groupes inconnus**, pas une ACL de tous
les multicasts. Avec un querier actif, les données IPv4 non link-local sans
membership peuvent être dirigées uniquement vers les ports routeurs :
`flood: true` ne force pas une copie vers tous les non-membres. Le test des flags
de flooding est donc réalisé séparément avec snooping désactivé.
`fast_leave` active l'immediate leave ; le réserver à un port
avec un seul récepteur, jamais un segment partagé/uplink, car plusieurs membres
peuvent sinon perdre leur flux. Les groupes connus suivent la MDB et les ports
routeurs, sous réserve de l'état des liens, VLAN et autres politiques.

Le querier nécessite le snooping. Il émet de vraies queries IGMPv2, avec les timers
Linux normaux, **source 0.0.0.0** car le switch est non numéroté. Certains hôtes
peuvent ne pas accepter ce querier ; aucune IP de management n'est inventée.
La convergence initiale prend notamment le délai de réponse aux queries (10 s
avec les valeurs kernel usuelles) : une MDB présente n'est pas un certificat
immédiat de filtrage/livraison. Sans querier effectif, Linux peut continuer à
flooder. Les intervalles ne sont pas raccourcis pour simuler une convergence.

La politique pilote `mcast_snooping`, `mcast_querier`, `mcast_igmp_version=2`,
`mcast_query_use_ifaddr=0`, `mcast_vlan_snooping=0` et les trois flags de chaque
port. Les paramètres partagés snooping/flood du kernel affectent aussi IPv6/MLD :
**il n'existe pas ici de contrôle IPv6 indépendant**. IGMPv3/SSM, PIM, multicast
routé, politique multi-VLAN et fidélité complète aux CLI constructeur ne sont
pas implémentés. Sources primaires :
[bridge Linux](https://www.kernel.org/doc/html/latest/networking/bridge.html) et
[bridge/iproute2](https://man7.org/linux/man-pages/man8/bridge.8.html).

### Configuration et diagnostics

```text
configure terminal
ip igmp snooping
ip igmp snooping querier
end
```

Les formes `no` sont acceptées. Désactiver le querier avant de désactiver snooping,
ou faire les deux dans le même bloc : l'ensemble est validé avant mutation.
Les variantes par VLAN/adresse de querier constructeur sont rejetées.
Pour les flags de ports, appliquer un fichier contenant l'objet de politique :

```bash
sudo python3 -m network_labs.appliances multicast-policy multicast-lan SW1 --file multicast-policy.json
sudo python3 -m network_labs.appliances inspect multicast-lan SW1
sudo python3 -m network_labs.appliances explain multicast-lan SW1
```

`inspect.multicast` rapporte les valeurs netlink, les paramètres de ports et la
**MDB observée** via `bridge -j -s -d mdb show`. Une valeur absente reste
non vérifiée. `explain` présente ces observations sans déduire une livraison ni
une topologie multicast complète. Les edits non liés ne flushent pas les groupes.
`save`/`export` refusent les paramètres gérés modifiés ; la MDB/timers dynamiques
ne sont pas de la dérive et ne sont pas sauvegardés. `restore` recrée la politique,
puis les clients doivent rejoindre à nouveau leurs groupes. Un JSON `null`
retire la gestion et rétablit snooping on/querier off/IGMPv2 et les flags de ports
par défaut ; cela ne restaure pas une ancienne configuration kernel externe.

### Essai réel sans ajouter de programme au rootfs

```bash
python3 -m network_labs.appliances example --multicast \
  --rootfs "$HOME/network-labs-rootfs" > multicast-lan.json
sudo python3 -m network_labs.appliances start multicast-lan.json
```

Dans le terminal A, rejoindre le groupe pendant une fenêtre bornée :

```bash
sudo python3 -m network_labs.appliances multicast multicast-lan RX1 \
  --group 239.10.10.10 --seconds 30
```

Dans le terminal B, attendre environ 12 secondes pour le démarrage normal du
querier, puis envoyer et inspecter pendant que le récepteur est encore actif :

```bash
sudo python3 -m network_labs.appliances multicast multicast-lan TX1 \
  --group 239.10.10.10 --send "Bonjour multicast" --count 3
sudo python3 -m network_labs.appliances inspect multicast-lan SW1
sudo python3 -m network_labs.appliances explain multicast-lan SW1
```

La commande `multicast` utilise un socket UDP réel dans le namespace réseau du
node, épinglé par descripteur, avec le Python de l'hôte via `nsenter`. Le rootfs
BusyBox reste inchangé. Le verrou du lab est relâché avant join/receive :
`send`, `inspect`, `configure` et `stop` restent utilisables dans un autre terminal.
Fermer le socket quitte le groupe et permet au kernel d'émettre IGMP leave.
Ce helper temporaire est **hors cgroup OCI** ; inclure son coût Python dans une
mesure globale si des probes tournent pendant le benchmark.

Limites des probes : groupes administratifs IPv4 239/8, ports UDP 1024..65535,
1..30 s, 1..100 envois de 1..1200 octets UTF-8, TTL=1. Le receive s'arrête après
1000 datagrammes au plus et conserve au plus huit échantillons de 64 octets en
hexadécimal. Les lectures de 1401 octets peuvent être tronquées et sont signalées.
Le watchdog GNU timeout borne aussi un worker orphelin si la CLI disparaît ; un
arrêt concurrent du lab conserve le namespace épinglé jusqu'à la fin de la probe,
sans retour vers le réseau de l'hôte. Les comptes décrivent cette fenêtre/socket,
pas une garantie zéro perte ; succès d'envoi ne prouve pas livraison. Après un
stop/restore concurrent, ils ne certifient pas la nouvelle génération du lab.

La validation native emploie un vrai join IGMP, vérifie MDB et réception UDP,
capture le non-membre (absence de copies d'un groupe connu), les ports routeurs,
la restriction mrouter-only des groupes inconnus avec querier, le flooding
autorisé/refusé avec snooping désactivé, le leave, la dérive, restore et
un stop concurrent. Les liens/routes/règles nft de l'hôte restent inchangés.

## Réservations DHCP : identité MAC et adresse stable

Le serveur BusyBox réel accepte maintenant `dhcp_server.reservations`, une liste
optionnelle de **1..256 mappings explicites MAC/IPv4** (liste vide par défaut).
La réservation permet par exemple à un client d'imprimante de retrouver la même
IP après renouvellement ou recréation du lab ; ce n'est pas une authentification
et cela n'empêche pas un autre hôte de s'attribuer manuellement cette IP.

```json
"dhcp_server": {
  "interface": "eth0",
  "start": "10.10.0.100",
  "end": "10.10.0.102",
  "lease_seconds": 120,
  "reservations": [
    {"mac": "02:00:00:00:10:03", "address": "10.10.0.100"}
  ]
}
```

La configuration produit une vraie directive BusyBox
`static_lease 02:00:00:00:10:03 10.10.0.100`.
Le serveur réserve cette adresse au client identifié par sa MAC et la retire
des candidats dynamiques, même avant que ce client rejoigne le LAN.
L'adresse peut aussi être **hors du pool dynamique**, mais doit être dans le
sous-réseau du serveur, unicast utilisable, distincte du serveur, de l'adresse
réseau/broadcast et de la gateway annoncée. La MAC doit être unicast non nulle.
Les doublons MAC/IP, champs inconnus et textes invalides sont refusés avant
création des ressources. Les formats MAC colon et Cisco pointé sont normalisés.
Ne pas réserver une IP déjà occupée ailleurs dans la topologie : le validateur
ne réalise pas d'inventaire global ni de détection de conflit distribuée.

Le mécanisme repose sur la MAC (`chaddr`), pas sur une identité cryptographique,
un client-ID arbitraire, un hostname, Option 82 ou des réservations DHCPv6.
Un clone de MAC ne peut pas être distingué par cette réservation. DHCP snooping,
DAI et IP Source Guard restent des politiques séparées, à activer explicitement.
Les clients et serveurs restent de vrais processus BusyBox dans leur cgroup OCI ;
aucun nouveau worker permanent n'est ajouté pour les réservations.

### Exemple autonome avec allocation dynamique et client réservé

```bash
python3 -m network_labs.appliances example --dhcp-reservations \
  --rootfs "$HOME/network-labs-rootfs" > dhcp-reservations-lan.json
sudo python3 -m network_labs.appliances start dhcp-reservations-lan.json
# Attendre quelques secondes pour DORA/ARP de BusyBox.
sudo python3 -m network_labs.appliances inspect dhcp-reservations-lan PRN1
sudo python3 -m network_labs.appliances inspect dhcp-reservations-lan PC1
sudo python3 -m network_labs.appliances inspect dhcp-reservations-lan PC2
sudo python3 -m network_labs.appliances exec dhcp-reservations-lan PC1 -- /bin/ping -c 3 10.10.0.100
sudo python3 -m network_labs.appliances explain dhcp-reservations-lan DHCP1
sudo python3 -m network_labs.appliances inspect dhcp-reservations-lan SW1
```

Le lab comprend 5 nodes : PC1, PC2, PRN1, SW1 et DHCP1. PRN1 est un client Linux
nommé pour illustrer une imprimante, sans émulation de firmware ni service
impression. PRN1 reçoit **10.10.0.100** ; PC1 et PC2 reçoivent .101/.102, sans
promesse sur leur ordre respectif. PC1 démarre avant PRN1 : l'exclusion de .100
ne dépend pas de l'existence d'un bail préalable du client réservé. SW1 utilise
le snooping avec un seul port serveur trusted ; les corrélations REQUEST/ACK
réelles sont comparées séparément aux IP installées sur les clients.

`inspect DHCP1` ajoute `dhcp_server`, avec pool, réservations **déclarées** et
conformité du fichier monté `/lab/udhcpd.conf`. La lecture bornée à 64 KiB utilise
`/bin/busybox head` à l'intérieur du container, sans copie/lecture de fichier
arbitraire de l'hôte. Un fichier manquant, trop grand ou illisible reste non
vérifié. `explain` distingue cette configuration des baux observés : conformité
du fichier ne prouve ni que le daemon est vivant ni que sa configuration chargée
n'a pas été modifiée. La disponibilité doit être vérifiée par du trafic DHCP réel.

`save` et `export` refusent une différence du fichier de serveur géré.
Les réservations restent dans le manifest startup et sont réappliquées après
`restore`. **Les baux et fichiers runtime ne sont pas des snapshots** : les
clients acquièrent de nouveaux baux, avec les mêmes identités MAC déclarées.
Les options DHCP, y compris réservations, se configurent dans le manifest avant
`start` ; remplacement à chaud/reload de la politique de serveur et CLI IOS DHCP
constructeur ne sont pas implémentés. Modifier le manifest puis recréer le lab
pour changer ces options ; `restore` seul reprend la dernière configuration sauvée.

La validation native vérifie les trois adresses installées, leurs ACKs observés,
l'exclusion du pool, les pings entre clients, un renouvellement forcé,
release/réacquisition, refus de sauvegarde sur dérive du fichier, restore avec la
même réservation et un second démarrage avec une réservation hors pool (.50).
Elle conserve les liens préexistants/routes/règles nft de l'hôte et ne laisse
aucun lien virtuel ajouté. Référence primaire :
[configuration BusyBox udhcpd](https://coral.googlesource.com/busybox/+/refs/heads/master/examples/udhcp/udhcpd.conf).

## DNS local réel, DHCP et HTTP par nom

`example --dns` démarre **5 nodes OCI** : PC1 (DHCP), PC2 (adresse et resolver
statiques), SW1 (VLAN 10 avec DHCP snooping), DNS1 (.2, DNS et DHCP) et WEB1
(.20, HTTP BusyBox). Le responder DNS est un vrai **dnsmasq** dans DNS1, avec
sockets UDP/TCP 53. BusyBox conserve la responsabilité DHCP et fournit l'option
DNS à PC1 ; son hook écrit `/etc/resolv.conf` après ACK. PC2 reçoit un fichier
resolver géré monté en lecture seule, distinct des fichiers de l'hôte.

### Préparer un nouveau rootfs avec DNS

Sur Ubuntu/Debian, installer le paquet binaire `dnsmasq-base` ; le moteur
n'utilise pas de service DNS de l'hôte. Garder le rootfs BusyBox précédent et
choisir **une nouvelle destination qui n'existe pas encore** :

```bash
sudo apt update
sudo apt install -y busybox-static dnsmasq-base
python3 -m network_labs.appliances rootfs \
  --busybox /bin/busybox --dnsmasq /usr/sbin/dnsmasq \
  --output "$HOME/network-labs-dns-rootfs"
python3 -m network_labs.appliances example --dns \
  --rootfs "$HOME/network-labs-dns-rootfs" > dns-lan.json
sudo python3 -m network_labs.appliances start dns-lan.json
# Attendre quelques secondes pour l'acquisition DHCP.
sudo python3 -m network_labs.appliances exec dns-lan PC1 -- \
  /bin/busybox nslookup -type=A intranet.lab.test
sudo python3 -m network_labs.appliances exec dns-lan PC1 -- \
  /bin/ping -c 3 intranet.lab.test
sudo python3 -m network_labs.appliances exec dns-lan PC2 -- \
  /bin/busybox wget -T 3 -q -O - http://intranet.lab.test/
sudo python3 -m network_labs.appliances inspect dns-lan DNS1
sudo python3 -m network_labs.appliances explain dns-lan DNS1
```

La réponse HTTP attendue est `Network LABS HTTP via DNS`. Le DNS fournit
`intranet.lab.test → 10.10.0.20` et `dns.lab.test → 10.10.0.2`, avec PTR inverse
et TTL 60 s. Les noms inconnus dans `lab.test` donnent NXDOMAIN ; un type AAAA
pour un nom IPv4 existant donne NOERROR sans réponse AAAA.

Le builder copie **un binaire local de confiance**, son interpréteur ELF et les
bibliothèques résolues par `ldd`, sans téléchargement automatique. Il exécute
ce binaire pour vérifier son identité : ne pas lui donner un exécutable inconnu.
Les chemins copiés sont listés dans `/etc/network-labs-dns-assets.json` du
rootfs. Construire pour la même architecture/ABI que l'hôte d'exécution. Les
copies ne sont pas mises à jour automatiquement avec les paquets de l'hôte ;
reconstruire un nouveau rootfs après une mise à jour nécessaire. Sans `--dnsmasq`,
le builder conserve le profil BusyBox statique précédent. Un node DNS dont le
rootfs n'a pas `/usr/sbin/dnsmasq` est refusé au preflight.

### Politique déclarative

```json
{
  "dns_server": {
    "interface": "eth0",
    "zone": "lab.test",
    "ttl": 60,
    "records": {"intranet.lab.test": "10.10.0.20"}
  }
}
```

Ce fragment s'ajoute à un endpoint OCI avec interface statique numérotée.
Les noms sont normalisés en minuscules, avec labels ASCII valides. Le profil
accepte 1 à 256 noms locaux, une seule adresse IPv4 unicast par nom et un seul
nom par adresse pour garder un PTR déterministe. Les doublons, noms hors zone,
valeurs injectables et champs inconnus sont refusés avant création des ressources.
La configuration générée doit tenir dans le budget observable de 64 Kio.
Le TTL doit être un entier entre 0 et 86400. `resolvers: ["10.10.0.2"]` ajoute
jusqu'à trois resolvers uniques à un endpoint OCI sans client DHCP. Le resolver
DHCP reste contrôlé par son ACK ; les deux modes ne peuvent pas se concurrencer.
Les nodes avec DNS ou resolver statique ne peuvent pas avoir de commandes
`startup` non suivies. HTTP dans WEB1 reste une commande startup explicite.

### Panne et recréation

```bash
sudo python3 -m network_labs.appliances exec dns-lan DNS1 -- \
  /bin/sh -c '/bin/kill -TERM "$(/bin/cat /run/dnsmasq.pid)"'
# La résolution n'est plus disponible ; le chemin IP/HTTP reste utilisable.
sudo python3 -m network_labs.appliances exec dns-lan PC1 -- \
  /bin/busybox wget -T 3 -q -O - http://10.10.0.20/
sudo python3 -m network_labs.appliances save dns-lan
sudo python3 -m network_labs.appliances stop dns-lan
sudo python3 -m network_labs.appliances restore dns-lan
# Après le nouveau DHCP, reprendre les tests par nom ci-dessus.
```

`inspect DNS1` montre la conformité du fichier `/lab/dnsmasq.conf` et un snapshot
brut des sockets DNS du kernel. `inspect PC2` montre la conformité de son
resolver géré. **Ces observations ne prouvent pas une réponse DNS correcte** ;
les requêtes et HTTP par nom constituent la preuve active. Même après arrêt du
daemon, le fichier peut rester conforme. `save`/`export` refusent une dérive ou
une lecture impossible d'un de ces fichiers gérés. Ils conservent la politique
déclarative ; `restore` relance DNS/DHCP/HTTP, sans snapshot de processus, cache,
sessions, filesystem runtime ou baux.

Le profil n'utilise aucun upstream : `no-resolv`, `no-hosts` et une configuration
explicite évitent l'héritage du DNS et des hosts de l'hôte. Il ne fournit ni
résolution Internet, DNSSEC, CNAME, enregistrement dynamique des noms DHCP,
zone transfer ni reload/CLI constructeur. Changer le manifest puis recréer le
lab pour modifier cette politique. Le processus DNS est dans le cgroup OCI de
son node ; le budget global de l'application reste non vérifié.

La validation native exerce A/PTR/NODATA/NXDOMAIN via **UDP et TCP**, resolver
issu d'un vrai DHCP, resolver statique en lecture seule, `nslookup`, `ping` et
HTTP par nom des deux PC, perte réelle du daemon, continuité par IP, restore,
refus de sauvegarde sur dérive de chaque fichier et nettoyage des ressources.
Référence primaire : [manuel dnsmasq](https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html).

## Découverte LLDP réelle

`example --lldp` relie PC1–SW1–SW2–PC2 sur le VLAN access 10. Chaque node lance
**lldpd dans son container**, avec un client lldpcli réel. Le rootfs optionnel
contient les deux exécutables de confiance et leurs dépendances ELF résolues
localement. Le builder accepte explicitement le profil Debian/Ubuntu avec
compte/groupe `_lldpd` et chroot `/run/lldpd` ; un profil différent est refusé
avant création du rootfs. Les nodes LLDP reçoivent seuls `CAP_SYS_CHROOT` pour
la séparation de privilèges du daemon. Ses processus restent dans le cgroup OCI.

```bash
sudo apt install -y busybox-static lldpd
python3 -m network_labs.appliances rootfs \
  --busybox /bin/busybox --lldpd /usr/sbin/lldpd --lldpcli /usr/sbin/lldpcli \
  --output "$HOME/network-labs-lldp-rootfs"
python3 -m network_labs.appliances example --lldp \
  --rootfs "$HOME/network-labs-lldp-rootfs" > lldp-lan.json
sudo python3 -m network_labs.appliances start lldp-lan.json
sudo python3 -m network_labs.appliances exec lldp-lan SW1 -- \
  /usr/sbin/lldpcli -u /run/lldpd.socket show neighbors details
sudo python3 -m network_labs.appliances inspect lldp-lan SW1
sudo python3 -m network_labs.appliances explain lldp-lan SW1
```

Choisir une nouvelle destination de rootfs. Le moteur n'utilise ni ne pilote
un éventuel service lldpd de l'hôte. L'installation du paquet reste une opération
système distincte de l'exécution des daemons du lab. `--dnsmasq` peut être ajouté
à la même commande rootfs pour disposer des deux services ; seuls les services
déclarés dans chaque node sont démarrés.

Le manifest ajoute par node :

```json
{"lldp": {"ports": ["eth0", "eth1"], "tx_interval": 2, "tx_hold": 3}}
```

Le profil initial accepte 1 à 16 interfaces physiques déclarées, des ports
switch Linux access ou trunk, intervalle 1–60 s et hold 2–10. Les ports sont explicitement
sélectionnés, le nom du node est annoncé, et l'identifiant de port est son nom
d'interface. Les configurations par défaut de l'hôte ne sont pas importées.
Les nodes avec startup non suivi ou LACP sont refusés pour ce premier profil.
Il n'ajoute ni CDP, LLDP-MED, PoE, SNMP, ni configuration constructeur.

`inspect` conserve la sortie JSON0 de `lldpcli show neighbors details`, avec
ses informations de ports/châssis/annonces. Les voisins ne sont jamais générés
à partir des liens du manifest. La table peut être vide après démarrage jusqu'à
réception d'une annonce ; une commande impossible/expirée/invalide reste
`null`, distincte d'une table vide observée. Les lectures sont bornées à 1 Mio
et 5 secondes. Ces annonces ne sont pas authentifiées et ne prouvent ni
livraison des données ni santé du voisin. Un bridge peut continuer à commuter
normalement quand son daemon LLDP est arrêté.

Pour observer les vraies trames :

```bash
sudo python3 -m network_labs.appliances capture lldp-lan PC1 eth0 \
  --seconds 5 --packets 10 --filter 'ether proto 0x88cc' --output lldp.pcap
```

`save`/`export` vérifient le fichier géré `/lab/lldpd.conf`, le fingerprint de
configuration globale lu via lldpcli et les statuts administratifs des ports
présents. Les interfaces absentes/down peuvent ne pas être rapportées par le
daemon ; les interfaces/admin state du kernel sont contrôlés séparément par le
mécanisme de sauvegarde existant. Une modification globale ou un port passé en
`disabled` via la vraie CLI est détecté. Cela ne constitue pas un export complet
de toutes les extensions/TLV par port offertes par lldpcli. Les options gérées
se modifient dans le manifest puis par recréation du lab ; l'adapter ios-basic
refuse les modifications de ces nodes. `restore` redémarre les services et
réapprend les voisins, sans snapshot du cache ou des timers.

La validation native compare les voisins reçus de chaque node, vérifie qu'un
PC ne découvre pas à travers les deux bridges, capture/décode une vraie trame,
coupe/rétablit le lien entre switches avec pings négatif/positif, tue réellement
lldpd et attend l'expiration des annonces tout en conservant le ping, puis
recrée le lab depuis startup. Elle couvre aussi les dérives fichier/CLI globale
et statut de port, leur refus de sauvegarde, et le nettoyage sans modification
des liens/routes/règles nft de l'hôte.

Références primaires : [usage lldpd/lldpcli](https://lldpd.github.io/usage.html),
[séparation de privilèges](https://github.com/lldpd/lldpd/blob/master/README.md).

## Backend Open vSwitch et RSTP réel

`example --rstp` utilise trois switches Open vSwitch dans trois containers OCI,
chacun avec sa base OVSDB, son socket de contrôle et son processus ovs-vswitchd.
Trois PC Linux ferment le scénario. Le datapath **kernel OVS** reste dans le
namespace réseau de son node ; aucun bridge/port n'est ajouté à l'OVS de l'hôte.
Ce backend est distinct du Linux bridge classique et ne dépend pas du nouveau
`stp_mode user` du kernel. Les anciens scénarios gardent leur backend Linux.

```bash
sudo apt install -y busybox-static openvswitch-switch
sudo modprobe openvswitch
python3 -m network_labs.appliances rootfs --busybox /bin/busybox \
  --openvswitch --output "$HOME/network-labs-ovs-rootfs"
python3 -m network_labs.appliances example --rstp \
  --rootfs "$HOME/network-labs-ovs-rootfs" > rstp-lan.json
sudo python3 -m network_labs.appliances start rstp-lan.json
sudo python3 -m network_labs.appliances inspect rstp-lan SW3
sudo python3 -m network_labs.appliances explain rstp-lan SW3
sudo python3 -m network_labs.appliances exec rstp-lan SW3 -- \
  /usr/bin/ovs-vsctl --db=unix:/run/ovs/db.sock get Port eth2 rstp_status
sudo python3 -m network_labs.appliances exec rstp-lan PC1 -- \
  /bin/ping -c 3 192.0.2.30
```

Utiliser une nouvelle destination de rootfs. Le builder copie les exécutables
locaux de confiance ovsdb-server, ovs-vswitchd, ovsdb-tool, ovs-vsctl et
ovs-appctl, leurs bibliothèques ELF et le schéma Open_vSwitch. Les versions sont
vérifiées avant création du rootfs. Le paquet système peut gérer son propre
service hôte ; le moteur de lab ne le pilote pas. Les commandes OVS du moteur
passent toutes par `crun exec` et le socket déclaré dans le node, sans fallback
sur une base ou un daemon hôte. Le module kernel doit être préchargé ; le moteur
ne le charge pas automatiquement.

Le manifest déclare `switch_backend: "ovs"` et `spanning_tree.mode: "rstp"`.
Le profil initial exige un switch OCI, dialect Linux, ports physiques access,
au moins 64 Mio alloués (128 Mio par switch dans l'exemple), sans startup non
suivi ni LACP. Les politiques de sécurité/multicast/LLDP propres au backend
Linux ne sont pas portées automatiquement. Trunks, MSTP/PVST, guards kernel,
CLI IOS et modifications à chaud par l'adapter sont refusés. Priorité, coût et
priorité de port, max_age et forward_delay sont configurés dans OVS. Le hello
reste à 2 s pour ce profil. Les trois switches d'un composant doivent utiliser
le même protocole et des timers cohérents.

La création du bridge avec `rstp_enable=true`, STP classique désactivé et ports
access se fait dans une transaction OVSDB. SW1 a la priorité 4096, SW2 8192 et
SW3 12288. RSTP échange ses BPDUs, choisit le root et les rôles de port. `inspect`
retourne les véritables statuts et compteurs OVSDB ; une absence de daemon ou de
données reste indisponible. L'audit VLAN basé sur netlink Linux bridge reste
explicitement inconnu pour OVS ; aucune table kernel fictive n'est produite.

Pour couper le chemin direct de SW3 vers SW1 :

```bash
sudo python3 -m network_labs.appliances exec rstp-lan SW3 -- /bin/ip link set eth1 down
sudo python3 -m network_labs.appliances exec rstp-lan PC1 -- /bin/ping -c 3 192.0.2.30
sudo python3 -m network_labs.appliances inspect rstp-lan SW3
sudo python3 -m network_labs.appliances exec rstp-lan SW3 -- /bin/ip link set eth1 up
```

SW3 doit utiliser eth2 via SW2 après reconvergence. Le délai dépend du scénario
et des observations : le premier ping peut perdre des paquets pendant le
changement. Les statuts OVSDB sont publiés de manière asynchrone ; ils ne sont
pas une preuve de livraison ni un certificat global de convergence.

`save`/`export` comparent les colonnes gérées de configuration Bridge/Port à leur
baseline, hors statuts RSTP/compteurs volatils, et exigent le daemon joignable.
Ils ne constituent pas un export complet des règles OpenFlow ou d'extensions
non gérées. Un changement de VLAN par ovs-vsctl est détecté. La perte du daemon
reste une panne, sans reprise automatique ou promesse sur les flows déjà en
cache ; utiliser stop/restore avec une configuration startup déjà sauvée.
`restore` recrée base, switches et protocoles, sans snapshot des flows/FDB/timers.
Les limites et mesures mémoire du benchmark précédent ne s'étendent pas à OVS.

La validation native observe l'élection/rôles d'un triangle, capture et décode
une vraie BPDU RSTP version/type 2, mesure le retour du ping après coupure d'un
root port, vérifie l'isolation access VLAN et la détection de dérive, l'absence
du daemon après SIGKILL, le refus de sauvegarde, puis le restore et nettoyage.
Les liens/routes/règles nft et la base OVS Bridge de l'hôte sont comparés avant
et après. Références primaires : [schéma OVS](https://www.openvswitch.org/support/dist-docs/ovs-vswitchd.conf.db.5.html),
[namespaces OVS](https://docs.openvswitch.org/en/latest/topics/networking-namespaces/).

## Switch Layer 3 : SVI et routage inter-VLAN

`example --svi` crée quatre PC, un switch Linux L3 SW1 et un switch L2 SW2,
reliés par un trunk transportant les VLAN 10 et 20 taggés. PC1/PC2 sont en
192.0.2.0/24, PC3/PC4 en 198.51.100.0/24. SW1 termine les VLANs avec de vrais
devices `vlan10`/`vlan20` sur son bridge `br0`, les gateways .1 et les memberships
VLAN `self` nécessaires au port local. Aucun nouveau daemon ni rootfs spécial.

Le scénario démarre **sans routage inter-VLAN**. Chaque groupe communique dans
son VLAN et peut joindre sa propre gateway. Activer explicitement le forwarding :

```bash
python3 -m network_labs.appliances example --svi \
  --rootfs "$HOME/network-labs-rootfs" > svi-lan.json
sudo python3 -m network_labs.appliances start svi-lan.json
sudo python3 -m network_labs.appliances configure svi-lan SW1 \
  --text $'configure terminal\nip routing\nend'
sudo python3 -m network_labs.appliances exec svi-lan PC1 -- /bin/ping -c 3 198.51.100.10
sudo python3 -m network_labs.appliances exec svi-lan PC2 -- /bin/ping -c 3 198.51.100.20
sudo python3 -m network_labs.appliances inspect svi-lan SW1
sudo python3 -m network_labs.appliances explain svi-lan SW1
```

Les paquets sont routés par Linux, avec décrément du TTL. PC2→PC4 entre par le
trunk en VLAN 10 et ressort par ce même trunk en VLAN 20. `no ip routing` coupe
le forwarding IPv4 tout en conservant les gateways locales et le switching L2.
Le rôle reste `switch` ; les ports physiques restent sans IP.

Le manifest ajoute, sur un switch OCI avec backend Linux :

```json
{
  "svis": {
    "vlan10": {"vlan": 10, "address": "192.0.2.1/24"},
    "vlan20": {"vlan": 20, "address": "198.51.100.1/24"}
  },
  "forwarding": true
}
```

Le champ `forwarding` reste false par défaut sur un switch. Jusqu'à 32 SVI,
nommées canoniquement vlan1..vlan4094, nécessitent un VLAN déclaré et une IPv4
unicast utilisable avec préfixe 1..32, ou une adresse vide. Les subnets qui se chevauchent sont
refusés ; VRF, adresses secondaires et IPv6 ne sont pas implémentés ici. Des
routes IPv4 statiques du manifest peuvent utiliser une SVI numérotée et un
next-hop dans son subnet. Le profil OVS ne prend pas encore en charge ces SVIs.
Les nodes SVI avec startup non suivi ou client DHCP sont refusés.

La CLI partielle ios-basic accepte les deux écritures `interface vlan 20` et
`interface Vlan20`, avec `ip address IP MASK`, `no ip address`, `shutdown`,
`no shutdown` et `no interface vlan 20`. Les commandes switchport appliquées à
une SVI sont refusées. L'ensemble du bloc est validé avant mutation ; une erreur
d'application utilise le journal/rollback réseau existant.

```bash
sudo python3 -m network_labs.appliances configure svi-lan SW1 \
  --text $'conf t\ninterface vlan 20\nshutdown\nend'
# PC3 et PC4 peuvent encore communiquer directement dans le VLAN 20.
sudo python3 -m network_labs.appliances configure svi-lan SW1 \
  --text $'conf t\ninterface vlan20\nno shutdown\nend'
```

`inspect` lit le parent, l'encapsulation 802.1Q, le VID, les flags/carrier réels,
les adresses/routes et les sysctls ARP par SVI. `arp_ignore=1` et `arp_announce=2`
sont appliqués dans ce node, après les changements d'ip_forward susceptibles de
réinitialiser des paramètres. Le profil limite ainsi les réponses ARP à
l'interface portant l'adresse demandée, sans annoncer une politique complète
d'authentification ou de contrôle d'accès. L'état/carrier Linux **n'est pas**
l'autostate Catalyst calculé à partir des ports actifs de chaque VLAN ; aucun
état logiciel fictif n'est ajouté. La présence d'une interface UP ne prouve pas
la disponibilité de la gateway. Les tests de paquets restent nécessaires.

`capture` et `monitor` acceptent aussi les interfaces SVI. Les compteurs de SVI,
bridge et trunk représentent des points d'observation distincts et ne doivent
pas être additionnés comme un total de trafic. L'audit VLAN entre switches
continue à utiliser leurs memberships physiques/logiques observés.

`save`/`export` vérifient les interfaces/adresses/admin state/forwarding/routes,
le parent et l'encapsulation des SVIs, les memberships CPU/self et les réglages
ARP gérés. Une configuration externe différente/inconnue bloque la sauvegarde.
`restore` recrée les devices et routes, y compris les SVIs shutdown ; les caches
ARP/FDB et compteurs ne sont pas des snapshots. Les modifications live du
backend OVS sont désormais refusées au point d'entrée réseau commun aussi,
afin qu'une priorité modifiée dans un manifest ne puisse être sauvée sans
avoir été appliquée au daemon.

La validation native vérifie L2/gateways sans routage, refus inter-VLAN puis
routage avec TTL décrémenté, absence de réponse ARP pour la gateway d'un autre
VLAN, capture 802.1Q des deux VLANs sur le trunk et ICMP sur une SVI. Elle exerce
no ip routing, shutdown d'une SVI avec L2 encore disponible, retrait/recréation,
refus de sauvegarde sur dérive CPU/ARP, rollback après suppression réelle et
restore avec une SVI initialement down. Les liens/routes/nft et sysctls de
l'hôte restent inchangés. Références primaires :
[bridge VLAN](https://docs.kernel.org/networking/bridge.html),
[sysctls IPv4](https://docs.kernel.org/networking/ip-sysctl.html),
[interface SVI et autostate Catalyst](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst3850/software/release/16-12/configuration_guide/int_hw/b_1612_int_and_hw_3850_cg/configuring_interface_characteristics.pdf).


## Routes statiques via CLI : aller, retour et longest prefix match

`example --static-routing` crée quatre nodes : PC1 (192.0.2.10/24), SW1 L3
(gateway vlan10 192.0.2.1/24, transit vlan20 198.18.0.1/29), R1 (transit
198.18.0.2/29 et LAN 203.0.113.1/24), PC2 (203.0.113.10/24). Le forwarding
est activé sur SW1/R1, mais aucun des deux ne connaît initialement le LAN distant.
Les clients ont leur gateway locale. Aucun daemon/rootfs supplémentaire.
Selon les valeurs Linux `rp_filter` héritées, une source sans route inverse peut
aussi être rejetée avant que sa requête atteigne le client distant. Le moteur
ne désactive pas cette validation implicitement ; le ping seul ne permet pas
de distinguer ce contrôle de source d’une absence de route de retour.

```bash
python3 -m network_labs.appliances example --static-routing \
  --rootfs "$HOME/network-labs-rootfs" > static-routing-lan.json
sudo python3 -m network_labs.appliances start static-routing-lan.json
sudo python3 -m network_labs.appliances configure static-routing-lan SW1 \
  --text $'conf t\nip route 203.0.113.0 255.255.255.0 198.18.0.2\nend'
# Le chemin aller existe, mais le ping échoue encore : route de retour absente.
sudo python3 -m network_labs.appliances configure static-routing-lan R1 \
  --text $'conf t\nip route 192.0.2.0 255.255.255.0 gi0/0 198.18.0.1\nend'
sudo python3 -m network_labs.appliances exec static-routing-lan PC1 -- \
  /bin/ping -c 3 203.0.113.10
sudo python3 -m network_labs.appliances inspect static-routing-lan SW1
```

Les commandes globales supportées sont :

- `ip route NETWORK NETMASK NEXT_HOP` et la même commande préfixée par `no`.
- `ip route NETWORK NETMASK INTERFACE NEXT_HOP` pour les routes non-default,
  avec alias physique, sous-interface dot1Q ou SVI (`vlan20` ou `Vlan 20`).
- `ip route 0.0.0.0 0.0.0.0 NEXT_HOP` et son `no`, traduits vers le champ
  existant `gateway`. Une default route avec interface explicite est refusée.

Le masque doit être une netmask IPv4 contiguë en notation pointée ; CIDR,
wildcard et host bits dans le préfixe sont refusés. Le next-hop doit être un
peer unicast directement joignable dans un subnet configuré, jamais une adresse
locale. Sans interface explicite, un seul subnet/interface doit correspondre ;
une ambiguïté est refusée, sans sélection implicite. La résolution utilise les
adresses configurées au moment de cette ligne : déclarer les interfaces/adresses
avant leurs routes. La validation finale du bloc vérifie encore sa cohérence.

Les routes non-default utilisent `ip -4 route replace ... proto static` et une
interface explicite dans le manifest. Une seule route par préfixe est supportée ;
changer le next-hop exige `no` puis ajout dans le même bloc. Un ajout identique
est idempotent et `no` ne retire qu'une entrée identique. Les syntaxes ECMP,
distance administrative, next-hop récursif, Null0, VRF, track et IPv6 sont refusées.
Le backend reste Linux et ne reproduit pas les détails RIB/adjacency d'IOS.

Pour observer la priorité d'une route host sur une route moins spécifique :

```bash
sudo python3 -m network_labs.appliances configure static-routing-lan SW1 \
  --text $'conf t\nip route 203.0.113.10 255.255.255.255 vlan20 198.18.0.3\nend'
# .3 est volontairement un peer absent : /32 prend priorité, le ping échoue.
sudo python3 -m network_labs.appliances exec static-routing-lan PC1 -- \
  /bin/ping -c 3 -W 1 203.0.113.10
sudo python3 -m network_labs.appliances configure static-routing-lan SW1 \
  --text $'conf t\nno ip route 203.0.113.10 255.255.255.255 vlan20 198.18.0.3\nend'
# Le chemin /24 redevient utilisable.
```

La validation native capture la requête ICMP réellement arrivée à PC2 quand la
route de retour manque (rp_filter désactivé temporairement sur R1 pour isoler
ce cas de la validation de source Linux), puis restaure les valeurs rp_filter
initiales et valide les pings dans les deux sens et TTL 62
après les deux sauts routés. Elle teste la priorité d'une /32 vers un voisin
absent, la default route sans /24, les retraits/restaurations et le refus de
save après ajout externe d'une route. Une panne injectée après suppression
réelle de la /24 vérifie sa recréation par rollback. Save/stop/restore recrée
routes et default route ; les liens/routes/nft et ip_forward de l'hôte restent
inchangés. Référence de syntaxe :
[Cisco IOS XE, Basic IP Routing](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ip-routing/b-ip-routing/m_iri-iprouting.html).


## Lookup de routage réel et validation de source Linux

La commande `route` interroge la pile Linux du node OCI avec `ip -j -4 route
get`, puis une lecture distincte `get fibmatch`. Elle ne calcule pas un chemin
à partir du dessin et n’envoie ni ping ni probe ARP. Elle affiche la décision
kernel (interface/next-hop/source préférée lorsqu’ils sont retournés), l’entrée
FIB correspondante observée séparément, les règles `ip rule`, les flags du lien
et les entrées voisines déjà connues pour le prochain saut. Une route locale
ou broadcast n’est pas présentée comme un voisin Ethernet à résoudre. Les
contextes via/encap ou objets nexthop non résolus restent dans les relevés bruts
mais ne déclenchent aucune déduction de voisin IPv4 direct.

Après avoir créé/configuré `static-routing-lan` comme dans la section précédente :

```bash
sudo python3 -m network_labs.appliances route static-routing-lan SW1 203.0.113.10
sudo python3 -m network_labs.appliances route static-routing-lan SW1 203.0.113.10 \
  --source 192.0.2.10 --ingress vlan10
sudo python3 -m network_labs.appliances route static-routing-lan R1 192.0.2.10 \
  --source 203.0.113.10 --ingress eth1 --json
sudo python3 -m network_labs.appliances explain static-routing-lan R1
```

Sans `--ingress`, c’est un lookup d’émission locale. `--source` désigne alors
une source locale ; une source non locale peut être refusée par Linux. Avec
`--ingress`, la source originale est obligatoire et Linux interroge le contexte
d’un paquet reçu par cette interface. Utiliser les noms Linux réels du node,
notamment vlan10/vlan20 pour une entrée routée par SVI. Les interfaces inconnues
ou absentes, nodes arrêtés et VMs sans agent invité sont refusés.

Le résultat JSON conserve séparément `lookup`, `fibmatch`, `rules`, `links`,
`selected`, `egress_link`, `neighbor_target`, `neighbors` et `ipv4_settings`.
Chaque lecture JSON a un statut `observed`, `command_failed` ou `unavailable`,
avec code de retour/erreur. Une sortie absente ou invalide ne devient jamais une
route calculée depuis le manifest. Le code de sortie CLI 0 signifie que le
rapport a été produit, même si Linux refuse le lookup ; inspecter ses champs.
`packet_delivery` reste `not_tested` et `test_packets_sent` reste false.

`inspect` expose désormais `ipv4_settings` : rp_filter global `all`, réglage
par interface et valeur effective max(all,interface), ainsi que forwarding
par interface d’entrée. Les noms de sous-interfaces avec point sont lus avec
des chemins sysctl séparés par slash. Une valeur absente, invalide ou une
lecture partielle reste inconnue, jamais assimilée à 0. `explain` décrit ces
faits sans désactiver la validation de source ni affirmer le résultat d’un flux.
Ces paramètres supplémentaires sont observés ; ils n’introduisent pas un
nouveau profil géré ni un audit exhaustif des sysctls dans save/export.

rp_filter 0 désactive ce contrôle, 1 demande le meilleur chemin inverse via
l’interface reçue, 2 exige un chemin inverse disponible. L’état observé ne
suffit pas à reproduire la validation d’un paquet marqué, soumis à des règles
avancées ou à d’autres filtres. Une route sélectionnée ne garantit ni résolution
ARP, ni forwarding, ni passage firewall/NAT, ni retour. Les lectures sont
successives, non atomiques ; une configuration externe peut changer entre elles.
Le lookup utilise le contexte UID observé, sans marque ni sélecteurs TOS/L4.
Il peut créer des entrées de cache internes de routage ; il ne modifie pas les
routes/règles configurées. Le lock du lab couvre les lectures et chaque commande
est bornée à 3 s. Aucun fallback vers l’état de l’hôte ou vers le simulateur.

La validation native vérifie une route absente, les routes aller/retour d’un
vrai LAN, une destination locale, /24 et /32 avec voisin absent. Une capture
ARP/ICMP sur le transit après vidage du voisinage reste vide pendant les
lookups, sans remplissage du cache voisin. Le test vérifie aussi qu’une décision
locale reste observable alors que forwarding est désactivé sur l’entrée et
que les pings échouent. Une règle externe vers une table blackhole provoque
un refus réel malgré le manifest inchangé ; retirer cette règle rétablit
lookup et trafic. Liens/routes/règles/nft et sysctls de l’hôte restent inchangés.

Références : [manuel ip-route du projet iproute2](https://man7.org/linux/man-pages/man8/ip-route.8.html),
[documentation kernel des sysctls IPv4](https://docs.kernel.org/networking/ip-sysctl.html).


### Explications lisibles et états du voisinage

`explain` affiche maintenant les valeurs observées par interface dans son texte,
par exemple `rp_filter all=2 ; effectif : vlan10=loose(2)` et
`Forwarding IPv4 ... vlan10=off`. Une valeur inconnue reste `?` ; un zéro lu reste
explicitement `off(0)` ou `off`, sans être confondu avec une absence de mesure.

`route` ajoute un tableau JSON `findings` avec `code`, `severity`, `message`,
`evidence` et `next_step`. La sortie texte reprend les messages et les points à
vérifier, ainsi que la source préférée si le kernel la retourne. Ce traitement
réutilise le relevé existant : aucune commande ou probe réseau supplémentaire.
Les suggestions ne sont jamais appliquées et aucun succès de ping n’est déduit.

| Observation | Interprétation bornée |
| --- | --- |
| Flags sans UP | Interface administrativement down dans ce relevé |
| UP sans LOWER_UP | Le kernel ne signale pas LOWER_UP ; examiner le parent/lien |
| Forwarding d’entrée à 0 | Désactivé pour le trafic à transférer ; destination locale distincte |
| Cache voisin vide | Aucun voisin observé, sans conclure que le peer est en panne |
| INCOMPLETE | Résolution non terminée, éventuellement transitoire |
| FAILED | Échec de validation du voisin signalé par le kernel, sans attribution à un ping précis |
| STALE / DELAY / PROBE | État de cache/validation, sans annoncer un peer mort |
| REACHABLE / PERMANENT / NOARP | État voisin observé, sans certifier la livraison |
| Donnée manquante / état inconnu | Finding unknown, jamais un zéro ou une panne inventée |

Le relevé voisin conserve aussi `query.target` et `query.device`, provenant
des filtres réellement passés à iproute2. Si le JSON omet `dev` avec un filtre
explicite, la corrélation utilise cette provenance ; la ligne brute reste intacte.
Une interface explicitement différente dans la ligne reste non corrélée.

La lecture utilise `ip neigh show nud all` afin d’inclure NOARP et les états
habituellement masqués par les filtres par défaut. Les destinations locales,
contextes via/encap non pris en charge et données non corrélées au prochain saut
ne deviennent pas des erreurs de résolution IPv4. Une erreur de commande reste
une observation indisponible ; sa cause n’est pas automatiquement « route absente ».

La validation native compare ces findings aux pings/captures existants : absence
de cache sans probe cachée, forwarding d’entrée désactivé, véritable expiration
ARP vers FAILED pour un peer absent, entrée NOARP visible, SVI shutdown puis
récupération. Les contrats vérifient aussi STALE/DELAY/PROBE, données partielles,
absence de modification du relevé et sortie texte avec valeurs effectives.
Référence des états : [ip-neighbour, documentation iproute2](https://man7.org/linux/man-pages/man8/ip-neighbour.8.html).


## DHCPv4 relay: remote single-pool server

`example --dhcp-relay` connects two DHCP clients in VLAN 10 to a BusyBox
DHCP server in VLAN 20 through a Linux L3 switch. A real dnsmasq process
relays DHCP; it does not provide DNS (`port=0`). Client addresses/default
routes are installed by real udhcpc events. Acquisition is asynchronous.

```bash
sudo apt-get install dnsmasq-base
python3 -m network_labs.appliances rootfs \
  --busybox "$(command -v busybox)" --dnsmasq "$(command -v dnsmasq)" \
  --output "$HOME/network-labs-rootfs-relay"
python3 -m network_labs.appliances example --dhcp-relay \
  --rootfs "$HOME/network-labs-rootfs-relay" > dhcp-relay-lan.json
sudo python3 -m network_labs.appliances start dhcp-relay-lan.json
sudo python3 -m network_labs.appliances inspect dhcp-relay-lan PC1
sudo python3 -m network_labs.appliances inspect dhcp-relay-lan SW1
sudo python3 -m network_labs.appliances exec dhcp-relay-lan PC1 -- /bin/ping -c 3 198.51.100.10
```

Use a fresh output directory for the rootfs. `dnsmasq-base` provides the
binary copied with its dependencies into the appliance image; the relay
runs inside SW1, not as a host service.

The relay's manifest policy is:

```json
"dhcp_relay": {
  "interface": "vlan10",
  "upstream_interface": "vlan20",
  "server": "198.51.100.10"
}
```

The first profile requires a forwarding OCI router or Linux L3 switch, two
distinct UP static interfaces/SVIs, disjoint subnets and one directly attached
upstream server. The local client-side IP becomes `giaddr`. The upstream
interface restricts acceptance of server replies. The server uses the explicit
`dhcp_server.network: "192.0.2.0/24"` for pool boundaries, reservations and the
DHCP subnet-mask option. Without this optional field, existing servers retain
their interface-subnet behavior. Remote pools must be disjoint from the server's
connected subnets. Only one pool is supported; BusyBox is not a multi-subnet
pool selector. The example includes the server's return route through
198.51.100.1, also needed for direct client renewal traffic.

PC1 has reservation 192.0.2.100; PC2 receives another address from the pool.
`inspect`/`explain` distinguish managed config-file conformity from UDP socket
observations. Neither proves that a daemon loaded the file or delivered a lease.
External config drift blocks save/export. Restore starts new processes and
acquires fresh leases; it does not snapshot lease files.

The partial IOS adapter accepts `ip helper-address ADDRESS` and
`no ip helper-address ADDRESS` under a routed interface/SVI. One helper per client interface
is supported (up to 32 client interfaces). Its upstream interface must be uniquely directly connected;
removal matches both the client interface and server address. To replace it,
explicitly remove the old helper before adding the new one. This implements
DHCPv4 relay only, not IOS forwarding of other UDP services.

Live helper-only edits stop/restart the real relay and atomically replace its
managed config without changing links, addresses or node containers. Combined
network/helper edits are refused before journaling; recreate the lab for other
network changes while relay is configured. Existing config drift blocks edits.
The journal restores the prior service policy after failure; if rollback also
fails, `recover` reapplies the previous helper. Repeating an unchanged helper
keeps its process and revision: it is not a service-health repair command.
Process control checks executable and exact config argument inside the node's
PID namespace, rather than trusting a pidfile as a signal target.

The new example sets SW1 to `ios-basic`; an already running lab generated by
an older version must be recreated from the new example once. The image must
already contain dnsmasq, including when adding a helper to a node with none.

```bash
sudo python3 -m network_labs.appliances configure dhcp-relay-lan SW1 \
  --text $'configure terminal\ninterface vlan10\nno ip helper-address 198.51.100.10\nend'
sudo python3 -m network_labs.appliances configure dhcp-relay-lan SW1 \
  --text $'configure terminal\ninterface vlan10\nip helper-address 198.51.100.10\nend'
```

Existing leased clients can keep routing and can renew directly to the server
even with the helper removed. A fresh DHCP acquisition is the relevant negative
test; a ping with an existing lease does not establish relay availability.

No DHCPv6, Option 82, multiple servers per client interface, HA or generic UDP forwarding is implemented. Multiple remote pools are described below.
This relay profile cannot share its node with DHCP clients/servers or DNS services,
untracked startup commands or DHCP snooping/ARP inspection/IP source guard.
Other nodes may still run their own services.

The opt-in native case captures DORA and `giaddr` at the server, renewal
Request/ACK, and unanswered client Discover traffic while the relay is stopped.
It checks address removal/reacquisition, independent routing of an existing
lease, configuration drift, save/restore and unchanged host networking. It also
removes/re-adds the helper through CLI, checks unchanged link/container identities,
proves rollback after actual service removal and exercises failed rollback/recovery.
A forged PID 1 pidfile must not prevent stopping the real relay or kill the node.

Reference: [dnsmasq relay options](https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html).


## Multiple DHCP VLANs and remote pools

`example --dhcp-multi` adds a central dnsmasq DHCPv4 server with separate
remote pools. The older BusyBox `dhcp_server` profile remains supported and
keeps its single-pool behavior. Both relay and multi-pool server require the
rootfs built with `--dnsmasq`; reuse `network-labs-rootfs-relay` from above.

```bash
python3 -m network_labs.appliances example --dhcp-multi \
  --rootfs "$HOME/network-labs-rootfs-relay" > dhcp-multi-lan.json
sudo python3 -m network_labs.appliances start dhcp-multi-lan.json
sudo python3 -m network_labs.appliances inspect dhcp-multi-lan PC1
sudo python3 -m network_labs.appliances inspect dhcp-multi-lan PC2
sudo python3 -m network_labs.appliances inspect dhcp-multi-lan DHCP1
```

| Node | VLAN | Address/pool | Gateway | DHCP DNS option |
|---|---|---|---|---|
| PC1 | 10 | Reserved 192.0.2.100/24 | 192.0.2.1 | 192.0.2.53 |
| PC2 | 20 | 198.18.0.100–110/24 | 198.18.0.1 | 198.18.0.53 |
| DHCP1 | 30 | Static 198.51.100.10/24 | Explicit return routes through SW1 | DNS disabled |

The two DNS addresses demonstrate distinct DHCP option values; this example
does not run DNS servers at those addresses. Use numeric targets for ping.
SW1 routes between VLANs: broadcast isolation does not imply an inter-VLAN
firewall. DHCP server selection uses real relay `giaddr` and dnsmasq ranges.
Each pool supplies explicit subnet mask, gateway and resolver options; empty
router/DNS lists suppress dnsmasq defaults rather than inheriting the host's DNS.

The manifest uses `dhcp_pools: {"interface": "eth0", "pools": [...]}` on DHCP1.
Each pool has an explicit `network`, `start`, `end`, and optional `router`, `dns`,
`lease_seconds`, `reservations`. Limits: 1..16 disjoint remote IPv4 subnets,
1..256 dynamic addresses and up to 256 reservations per pool. Reservation MACs
must be globally unique across pools. Pool subnets cannot overlap any connected
server subnet. The server requires explicit return routes to the client networks.
`dhcp_pools` cannot coexist on its node with the older DHCP server/client,
DNS/LLDP/relay services or untracked startup. Pool-server live editing is refused;
change the manifest and recreate the lab. This is not HA or lease replication.

`dhcp_relay` accepts the original single object or a list of up to 32 policies,
one per client interface. Client and upstream interfaces must be disjoint across
the list. The existing CLI supports adding/removing the helper of each VLAN:

```bash
sudo python3 -m network_labs.appliances configure dhcp-multi-lan SW1 \
  --text $'conf t\ninterface vlan10\nno ip helper-address 198.51.100.10\nend'
sudo python3 -m network_labs.appliances configure dhcp-multi-lan SW1 \
  --text $'conf t\ninterface vlan10\nip helper-address 198.51.100.10\nend'
```

Changing a helper restarts the shared relay process briefly and then restores
all remaining policies; it does not restart node containers. The native case
captures DORA/giaddr and Request/ACK renewal for both VLANs, checks distinct
addresses/masks/gateways/resolver options, captures zero client DHCP broadcast
leakage across VLANs, and tests fresh VLAN20 acquisition while VLAN10's helper
is removed. It verifies reacquisition after re-add, drift/save refusal, restore
and unchanged host networking. Save stores declarations, not lease files.


## Native OSPFv2 with BIRD 2

`example --ospf` creates PC1, PC2 and three routers. R1–R2 is the preferred
transit link; R1–R3–R2 is the higher-cost backup. BIRD exchanges actual OSPFv2
packets and installs learned routes in each router's Linux namespace. The
engine does not calculate or insert synthetic topology routes.

```bash
sudo apt-get install bird2
python3 -m network_labs.appliances rootfs \
  --busybox "$(command -v busybox)" \
  --bird "$(command -v bird)" --birdc "$(command -v birdc)" \
  --output "$HOME/network-labs-rootfs-ospf"
python3 -m network_labs.appliances example --ospf \
  --rootfs "$HOME/network-labs-rootfs-ospf" > ospf-lan.json
sudo python3 -m network_labs.appliances start ospf-lan.json
sudo python3 -m network_labs.appliances inspect ospf-lan R1
sudo python3 -m network_labs.appliances exec ospf-lan R1 -- \
  /usr/sbin/birdc -s /run/bird.ctl show ospf neighbors
sudo python3 -m network_labs.appliances exec ospf-lan R1 -- \
  /usr/sbin/birdc -s /run/bird.ctl show route
sudo python3 -m network_labs.appliances exec ospf-lan PC1 -- \
  /bin/ping -c 3 198.51.100.10
```

Use a new rootfs output directory. The builder copies trusted local BIRD 2
executables and their ELF dependencies; daemon execution is inside the router
containers. A BIRD 3 binary is not accepted by this profile. `start` waits for
the control socket, not for OSPF convergence. Neighbor state can take several
seconds to reach Full.

The `ospf` manifest defines `router_id`, `interfaces` (each with `cost` and
`passive`), `hello` and `dead`. Router IDs must be unique in the lab. Defaults
are cost 10, hello 1 second and dead 4 seconds. Forwarding OCI routers and Linux L3 switches support
1..16 UP numbered routed interfaces: physical ports on routers, SVIs on Linux
switches. Disjoint IPv4 subnets and area 0 are required. The older triangle uses point-to-point transit; the broadcast profile
below adds shared Ethernet DR/BDR election. Passive LANs are announced without
sending/receiving OSPF Hello packets. ECMP is disabled.

There is no OSPFv3, multi-area, NBMA/PtMP profile, authentication, BFD,
redistribution, default origination or VRF in this bounded profile. Static/default routes, untracked startup and other managed services
(except the bounded DHCP relay composition below) are rejected on OSPF nodes. The partial IOS adapter supports the OSPF-only edits described below. Changes
to addresses, link state, router ID or process-wide timer defaults still require the manifest and
lab recreation. Real BIRD show commands remain available.

A bounded failure test can be done directly in R1, then restored:

```bash
sudo python3 -m network_labs.appliances exec ospf-lan R1 -- /bin/ip link set eth0 down
# After convergence: R1's remote LAN route uses 10.0.13.2 via R3.
sudo python3 -m network_labs.appliances exec ospf-lan PC1 -- /bin/ping -c 3 198.51.100.10
sudo python3 -m network_labs.appliances exec ospf-lan R1 -- /bin/ip link set eth0 up
```

The primary PC1→PC2 path crosses two routers (TTL 62 with BusyBox's initial
TTL 64); the backup crosses three (TTL 61). Restore externally changed link
state before saving. `inspect`/`explain` retain actual BIRD neighbor/protocol/RIB
text and separate kernel routes. Unavailable or oversized controller output
is unknown, not an empty neighbor table or a convergence verdict. Config-file
conformity does not prove the running daemon loaded an unchanged configuration.

Save/restore persists OSPF declarations, not learned routes, LSDB or adjacency
state. For OSPF nodes only, kernel routes tagged `bird` (protocol 192) are treated
as dynamic and excluded from the static-route drift comparison. This is not an
audit of the full dynamic RIB, nor a guarantee against externally injected routes
using that same protocol tag. Non-BIRD injected routes still fail the static-route
audit, and managed BIRD config-file drift blocks save. Restore reconverges using
new daemon processes.

The native case verifies absent routes/failed traffic before daemon startup,
Full adjacencies, captured OSPFv2 packets, no OSPF packets on a passive LAN,
actual preferred and backup FIB next hops and routed TTL, withdrawal after both
R1 transit links fail, recovery, daemon shutdown route removal, config/static-route
drift refusal and restore. Baseline host links/routes/rules/nft/forwarding are
checked after cleanup.

Reference: [BIRD 2 configuration and OSPF documentation](https://bird.nic.cz/doc/bird-2.16.2.html).


### Managed OSPF configuration from the partial IOS adapter

Recreate old `ospf-lan` examples once: the new example enables `dialect: ios-basic`
on the three routers. It declares one process (`process_id`, default 1). The adapter can also create
or remove that single process; multiple processes and Cisco firmware are outside
this profile. Its real BIRD daemon remains running
while managed commands reload its configuration. Reload completion does not
mean neighbors have converged or traffic has succeeded.

```bash
# Preferred R1-to-R2 cost becomes 100, selecting R1-to-R3-to-R2 instead.
sudo python3 -m network_labs.appliances configure ospf-lan R1 \
  --text $'configure terminal\ninterface eth0\nip ospf cost 100\nend'
sudo python3 -m network_labs.appliances exec ospf-lan R1 -- \
  /usr/sbin/birdc -s /run/bird.ctl show route
sudo python3 -m network_labs.appliances exec ospf-lan PC1 -- \
  /bin/ping -c 3 198.51.100.10
# Restore the primary cost.
sudo python3 -m network_labs.appliances configure ospf-lan R1 \
  --text $'conf t\ninterface eth0\nip ospf cost 10\nend'

# Stop R1's OSPF adjacency on eth0 while retaining its connected IP/link.
sudo python3 -m network_labs.appliances configure ospf-lan R1 \
  --text $'conf t\nrouter ospf 1\npassive-interface eth0\nend'
sudo python3 -m network_labs.appliances configure ospf-lan R1 \
  --text $'conf t\nrouter ospf 1\nno passive-interface eth0\nend'

# Disable/re-enable OSPF on the subnet selected by this stored statement.
sudo python3 -m network_labs.appliances configure ospf-lan R1 \
  --text $'conf t\nrouter ospf 1\nno network 10.0.12.0 0.0.0.3 area 0\nend'
sudo python3 -m network_labs.appliances configure ospf-lan R1 \
  --text $'conf t\nrouter ospf 1\nnetwork 10.0.12.0 0.0.0.3 area 0\nend'
```

Supported commands select or create one process, delete it with `no router ospf
ID`, set an explicit cost 1..65535,
set/unset passive on a declared OSPF interface, and add/remove `network ADDRESS
WILDCARD area 0` (also `area 0.0.0.0`). Wildcards must be contiguous; `0.0.0.0`
selects an exact local address. The command selects interfaces by their primary
IPv4 address; it does not advertise an arbitrary remote prefix. A selector must
match an existing numbered physical interface. Non-zero areas, additional processes, live router-ID/process-wide timer edits, passive-default,
cost auto-calculation,
interface-level `ip ospf PROCESS area AREA` and other syntax are rejected.

`ospf.networks` stores up to 64 canonical IPv4 selector prefixes. When omitted,
it defaults to the subnet of each declared OSPF interface. All selectors are in
area 0. Overlapping selectors remain independent: removing one disables an
interface only when no remaining selector matches. Interface cost/passive options
remain stored while deselected. At least one selected non-passive transit
interface must remain; an empty/stopped process is outside this profile.
No bandwidth-based automatic cost is claimed: the manifest default remains 10.

Before journaling, live edits require a matching managed config file and a BIRD
control response with no pending or unconfirmed reconfiguration. The candidate
file is syntax-checked with the real BIRD parser, replaced atomically, and loaded
through its control socket. Apply failures reload the previous policy; interrupted
or failed rollback can use `recover`. Ordinary edits reload the existing daemon; explicit process creation/removal
starts/stops BIRD. Interfaces and addresses remain in place. Before ordinary
edits or removal, a missing/unmanaged daemon is refused. Recovery reconciles
the journal target, including restarting a removed daemon or undoing creation. These observations cannot exclude concurrent external
BIRD control commands; don't mix unmanaged BIRD edits with managed configuration.

The expanded native OSPF test verifies cost-based next-hop changes without
physical failure, including captured request TTL 61 at PC2 while replies retain
TTL 62 on their unchanged reverse path, passive adjacency loss and recovery, overlapping network selector
removal/re-add, preserved BIRD/container/link identities, unchanged revision for
idempotent edits, pre-journal drift refusal, rollback after actual BIRD reload,
failed rollback followed by recovery, and save/restore. The general tests cover
invalid contexts, wildcard/profile limits and pending/unknown control responses.


### Create and remove OSPF processes through CLI

Reuse a rootfs built with both BIRD 2 binaries (see setup above).
`--ospf-cli` starts the same five-node topology with interface addresses and
forwarding configured, but no OSPF processes or learned routes. Configure each
router in a complete block; an unfinished process without an explicit unique
router ID and at least one active network selector is rejected atomically.

```bash
python3 -m network_labs.appliances example --ospf-cli \
  --rootfs "$HOME/network-labs-rootfs-ospf" > ospf-cli-lan.json
sudo python3 -m network_labs.appliances start ospf-cli-lan.json

sudo python3 -m network_labs.appliances configure ospf-cli-lan R1 \
  --text $'conf t\nrouter ospf 1\nrouter-id 1.1.1.1\nnetwork 10.0.12.0 0.0.0.3 area 0\nnetwork 10.0.13.0 0.0.0.3 area 0\nnetwork 192.0.2.0 0.0.0.255 area 0\npassive-interface eth2\ninterface eth1\nip ospf cost 30\nend'
sudo python3 -m network_labs.appliances configure ospf-cli-lan R2 \
  --text $'conf t\nrouter ospf 1\nrouter-id 2.2.2.2\nnetwork 10.0.12.0 0.0.0.3 area 0\nnetwork 10.0.23.0 0.0.0.3 area 0\nnetwork 198.51.100.0 0.0.0.255 area 0\npassive-interface eth2\nend'
sudo python3 -m network_labs.appliances configure ospf-cli-lan R3 \
  --text $'conf t\nrouter ospf 1\nrouter-id 3.3.3.3\nnetwork 10.0.13.0 0.0.0.3 area 0\nnetwork 10.0.23.0 0.0.0.3 area 0\ninterface eth0\nip ospf cost 30\nend'

# Wait for neighbors to reach Full, then verify traffic.
sudo python3 -m network_labs.appliances exec ospf-cli-lan R1 -- \
  /usr/sbin/birdc -s /run/bird.ctl show ospf neighbors
sudo python3 -m network_labs.appliances exec ospf-cli-lan PC1 -- \
  /bin/ping -c 3 198.51.100.10

# Removing R1's process withdraws its daemon-owned routes and connectivity.
sudo python3 -m network_labs.appliances configure ospf-cli-lan R1 \
  --text $'conf t\nno router ospf 1\nend'
# Reapply the complete R1 block above to restore it.
```

`router ospf ID` creates a process only on a forwarding OCI router with the
required image assets. IDs range from 1..65535 and are locally significant;
router IDs must be unique across active lab processes. No automatic router-ID
selection is performed. `router-id` can set the ID while creating a process;
changing the ID of an existing process requires separate delete/create blocks.
Missing/mismatched IDs on deletion are refused. Creation/removal must not be
combined with IP/link/static-route or other service changes. The router's
addresses and forwarding must already be configured. Existing profile limits
(area 0, numbered point-to-point/broadcast transit and passive LAN interfaces) still apply.

Creation checks for executable BIRD assets, existing BIRD processes and conflicting
managed config/control paths before journaling. Removal verifies the executable
and config/control argv inside the container namespace, signals only the managed
non-init process, waits for its exit, and removes its config/control files.
`bird.pid` is never used to select a kill target. An unrelated BIRD process
causes refusal and is left untouched. Process creation can reconverge after the
command returns; a successful command does not certify end-to-end traffic.

The native case additionally verifies actual route withdrawal and failed traffic
after deletion, container/link survival with a forged PID 1 pidfile, refusal
without stopping a separate real BIRD daemon, rollback after actual removal
and after actual creation, failed creation rollback followed by `recover`, and
save/restore both with the process absent and with its recreated policy active.


### Shared Ethernet OSPF broadcast, DR and BDR

`example --ospf-broadcast` creates seven nodes: four routers on a common switch,
plus PC1 behind R3 and PC2 behind R4. The switch explicitly disables IGMP snooping
in this example so that this lab exercises OSPF multicast over a plain shared LAN.
It does not test the coexistence of OSPF with the optional snooping profile.

```bash
python3 -m network_labs.appliances example --ospf-broadcast \
  --rootfs "$HOME/network-labs-rootfs-ospf" > ospf-broadcast-lan.json
sudo python3 -m network_labs.appliances start ospf-broadcast-lan.json
sudo python3 -m network_labs.appliances exec ospf-broadcast-lan R3 -- \
  /usr/sbin/birdc -s /run/bird.ctl show ospf interface
sudo python3 -m network_labs.appliances exec ospf-broadcast-lan R3 -- \
  /usr/sbin/birdc -s /run/bird.ctl show ospf neighbors
sudo python3 -m network_labs.appliances exec ospf-broadcast-lan PC1 -- \
  /bin/ping -c 3 198.51.100.10
```

The shared transit subnet is `10.0.100.0/24`; router R1..R4 uses address `.1`..`.4`.
Priorities are 200, 100, 1 and 0. With a fresh simultaneous startup, the example
expects R1 as DR, R2 as BDR, and R3/R4 as DROther. R3 and R4 normally remain
2-Way with each other while each forms Full adjacencies with the DR and BDR.
A 2-Way DROther pair is not, by itself, an adjacency failure. Priority 0 prevents
R4 becoming DR/BDR but does not stop it exchanging routes or forwarding traffic.

`ospf.interfaces.PORT.network_type` accepts `point-to-point` (the legacy default)
or `broadcast`. `priority` is an integer 0..255, default 1; values other than 1
require broadcast. The generated BIRD config explicitly sets network type and,
for broadcast, election priority and wait timer equal to the declared dead timer.
The example retains the lab timers hello 1/dead 4 seconds. Do not infer Cisco
Ethernet defaults from this adapter's legacy point-to-point default.

The partial IOS adapter can change these options on a declared OSPF interface:

```bash
sudo python3 -m network_labs.appliances configure ospf-broadcast-lan R4 \
  --text $'conf t\ninterface eth0\nip ospf network broadcast\nip ospf priority 255\nend'
# Reset priority to 1, then explicitly choose point-to-point if required:
# conf t / interface eth0 / no ip ospf priority / ip ospf network point-to-point / end
# For this shared-LAN example, restore R4's broadcast priority 0:
sudo python3 -m network_labs.appliances configure ospf-broadcast-lan R4 \
  --text $'conf t\ninterface eth0\nip ospf network broadcast\nip ospf priority 0\nend'
```

Existing DR/BDR elections are non-preemptive; raising priority or returning an
older higher-priority router does not force an existing DR out of its role.
Changing network type may disrupt adjacencies and requires matching peer settings;
there is no automatic cross-node coordination or computed election. The engine
only renders policy, reloads BIRD, and observes its actual interface/neighbor text.
`inspect`/`explain` now include bounded `show ospf interface ospf4` output; missing
output stays unknown. No inferred DR/BDR or universal convergence flag is supplied.

The native case verifies all initial DR/BDR/DROther roles, actual Full and 2-Way
neighbors, captured OSPFv2 multicast Hellos, priority-0 exclusion, BDR promotion
when R1's link goes down, and R1's non-preemptive return. It verifies that real
PC1/PC2 traffic crosses R3/R4 directly (kernel next hop `.4`, reply TTL 62), even
while the DR changes. Actual CLI priority changes and point-to-point/broadcast
reloads are checked against BIRD output, followed by recovered adjacencies and
traffic. Save/restore preserves the declared type/priority, then new daemons run
a fresh election; elected roles are not saved. Baseline host links, routes, rules,
nft policy and forwarding remain checked after cleanup.

References: [BIRD 2 OSPF options](https://bird.nic.cz/doc/bird-2.16.2.html),
[Cisco OSPF interface states and priority](https://www.cisco.com/c/en/us/support/docs/ip/open-shortest-path-first-ospf/13689-17.html),
and [Cisco explanation of normal 2-Way neighbors](https://www.cisco.com/c/en/us/support/docs/ip/open-shortest-path-first-ospf/13683-11.html).


### Per-interface OSPF Hello and Dead timers

The partial IOS adapter accepts `ip ospf hello-interval SECONDS` and
`ip ospf dead-interval SECONDS` under a declared OSPF interface. These commands
set the real BIRD interface timers; they do not change timers on other ports.
`ospf.interfaces.PORT.hello` and `.dead` are optional integer overrides. Without
an override, the interface inherits `ospf.hello`/`ospf.dead` (legacy lab defaults
1/4 seconds). Overrides remain explicit through save/restore; inheritance is not
silently converted into a stored per-port value. Broadcast's wait timer follows
the effective per-interface dead timer.

This bounded profile permits hello 1..60 seconds and dead 2..240 seconds, with
dead strictly greater than hello. The complete command block is validated before
any journal or daemon change, so a block can set both timers in either order.
Fast Hello/hello-multiplier, millisecond timers, BFD and `no ...-interval` reset
syntax are unsupported. Use explicit positive values to change timers back;
these values are profile settings, not a promise of Cisco's factory defaults.
Process-wide timer defaults remain manifest-only for existing processes.

On the existing `example --ospf` triangle (`ospf-lan`), the R1–R2 link is eth0 at
both ends. R1–R3 and R2–R3 retain their original timers:

```bash
# Mismatch R1's primary link: R2 still uses hello 1/dead 4.
sudo python3 -m network_labs.appliances configure ospf-lan R1 \
  --text $'conf t\ninterface eth0\nip ospf hello-interval 2\nip ospf dead-interval 8\nend'
sudo python3 -m network_labs.appliances exec ospf-lan R1 -- \
  /usr/sbin/birdc -s /run/bird.ctl show ospf neighbors
sudo python3 -m network_labs.appliances exec ospf-lan R1 -- \
  /usr/sbin/birdc -s /run/bird.ctl show ospf interface
# After actual convergence, the surviving R1–R3–R2 path carries the traffic.
sudo python3 -m network_labs.appliances exec ospf-lan PC1 -- \
  /bin/ping -c 3 198.51.100.10

# Match R2 to reestablish the primary adjacency and path.
sudo python3 -m network_labs.appliances configure ospf-lan R2 \
  --text $'conf t\ninterface eth0\nip ospf hello-interval 2\nip ospf dead-interval 8\nend'
# Optional: explicitly restore 1/4 at both ends.
sudo python3 -m network_labs.appliances configure ospf-lan R1 \
  --text $'conf t\ninterface eth0\nip ospf hello-interval 1\nip ospf dead-interval 4\nend'
sudo python3 -m network_labs.appliances configure ospf-lan R2 \
  --text $'conf t\ninterface eth0\nip ospf hello-interval 1\nip ospf dead-interval 4\nend'
```

Peers on a link must use compatible Hello/Dead timers. The adapter deliberately
does not rewrite peer configurations or declare convergence: a mismatch can
break an adjacency and alter real routing. On a broadcast LAN, coordinate every
participating router's timers; this is not an automatic multi-node transaction.
Reload completion is separate from neighbor expiry, election and SPF convergence.

The native timer case checks invalid-block refusal before revision changes,
actual primary-adjacency loss with the R1/R2 mismatch, retained Full neighbors
on the other links, the real backup kernel next hop and TTL-61 ping, and a PCAP
whose decoded R1 Hello carries Hello Timer 2s/Dead Timer 8s. Matching R2 restores
Full adjacency and TTL-62 primary traffic. Daemon/container/link identities stay
unchanged through these edits. Save/restore preserves the nondefault overrides;
a failure injected after an actual timer reload exercises rollback to the prior
2/8 configuration, followed by real adjacency/traffic recovery. Host networking
cleanup checks remain required.


### OSPF on Linux L3-switch VLAN interfaces

`example --ospf-svi` provides five real OCI nodes. PC1 (192.0.2.10/24) uses
SW1's passive VLAN10 gateway (192.0.2.1). SW1's VLAN20 (198.18.0.1/29)
forms a broadcast OSPF adjacency with R1 (198.18.0.2/29), through a tagged
VLAN20 trunk to the L2 switch SW2 and an access port to R1. PC2
(203.0.113.10/24) uses R1's passive LAN gateway (203.0.113.1).
The two endpoints need no manually configured remote-prefix routes;
BIRD learns them and installs them in each transit node's Linux FIB.

Use the trusted BIRD-enabled rootfs built in the OSPF setup above:

```bash
python3 -m network_labs.appliances example --ospf-svi \
  --rootfs "$HOME/network-labs-rootfs" > ospf-svi.json
sudo python3 -m network_labs.appliances start ospf-svi.json
sudo python3 -m network_labs.appliances exec ospf-svi-lan SW1 -- \
  /usr/sbin/birdc -s /run/bird.ctl show ospf neighbors
sudo python3 -m network_labs.appliances exec ospf-svi-lan PC1 -- \
  /bin/ping -c 3 203.0.113.10
sudo python3 -m network_labs.appliances configure ospf-svi-lan SW1 \
  --text $'conf t\ninterface vlan 20\nip ospf cost 40\nend'
sudo python3 -m network_labs.appliances inspect ospf-svi-lan SW1
sudo python3 -m network_labs.appliances save ospf-svi-lan
sudo python3 -m network_labs.appliances stop ospf-svi-lan
sudo python3 -m network_labs.appliances restore ospf-svi-lan
```

On a switch, `ospf.interfaces` keys and `network` selectors resolve only declared
SVIs, never L2 ports or br0. `interface vlan 20` / `interface vlan20` select an
existing SVI for OSPF cost, type, priority and Hello/Dead policy. Router-process
creation/removal and `passive-interface vlan10` use the same partial IOS adapter
as routers. Creation needs a complete explicit policy; e.g. router-id 1.1.1.1,
network 192.0.2.0 0.0.0.255 area 0, network 198.18.0.0 0.0.0.7 area 0,
passive-interface vlan10 and broadcast type on vlan20. Match R1's transit type
and timers. A cost edit on this single-path example changes the metric, not the
physical path.

SVIs and `ip routing` must already be configured before creating OSPF. While
OSPF exists, combined SVI/address/VLAN/forwarding changes are refused before
journaling. Remove OSPF first or recreate the lab to change underlying networking.
Existing staged parser checks, reload, rollback/recover and drift/save checks apply.
Save stores declarations; restore rebuilds SVIs and starts a fresh routing daemon,
which must reconverge. It does not save learned routes or neighbors.

This profile excludes OVS SVIs, switch physical routed ports, router subinterfaces,
bundles and co-located DHCP clients/servers, DNS/firewall, bridge security or
explicit multicast policies. The bounded DHCP relay and physical-port LLDP compositions below are supported. It does not implement Catalyst per-VLAN autostate or all vendor behavior.
The example uses the default Linux bridge multicast behavior; optional snooping
policy coexistence has not been validated.

The privileged test checks Full adjacency on the actual SVI, learned forward and
return routes with vlan20 egress, bidirectional TTL-62 pings, decoded VLAN20-tagged
OSPF Hellos on the trunk and zero OSPF packets on passive VLAN10. It reloads a
cost without replacing the daemon/SVI, removes/recreates the switch OSPF process
to verify route withdrawal and failed/recovered traffic, then saves/restores the
nondefault cost and SVIs. Baseline host links/routes/rules/nft/forwarding remain
checked after cleanup.


### OSPF and DHCP relay on the same L3 switch

`example --ospf-dhcp` extends the SVI/trunk lab to six nodes. PC1 now obtains
192.0.2.100/24 and gateway 192.0.2.1 from a reserved remote pool on DHCP1
(198.18.0.3/29), via SW1's VLAN10 relay and VLAN20 upstream SVI. DHCP1 connects
to an access port on SW2. SW1 also runs BIRD OSPF on VLAN20 and advertises
passive VLAN10; R1 learns the DHCP-client subnet through actual OSPF.
PC1 and PC2 (203.0.113.10) exchange real traffic through SW1 and R1.

The DHCP server remains **on-link to the relay's upstream SVI**. Its explicit
static return route to 192.0.2.0/24 uses 198.18.0.1. This composition does not add
multi-hop DHCP helpers or require OSPF convergence for DHCP acquisition. OSPF
learned routes provide remote-client connectivity; DHCP still works if the OSPF
process is removed, while traffic requiring learned routes fails.

Build a fresh trusted rootfs containing both service executables:

```bash
sudo apt-get install crun iproute2 busybox-static bird2 dnsmasq-base
python3 -m network_labs.appliances rootfs --busybox /bin/busybox \
  --bird /usr/sbin/bird --birdc /usr/sbin/birdc \
  --dnsmasq /usr/sbin/dnsmasq --output "$HOME/network-labs-ospf-dhcp-rootfs"
python3 -m network_labs.appliances example --ospf-dhcp \
  --rootfs "$HOME/network-labs-ospf-dhcp-rootfs" > ospf-dhcp.json
sudo python3 -m network_labs.appliances start ospf-dhcp.json
sudo python3 -m network_labs.appliances exec ospf-dhcp-lan PC1 -- \
  /bin/busybox ip -4 addr show dev eth0
sudo python3 -m network_labs.appliances exec ospf-dhcp-lan PC1 -- \
  /bin/ping -c 3 203.0.113.10
sudo python3 -m network_labs.appliances inspect ospf-dhcp-lan SW1
```

A DHCP address may arrive asynchronously after start. Check the actual lease and
OSPF neighbors before interpreting failed pings. The example runs no DNS server.
Use an unused rootfs output directory; the builder refuses existing output.

Live changes select the service whose policy changed, including journal rollback
and `recover`. An OSPF-only edit reloads BIRD and preserves the relay process;
a helper-only edit restarts the relay and preserves BIRD. Removing one service
leaves the other running. Idempotent blocks on a co-located node preflight both
services without reloading either. Changes to both policies in one block, or
combined service/network edits, are refused before journaling. Make separate
transactions; there is no distributed or multi-service atomic transaction.
Normal edits preflight the selected service, not the unchanged service's complete
runtime state. Save still audits both managed config files and network drift.

```bash
sudo python3 -m network_labs.appliances configure ospf-dhcp-lan SW1 \
  --text $'conf t\ninterface vlan20\nip ospf cost 40\nend'
sudo python3 -m network_labs.appliances configure ospf-dhcp-lan SW1 \
  --text $'conf t\ninterface vlan10\nno ip helper-address 198.18.0.3\nend'
sudo python3 -m network_labs.appliances configure ospf-dhcp-lan SW1 \
  --text $'conf t\ninterface vlan10\nip helper-address 198.18.0.3\nend'
sudo python3 -m network_labs.appliances save ospf-dhcp-lan
sudo python3 -m network_labs.appliances stop ospf-dhcp-lan
sudo python3 -m network_labs.appliances restore ospf-dhcp-lan
```

Existing leases can continue routing during helper removal; new acquisition
fails. The privileged composition case verifies reserved address/default gateway,
bidirectional TTL-62 traffic through OSPF routes, captured DORA and giaddr,
unsuccessful discovery without a helper, unchanged BIRD during helper edits,
unchanged relay during OSPF edits, failed helper rollback followed by actual
recovery, and DHCP acquisition while OSPF is absent. It saves/restores both
policies and checks host links/routes/rules/nft/forwarding after cleanup.
Restore reacquires a lease and reconverges OSPF; runtime leases/neighbors are not
snapshotted. Existing single-service profile limits remain in force; this does
not enable DHCP/DNS/security services arbitrarily on every OSPF node. The physical-port LLDP composition below is supported.


### Two DHCP client VLANs with OSPF and scoped recovery

`example --ospf-dhcp-multi` extends the previous composition to seven nodes:

| Node/interface | Network | Purpose |
|---|---|---|
| PC1 / SW1 vlan10 | 192.0.2.0/24 | DHCP reservation .100, gateway .1 |
| PC3 / SW1 vlan30 | 198.51.100.0/24 | Independent DHCP reservation .100, gateway .1 |
| SW1 vlan20 / SW2 / R1 eth0 | 198.18.0.0/29 | Tagged VLAN20 transit; broadcast OSPF |
| DHCP1 eth0 | 198.18.0.3/29 | Two remote pools; explicit return route to each client subnet |
| R1 eth1 / PC2 | 203.0.113.0/24 | Remote LAN, PC2 .10 and gateway .1 |

Both client SVIs are passive OSPF advertisements. R1 learns both client prefixes;
SW1 learns the remote LAN. The VLAN20 trunk carries transit traffic, while the
two DHCP client ports remain in separate access VLANs. Inter-VLAN client traffic
is routed by SW1 (BusyBox TTL 63), and traffic to PC2 crosses SW1 and R1 (TTL 62).
The server is still on-link to the relay upstream; multi-hop helpers are not added.
No DNS service is configured.

Use the BIRD-and-dnsmasq rootfs from the preceding section:

```bash
python3 -m network_labs.appliances example --ospf-dhcp-multi \
  --rootfs "$HOME/network-labs-ospf-dhcp-rootfs" > ospf-dhcp-multi.json
sudo python3 -m network_labs.appliances start ospf-dhcp-multi.json
sudo python3 -m network_labs.appliances exec ospf-dhcp-multi-lan PC1 -- \
  /bin/ping -c 3 198.51.100.100
sudo python3 -m network_labs.appliances exec ospf-dhcp-multi-lan PC3 -- \
  /bin/ping -c 3 203.0.113.10
sudo python3 -m network_labs.appliances exec ospf-dhcp-multi-lan R1 -- \
  /usr/sbin/birdc -s /run/bird.ctl show route
sudo python3 -m network_labs.appliances configure ospf-dhcp-multi-lan SW1 \
  --text $'conf t\ninterface vlan10\nno ip helper-address 198.18.0.3\nend'
sudo python3 -m network_labs.appliances configure ospf-dhcp-multi-lan SW1 \
  --text $'conf t\ninterface vlan10\nip helper-address 198.18.0.3\nend'
```

Wait for actual leases and OSPF convergence after start. Removing VLAN10's helper
retains VLAN30's helper and both routing advertisements. The shared relay daemon
restarts briefly for a helper change; uninterrupted DHCP during that restart is
not guaranteed. Once loaded, the remaining VLAN30 helper can handle fresh DORA
while VLAN10 discovery receives no offer. Existing leases can still route.

New network and firewall transactions persist `pending_node` alongside the
pending manifest **before** applying changes. After failed rollback, `recover`
reconciles that node only, preserving services on unrelated nodes. It validates
the target name/runtime, node ordering and that the other declarations/topology
are unchanged before touching any node. An invalid scoped journal is retained
and refused. Equal desired/pending declarations still reconcile the target:
a partially executed idempotent operation may have changed actual kernel state.
Successful commit, rollback or recovery clears both journal fields.

Older journals without `pending_node` retain the legacy all-node reconciliation
behavior for compatibility. This marker scopes a single-node transaction; it is
not a distributed transaction or a filesystem/lease/adjacency snapshot. Recovery
on the target still uses the appropriate existing service or LAN adapter.

The privileged multi-VLAN case captures DORA and the distinct giaddr for both
pools, observes zero DHCP packets on released PC1's VLAN during fresh PC3 DORA,
checks actual addresses/default gateways, both learned return routes and routed
TTL-63/TTL-62 traffic. It removes only VLAN10's helper, verifies unanswered fresh
VLAN10 discovery and successful fresh VLAN30 acquisition, restores the helper,
then injects failure after an actual OSPF cost reload on R1 and fails rollback.
Scoped recovery restores R1 while preserving SW1's real BIRD and relay PIDs.
Save/stop/restore reacquires both reserved leases and reconverges OSPF. Host
links/routes/rules/nft/forwarding remain checked after cleanup.


### Physical LLDP alongside OSPF and DHCP

`example --ospf-dhcp-lldp` extends the seven-node multi-VLAN lab above. Real
lldpd daemons run on SW1, SW2 and R1, restricted to these physical ports:

| Local node / port | Expected received peer / advertised port |
|---|---|
| SW1 eth1 | SW2 eth0 (trunk) |
| SW2 eth0 | SW1 eth1 (trunk) |
| SW2 eth1 | R1 eth0 (access VLAN20) |
| R1 eth0 | SW2 eth1 |

This table describes the example, not fabricated observation. `inspect` retains
actual daemon JSON; missing evidence remains unknown. SW1 and R1 are OSPF peers
on VLAN20 but are not direct LLDP neighbors: SW2 lies between them. Client/server
access ports and SVIs do not advertise LLDP in this example. The interface
selection follows the [lldpd manual](https://lldpd.github.io/usage.html); Linux
physical access/trunk ports are supported, while virtual SVIs, LACP and OVS
coexistence remain excluded. LLDP advertisements are unauthenticated and do not
establish delivery, routing convergence or application health.

Build a **new** image directory containing all three service assets:

```bash
sudo apt install -y busybox-static bird2 dnsmasq-base lldpd
python3 -m network_labs.appliances rootfs \
  --busybox /bin/busybox --bird /usr/sbin/bird --birdc /usr/sbin/birdc \
  --dnsmasq /usr/sbin/dnsmasq --lldpd /usr/sbin/lldpd --lldpcli /usr/sbin/lldpcli \
  --output "$HOME/network-labs-ospf-dhcp-lldp-rootfs"
python3 -m network_labs.appliances example --ospf-dhcp-lldp \
  --rootfs "$HOME/network-labs-ospf-dhcp-lldp-rootfs" > ospf-dhcp-lldp.json
sudo python3 -m network_labs.appliances start ospf-dhcp-lldp.json
sudo python3 -m network_labs.appliances exec ospf-dhcp-lldp-lan SW2 -- \
  /usr/sbin/lldpcli -u /run/lldpd.socket show neighbors details
sudo python3 -m network_labs.appliances inspect ospf-dhcp-lldp-lan SW1
# Wait for DHCP addresses and OSPF convergence before testing delivery.
sudo python3 -m network_labs.appliances verify ospf-dhcp-lldp-lan PC1 PC2 --bidirectional
sudo python3 -m network_labs.appliances configure ospf-dhcp-lldp-lan SW1 \
  --text $'conf t\ninterface vlan20\nip ospf cost 55\nend'
sudo python3 -m network_labs.appliances save ospf-dhcp-lldp-lan
sudo python3 -m network_labs.appliances stop ospf-dhcp-lldp-lan
sudo python3 -m network_labs.appliances restore ospf-dhcp-lldp-lan
```

Separate OSPF-only and helper-only live edits preserve the LLDP policy and
processes. LLDP policy/port changes and underlying network edits on LLDP nodes
are refused before journaling; recreate the lab for those changes. A no-op
configuration does not reapply networking. Selected-service preflight still
audits that service only; an OSPF edit does not repair or certify LLDP. Save
checks the existing managed LLDP file, live global policy and port-status
baseline as well as the other services. Restore starts fresh daemons and must
rediscover neighbors, reacquire leases and reconverge OSPF; no runtime tables
are snapshotted.

The privileged composition case checks exact received local-port/peer/remote-port
pairs (including absence of a false SW1–R1 LLDP hop), untagged LLDP and tagged
VLAN20 OSPF in an actual trunk PCAP, both DHCP addresses and bidirectional TTL-62
remote traffic. Cost/helper edits preserve LLDP process identities; fresh DHCP
still works afterwards. Trunk loss ages out the affected LLDP neighbors, expires
OSPF adjacency and breaks remote delivery, while SW2–R1 discovery remains.
Link return restores discovery and routing. Save/restore retains the nondefault
cost and rediscovers actual neighbors. Host links/routes/rules/nft/forwarding
are checked after cleanup. No convergence-time or lossless-failover guarantee is
made, and generic service/security combinations remain outside this profile.


### Readable received LLDP neighbors

`inspect LAB NODE` keeps the original LLDP JSON0 in `lldp.neighbors` and adds
`lldp.neighbor_summary`, normalized from **that same read**, with no extra query.
`explain LAB NODE` prints each received local port, announced name/chassis,
remote port identifier with its subtype, and advertised TTL. The upstream
[lldpd JSON0 integration contract](https://github.com/lldpd/lldpd/blob/master/tests/integration/test_lldpcli.py)
defines the array structure; unfamiliar or malformed data remains unknown/partial.

```bash
sudo python3 -m network_labs.appliances explain ospf-dhcp-lldp-lan SW2
sudo python3 -m network_labs.appliances inspect ospf-dhcp-lldp-lan SW2
sudo python3 -m network_labs.appliances explain ospf-dhcp-lldp-lan SW2 --json
```

A received SW2 record can describe local `eth0`, announced chassis/name `SW1`,
port ID subtype `ifname` and value `eth1`, with advertised TTL 6 seconds. That TTL
is not a remaining-lifetime countdown; the daemon's age label is retained without
calculating expiry. A MAC/local port ID is preserved as such, never guessed to be
a physical interface name. A missing system name uses only the received chassis
ID for display. Names are unauthenticated claims, not resolved against managed
node names or declared cables. Repeated local ports remain repeated records;
multiple advertisements are not collapsed into a dictionary.

Summary status `observed` means the supported record structure was decoded,
including a genuinely empty table. `partial` preserves decoded records/identifiers
while counting rejected entries or marking malformed optional fields. `unknown`
means the table could not be decoded; it is not an empty-table verdict. Raw JSON
remains available whenever the existing bounded daemon read returned it. Displayed advertised
text is JSON-escaped; the underlying evidence retains its original value.

An empty table does not establish a failed link or failed packet delivery.
Neither normalized LLDP nor file conformity certifies DHCP acquisition, OSPF
convergence or application health. `explain` stays passive and leaves state and
revision untouched; use explicit `verify` for bounded delivery tests. The native
composition case checks decoded exact port pairs through loss/return/restore,
actual TTL values after fresh announcements, passive rendered/JSON findings
and unchanged state. Startup may briefly retain an earlier advertised TTL; the
parser never replaces it with the declared policy. The
standalone LLDP case checks an unavailable daemon produces unknown summary data.


### Explicit connectivity verification between managed hosts

`verify LAB SOURCE DESTINATION` resolves both endpoints from actual kernel IPv4
address snapshots and executes a bounded real ICMP test. It works with DHCP
addresses without copying the current lease into a command. Endpoints must be
different running OCI hosts, each with one physical eth0 and exactly one usable
global-scope IPv4 address. This first profile excludes router/switch/VM endpoints,
multiple NICs, subinterfaces, port channels and ambiguous address selection.
There is no fallback to a declared IP if the kernel has no usable address.

```bash
sudo python3 -m network_labs.appliances verify ospf-dhcp-multi-lan PC1 PC2
sudo python3 -m network_labs.appliances verify ospf-dhcp-multi-lan PC1 PC3 \
  --bidirectional --count 2
sudo python3 -m network_labs.appliances verify ospf-dhcp-multi-lan PC2 PC1 \
  --bidirectional --json
```

The default count is 3, bounded to 1..5 per direction. `--bidirectional` executes
two separate round-trip tests. Each uses numeric ping bound to eth0, one-second
reply timeout and a count+2-second deadline; the command wrapper times out at
count+5 seconds. The lab lock stays held during this bounded operation, so other
lab lifecycle/configuration operations wait. A capture started beforehand can
continue recording the packets. Individual kernel/container reads time out after
3 seconds. No configuration is written, but probes can update ARP/neighbor
caches, counters and conntrack. `explain` and `route` remain passive commands.

Human output is French; `--json` includes endpoint kernel evidence, observed
source route-get records before each probe, exact ping argv, return code, bounded
stdout/stderr, transmitted/received/loss counts and observed reply TTLs. It records
probe command attempts separately from packet counts; an attempted command does
not prove packets went on the wire. A TTL is an observation, not a computed path.

| Status | Meaning |
|---|---|
| passed | Every requested direction returned all requested replies, with valid statistics and ping exit 0 |
| failed | At least one executed probe has valid statistics showing incomplete delivery |
| blocked | Endpoint prerequisite missing/down, duplicate endpoint IPv4, or an observed local/lo route that cannot test the remote host |
| unknown | An observation, command or statistics result is unavailable, ambiguous, malformed or timed out |

CLI exit status is 0 only for `passed`, otherwise 1. Invalid arguments and a lab
with pending configuration are refused before probing. Missing IP does not prove
a DHCP failure, and a present IP does not prove DHCP lease provenance. An absent
or rejected route-get result remains separate evidence: the command can still
attempt ping. An observed route does not guarantee packet delivery. Duplicate
addresses and observed local routes are blocked to avoid calling local echo
replies remote connectivity. Observations are sequential and can change between
reads; external namespace changes are outside the lab-lock guarantee.

This is an explicit pairwise ICMP check, not a lab-wide certificate of VLAN
isolation, OSPF convergence, DHCP/DNS/firewall correctness or application health.
Use the existing inspect/explain, actual daemon commands and captures for those
details. The privileged verification case uses DHCP endpoints in the seven-node
lab, correlates successful bidirectional counts/TTL with actual ICMP request/reply
PCAP, suppresses destination echo replies to prove route selection can coexist
with failed delivery, then checks a down interface and released DHCP address
block without launching ping. It also removes the destination default route
explicitly to verify a missing return path is reported as failed delivery, then
restores the gateway. Administrative link-down may remove next-hop routes;
raising the link alone does not restore all declarative configuration. Verification
observes this drift and does not repair it. After link/helper recovery and convergence, real
bidirectional verification succeeds again. Configuration/revision snapshots and
baseline host links/routes/rules/nft/forwarding remain unchanged by verification.


### Routed LAN services: DHCP, DNS and HTTP with OSPF and LLDP

`example --lan-services` composes the preceding profiles into eight real OCI
nodes. It reuses existing adapters and validation limits; no service is enabled
implicitly on other nodes.

| Node | Address / role |
|---|---|
| PC1 | VLAN10 DHCP reservation 192.0.2.100, gateway 192.0.2.1 |
| PC3 | VLAN30 DHCP reservation 198.51.100.100, gateway 198.51.100.1 |
| SW1 | L3 switch: both DHCP helpers, passive client SVIs, OSPF on VLAN20, physical LLDP |
| SW2 | VLAN20 L2 transit, trunk to SW1, access links to R1/DHCP1/DNS1, physical LLDP on infrastructure links |
| R1 | 198.18.0.2/29 and 203.0.113.1/24, broadcast OSPF transit and passive remote LAN, physical LLDP |
| PC2 | 203.0.113.10/24, gateway 203.0.113.1, explicit BusyBox HTTP startup recipe |
| DHCP1 | 198.18.0.3/29, two remote DHCP pools, explicit client-subnet return routes |
| DNS1 | 198.18.0.4/29, static local dnsmasq records and explicit return routes via SW1/R1 |

Both DHCP pools advertise DNS1 as option 6. The clients' actual `/etc/resolv.conf`
is installed by the existing DHCP hook; no static resolver competes with it.
DNS1 serves `web.lab.test` → 203.0.113.10 and `dns.lab.test` → 198.18.0.4, including
automatic reverse PTR records. These are explicit static records, not dynamic
DHCP registration. DNS has no host/upstream resolver inheritance or cache;
existing local-zone A/PTR/NODATA/NXDOMAIN behavior is retained. No external
Internet access, DNSSEC, recursive DNS or HTTPS service is added.

Use the BIRD/dnsmasq/lldpd rootfs from the physical LLDP composition above:

```bash
python3 -m network_labs.appliances example --lan-services \
  --rootfs "$HOME/network-labs-ospf-dhcp-lldp-rootfs" > lan-services.json
sudo python3 -m network_labs.appliances start lan-services.json
# Wait for both DHCP leases and OSPF convergence.
sudo python3 -m network_labs.appliances exec lan-services PC1 -- \
  /bin/cat /etc/resolv.conf
sudo python3 -m network_labs.appliances exec lan-services PC1 -- \
  /bin/busybox nslookup -type=A web.lab.test
sudo python3 -m network_labs.appliances exec lan-services PC1 -- \
  /bin/busybox wget -T 3 -q -O - http://web.lab.test/
sudo python3 -m network_labs.appliances exec lan-services PC3 -- \
  /bin/busybox wget -T 3 -q -O - http://web.lab.test/
sudo python3 -m network_labs.appliances verify lan-services PC1 PC2 --bidirectional
sudo python3 -m network_labs.appliances explain lan-services SW2
sudo python3 -m network_labs.appliances save lan-services
sudo python3 -m network_labs.appliances stop lan-services
sudo python3 -m network_labs.appliances restore lan-services
```

Successful HTTP returns `Network LABS routed HTTP`. HTTP crosses SW1 and R1;
client DNS reaches DNS1 through SW1 and the transit VLAN. DNS1 has explicit
return routes to both client subnets through SW1 and the remote PC2 subnet
through R1. Startup readiness remains separate from DHCP/OSPF convergence.

PC2's explicit startup argv creates a sample page and starts BusyBox httpd in
its own container. Restore replays this recipe, rebuilding the sample page.
Arbitrary HTTP filesystem changes, process state, caches and connections are not
snapshotted or audited as a managed web-server policy. This is a bounded HTTP
application test, not a complete server OS or vendor web GUI.

The privileged composition case observes both acquired addresses and resolver
files, UDP/TCP A/PTR/NODATA/NXDOMAIN responses from both client VLANs and PC2,
name-based HTTP from PC1/PC3, physical LLDP and bidirectional real ICMP. A client
PCAP contains actual DNS traffic, HTTP request/response and the sample payload.
It separately stops DNS, stops HTTP and removes R1 OSPF: routing/ICMP can still
work with DNS unavailable; DNS and ICMP can work with HTTP unavailable; transit
DNS can still answer while the remote OSPF route and HTTP delivery are absent.
Services/routing are restored and retested before save/stop/restore, which must
reacquire leases and restore name-based HTTP. Host links/routes/rules/nft/forwarding
remain checked after cleanup. No lossless recovery or whole-application resource
budget is inferred from these checks.

### Explicit DNS, TCP and HTTP service probes

`probe` sends real, bounded traffic from a running single-NIC OCI host. It reads
its observed IPv4 and guest `/etc/resolv.conf`, then reports each executed stage.
The host Python standard library runs in the owned node network namespace; no
Python installation in the guest is needed. It binds sockets to the observed
source IPv4. It does not change configuration or use the host DNS resolver.

```bash
sudo python3 -m network_labs.appliances probe lan-services PC1 web.lab.test
sudo python3 -m network_labs.appliances probe lan-services PC3 web.lab.test --json
sudo python3 -m network_labs.appliances probe lan-services PC1 web.lab.test --protocol dns
sudo python3 -m network_labs.appliances probe lan-services PC1 203.0.113.10 --protocol tcp --port 80
sudo python3 -m network_labs.appliances probe lan-services PC1 web.lab.test --path /missing-page
```

Default HTTP probing performs DNS when needed, TCP connect, then a separate HTTP
HEAD connection. Only HTTP 2xx passes; 3xx/4xx/5xx retain their actual status and
fail the requested check. Redirects are not followed, response bodies are not
validated, and TLS is not supported. TCP success proves connection establishment,
not application correctness. A later HTTP failure can occur after TCP success.

DNS support deliberately covers a direct IPv4 A query over UDP to exactly one
IPv4 nameserver read from the guest. No search domains, CNAME chain following,
multiple-server fallback, TCP retry, recursion implementation or host resolver
fallback. NXDOMAIN and an empty direct A answer fail the requested resolution;
malformed/truncated replies remain unknown. Multiple A addresses block subsequent
TCP/HTTP selection. Literal IPv4 targets bypass DNS. Local/loopback targets are
rejected for transport checks. Source endpoints require one observed usable IPv4
on physical eth0, and a running lab without pending configuration.

`--timeout 1..5` (default 3) bounds each wire stage; the parent also bounds worker
execution. HTTP reads at most 4096 bytes while finding the status line. Total time
also includes bounded endpoint, resolver and route observations. Stages stop at
the first failure or unavailable result. JSON and French output distinguish
`passed`, `failed`, `unknown` and `blocked`; exit 0 means the requested probe passed,
otherwise exit 1. Kernel route evidence is reported separately from delivery.
No failure alone proves whether routing, filtering, a stopped service or the
return path caused it. Probes update normal network counters and connection state.

The routed-services native test exercises successful probes from both DHCP VLANs,
NXDOMAIN, HTTP 404, stopped DNS with working literal-IP HTTP, stopped HTTP with
working DNS, route withdrawal, and recovery/save/restore. Unit tests additionally
exercise malformed DNS packets, resolver ambiguity, actual loopback TCP/HTTP
responses and non-followed redirects.

If a command reports **aucun état actif trouvé**, start the lab from its manifest
before running `probe`, `verify`, `inspect` or `status`. The manifest's `name`
must match the lab name used by those commands. If a saved startup file exists,
the error also prints the corresponding `restore` command. Neither action is
performed automatically. `/run` is transient, so saved declarations and active
runtime state are different. An existing lab directory with a missing state file
is reported as incomplete state, not a safe invitation to overwrite resources.

Service probes also expose structured `findings` with stable codes, status,
French explanation, suggested checks and the original stage evidence. Human
output explains DNS NXDOMAIN/no-direct-A/errors, TCP refusal versus other failed
connections, and actual HTTP statuses. Suggestions never change configuration
and never turn a timeout or refusal into a proven firewall/routing/daemon cause.
HTTP HEAD rejection is distinguished from GET availability; previous successful
DNS/TCP stages remain visible when HTTP fails. Raw evidence remains in `--json`.

### Read-only IOS-style show commands

Five complete command spellings are available through the native CLI:

```bash
sudo python3 -m network_labs.appliances show lan-services PC1 --text 'show ip interface brief'
sudo python3 -m network_labs.appliances show lan-services SW1 --text 'show ip route'
sudo python3 -m network_labs.appliances show lan-services SW1 --text 'show arp'
sudo python3 -m network_labs.appliances show lan-services SW1 --text 'show vlan brief'
sudo python3 -m network_labs.appliances show lan-services SW1 --text 'show mac address-table' --json
```

This is a partial command adapter over actual Linux kernel observations, not
Cisco firmware or a complete vendor CLI. Interface names remain Linux names.
The address summary reads all links so unaddressed ports are retained, and shows
only their observed IPv4 addresses. Routes cover the IPv4 main table, with raw
kernel protocol labels; other policy tables and advanced route details require
other diagnostics or the raw JSON. ARP includes unresolved neighbor states.
VLAN output is bridge membership, including trunks and bridge-self entries,
not a vendor VLAN database. FDB output includes local/permanent entries instead
of pretending all rows are learned dynamic MACs. Bridge commands require a Linux
switch; OVS and VM guest adapters are not provided here.

Every kernel read and container-state read has a three-second timeout. No packet
probes or configuration changes occur. Empty observed tables differ from unknown
or failed reads; unavailable fields display `?`. JSON preserves kernel records,
command argv, timestamps and revision. Exit 0 means the observation was obtained,
not that connectivity is healthy. Unknown commands, multiple commands, shell
syntax and pending configurations are rejected before observation. The native
routed-services test checks the actual DHCP address, learned route, bridge tables
and unchanged state; unit tests cover invalid commands and missing evidence.

FDB port rendering uses iproute2's `ifname` field (with an explicitly observed
`dev` fallback), rather than assuming the neighbor-table JSON schema. A literal
empty FDB `state` is displayed as `reachable`, matching iproute2's state encoder;
a missing state remains `?`. Raw JSON is untouched. Flags are shown as readable
lists (`-` for an observed empty list). Missing VLANs remain unspecified.

```bash
sudo python3 -m network_labs.appliances show lan-services SW1 --text 'show mac address-table vlan 10'
sudo python3 -m network_labs.appliances show lan-services SW1 --text 'show mac address-table interface eth0'
```

These optional single filters select observed rows from the same complete br0
snapshot, not from the manifest's VLAN/MAC declarations. JSON retains both the
full `observation.records` and filtered `display_records`, with a count of
unselected rows. Unknown/missing fields do not match a filter. Empty selection
is not presented as an empty kernel table or a connectivity verdict. Interface
filters accept a declared physical switch port or br0; VLAN filters accept
1..4094. Combined filters and dynamic/static vendor classification are not added.

Schema reference: [iproute2 bridge/fdb.c](https://kernel.googlesource.com/pub/scm/network/iproute2/iproute2-next/+/f46186fd0332640cb09f719627e5e14d38d54472/bridge/fdb.c).

### OSPF show commands

Nodes with a declared OSPF process also support these read-only aliases:

```bash
sudo python3 -m network_labs.appliances show lan-services SW1 --text 'show ip ospf neighbor'
sudo python3 -m network_labs.appliances show lan-services SW1 --text 'show ip ospf interface'
sudo python3 -m network_labs.appliances show lan-services R1 --text 'show ip ospf'
sudo python3 -m network_labs.appliances show lan-services SW1 --text 'show ip route ospf'
```

The aliases call the existing BIRD control adapter with fixed commands and its
read-only flag, three-second timeout, 64 KiB output bound and daemon-error checks.
Output is explicitly labeled BIRD, retains its native columns/control codes, and
escapes terminal control characters in human text; JSON preserves the actual
text and command. Missing, empty, failed or oversized daemon output stays unknown.
Nodes without declared OSPF reject these queries before executing a command.
No neighbor, DR/BDR or convergence state is synthesized from topology. OSPF routes
here are the BIRD protocol RIB; use `show ip route` for the Linux main table and
`verify`/`probe` for delivery. This adds no configuration syntax or protocols.

Malformed VLAN entries now render unknown fields rather than disappearing into
an apparently empty kernel table. Raw observations remain available in JSON.

### LLDP show commands

```bash
sudo python3 -m network_labs.appliances show lan-services SW2 --text 'show lldp neighbors'
sudo python3 -m network_labs.appliances show lan-services SW2 --text 'show lldp neighbors detail' --json
```

Both commands read one actual lldpcli JSON0 neighbor snapshot using the existing
bounded adapter and normalizer. They retain received port/chassis identifier
subtypes, repeated ports, optional system names and advertised TTL (not remaining
lifetime). The detailed view adds chassis identity, the raw lldpd age label and
incomplete-field names. Advertised text is escaped in human output; JSON keeps
raw evidence and normalized records. No manifest link or inventory name is used
to invent a peer. A missing advertised name falls back only to its chassis ID.

An observed empty table is distinct from unavailable or malformed output. Partial
observations retain usable rows with a warning and exit 1; only fully observed
output exits 0. None of these results certifies connectivity or authenticates
advertised identities. Nodes without declared LLDP reject the query. The LLDP
pipeline now enables pipefail so a failed lldpcli cannot be hidden by a successful
output-limiting command. No daemon restart or configuration change is performed.

### Classic STP show command

```bash
sudo python3 -m network_labs.appliances show stp-lan SW3 --text 'show spanning-tree'
```

For a running Linux switch, this command reads actual detailed netlink links and
kernel sysfs bridge/root IDs (each read bounded to three seconds). It displays
the observed common-tree protocol, bridge/root identifiers, root port and path
cost, topology-change flag, per-port state/cost/priority and guard flags. OVS,
router/host endpoints and vendor per-VLAN spanning trees are outside this adapter.
Missing bridge/controller evidence is unknown; missing port state is partial.
Raw reads and normalized tree remain available with --json. Observations are
sequential, not atomic. No topology tree is computed, no BPDUs are sent by the
command, and local settled state does not certify global convergence or delivery.
The existing native STP triangle test checks initial blocking/root identity,
actual failover to the alternate root port and unchanged configuration.
