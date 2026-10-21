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
  de routes statiques CLI ni de pools DHCP en syntaxe IOS dans ce jalon. Les SVI Linux sont décrites plus bas.
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
Pas de DHCP relay, DHCPv6 ou serveur DNS fourni automatiquement. Les réservations explicites MAC/IP sont décrites plus bas.

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

Un node OCI numéroté hors switch peut déclarer jusqu'à 128 routes IPv4 :

```json
"routes": [
  {"destination": "10.10.10.0/24", "gateway": "172.31.255.2", "interface": "eth0"},
  {"destination": "10.20.20.0/24", "gateway": "172.31.255.2", "interface": "eth0"}
]
```

La passerelle doit être un voisin utilisable sur l'interface indiquée. Les
préfixes sont uniques, sans remplacement d'un réseau directement connecté.
La route par défaut reste le champ `gateway`. Les routes sont appliquées au
kernel et vérifiées avant `save`/`export`, puis recréées par `restore`. Ce jalon
ne fournit pas encore `ip route` dans l'adaptateur IOS partiel. Les commandes
brutes `exec ... ip route` restent possibles, mais ne modifient pas le manifest.

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
switch access, intervalle 1–60 s et hold 2–10. Les ports sont explicitement
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
