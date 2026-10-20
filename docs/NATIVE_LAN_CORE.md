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
- STP/RSTP, LACP, firewall/NAT, DNS et les autres constructeurs restent à porter.
  Les boucles entre switches sont encore refusées ; ne pas les activer par commandes brutes.

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
The 2 GiB target has not been measured for a 20-node topology yet.

Primary references: [nftables manual](https://netfilter.org/projects/nftables/manpage.html),
[atomic replacement](https://wiki.nftables.org/wiki-nftables/index.php/Atomic_rule_replacement),
[NAT semantics](https://wiki.nftables.org/wiki-nftables/index.php/Performing_Network_Address_Translation_(NAT)),
[conntrack](https://www.netfilter.org/projects/conntrack-tools/conntrack-manpage.html).
