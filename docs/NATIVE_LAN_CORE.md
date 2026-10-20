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
- Pas de `allowed vlan add/remove/except`, de `encapsulation ... native`, de SVI,
  de routes statiques CLI ni de pools DHCP en syntaxe IOS dans ce jalon.
- DHCP se configure dans le manifest. Le live adapter refuse les nodes qui
  portent eux-mêmes un service/client DHCP ; il ne prétend pas reconfigurer ce daemon.
- Le bridge Linux ne reproduit pas tous les détails d'acceptation des trames d'un
  ASIC Cisco. L'encodage d'une commande n'est pas une preuve de conformité matérielle.
- RSTP, DNS et les autres constructeurs restent à porter. LACP et STP classique Linux sont décrits plus bas. Le firewall/NAT
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
Pas de DHCP relay, DHCPv6, réservations ou serveur DNS fourni automatiquement.

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
**RSTP reste non implémenté**.

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

### Pourquoi RSTP n'est pas annoncé comme fonctionnel

Le bridge Linux historique implémente STP classique. Un daemon tel que `mstpd`
implémente RSTP, mais requiert un bridge en mode **userspace STP**, différent
`stp_state=2` du `stp_state=1` kernel. Le mécanisme traditionnel `/sbin/bridge-stp`
n'est appelé que dans le namespace réseau initial ; un simple `stp_state 1`
dans nos namespaces peut donc rester en STP classique malgré la présence de mstpd.
Les kernels récents proposent `IFLA_BR_STP_MODE=user` pour cette situation.
Il reste à valider ce support dans les couples kernel/iproute2 ciblés, puis la
supervision isolée de mstpd, sa défaillance, la mesure de ressources et de vrais
tests de BPDUs/reconvergence RSTP. Le manifest refuse `mode: rstp` explicitement,
sans fallback silencieux, sans mise à niveau automatique du kernel de l'utilisateur.

Références primaires : [bridge Linux](https://docs.kernel.org/networking/bridge.html),
[encodage des priorités de port](https://github.com/torvalds/linux/blob/master/net/bridge/br_stp_if.c),
[mstpd : utilisation avec VLANs](https://github.com/mstpd/mstpd/blob/master/README.VLANs.md),
[mstpctl](https://github.com/mstpd/mstpd/blob/master/utils/mstpctl.8).
