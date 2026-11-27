# Conteneurs (OCI) et ligne de commande

> Le moteur à conteneurs OCI (crun, namespaces Linux) reste disponible tel quel pendant la release 1 : il est gelé, les
> nouvelles fonctions visent les micro-VM ([RELEASE_1.md](RELEASE_1.md)). Ces notes, reprises du README, décrivent ses
> scénarios en ligne de commande (`python3 -m network_labs.appliances` ou `network-labs-lab`) et leurs limites ; les
> premières lignes datent de l’atelier d’avant les micro-VM.

## L’atelier avec des conteneurs


[État actuel du projet](STATUS.md), [estimation historique](PROJECT_STATUS.md)
et [couverture exacte des profils LAN natifs](LAN_PROTOCOL_COVERAGE.md).
Les estimations de progression ne sont pas des pourcentages de couverture des tests.

`python3 -m network_labs` ouvre l'atelier dans la fenêtre principale : équipements à gauche,
topologie au centre et inspecteur à droite, selon la disposition existante.
Création de postes/switches/routeurs OCI, câblage par ports libres ou nouveaux,
suppression et déplacement sont disponibles pour le brouillon. Enregistrer puis
arrêter/redémarrer applique la topologie ; les positions restent en session. Le projet initial est maintenant un
campus natif de dix nodes (VLAN 10/20/30, routeur, deux switches, firewall bloquant
par défaut et serveur endpoint). **Fichier → Campus entreprise** crée une copie
avec votre rootfs ; **Nouveau LAN** conserve le petit exemple. La bibliothèque
occupe toute la hauteur et le panneau GUI affiche ports/adresses/détails.
L’onglet Configuration du panneau équipement permet le nom, IPv4/passerelle et
l’état d’un port OCI ; les modifications sont validées avant application au brouillon. La bibliothèque
est illustrée et classée ; le canevas affiche les groupes VLAN déclarés et
les ports/trunks. Les résultats de ping sont lisibles dans un panneau de
diagnostic en lecture seule, avec JSON séparé.
La GUI utilise Inter (licence SIL OFL incluse), des contrôles arrondis et un
canevas interactif : molette pour zoomer, bouton central ou Maj+glisser pour
déplacer la vue, double-clic sur un équipement pour ouvrir sa configuration.
Les boutons − / + / Centrer règlent aussi la vue sans modifier le manifest.
Le menu **Fichier → LAN sécurité access** crée un profil adapté aux protections
snooping/DAI/source guard ; le profil actuel exige des ports physiques access.
Démarrage/état/inspection, test ICMP réel et arrêt sont disponibles ; JSON,
dépendances et plan mémoire restent accessibles par onglets. Le bouton de
retour restaure le projet pédagogique. Le laboratoire natif garde son propre
état : il ne convertit pas automatiquement les modèles constructeur ni leurs
configurations. Voir la [capture réelle et les limites GUI](NATIVE_GUI_FLOW.md).

Le nouveau gestionnaire peut démarrer des **containers OCI/crun persistants**,
relier leurs namespaces par veth et lancer des **microVMs Firecracker** optionnelles
sur le même fabric via TAP. Rootfs, kernel et disque sont fournis explicitement.
Les commandes OCI sont exécutées dans le node réel. Le démarrage/arrêt nécessite
sudo dans un terminal ; conserver la GUI sans privilèges. Libkrun, Unikraft,
Hyperlight/Nanvix, WASI 0.3 et netkit sont identifiés comme pistes non intégrées.

```bash
python3 -m network_labs.appliances doctor
```

[Guide d'installation, premier ping réel, limites et validation](HYBRID_APPLIANCES.md).

### Premier moteur LAN autonome

Le scénario natif `example --campus` crée **8 nodes** avec VLAN access/trunk,
sous-interfaces 802.1Q, routage inter-VLAN et DHCP BusyBox réel. Une CLI partielle
`ios-basic` applique les blocs supportés sur les namespaces Linux ; `inspect`
lit les interfaces/routes/VLAN du kernel. `save` conserve un manifest startup
durable et `restore` recrée le lab après arrêt. Ce moteur ne dépend pas de Tk.

```bash
python3 -m network_labs.appliances example --campus --rootfs "$HOME/network-labs-rootfs" > campus-lan.json
python3 -m network_labs.appliances plan campus-lan.json
```

[Lancement, commandes couvertes, sauvegarde et critères de validation](NATIVE_LAN_CORE.md).
Le backend Linux propose aussi un firewall IPv4 stateful et masquerade/SNAT/DNAT
(`example --firewall`), avec règles, compteurs, sessions et sauvegarde.
Le filtre IPv4 `example --ip-source-guard` ajoute la validation réelle IP ou
IP+MAC par port access, basée sur DHCP snooping/bindings statiques, avec DAI
optionnel et autorisations dynamiques courtes. Voir le guide LAN pour ses limites.
Le scénario `example --multicast` ajoute IGMPv2 snooping/querier Linux sur un
VLAN access, une MDB réelle et des probes UDP bornées via la commande `multicast`.
`example --dhcp-reservations` ajoute un client PRN1 avec IP réservée par MAC,
deux clients dynamiques et des ACKs observables via DHCP snooping.
`example --dns` ajoute DNS local dnsmasq réel (UDP/TCP, A/PTR), resolver DHCP ou
statique et HTTP par nom ; préparer un nouveau rootfs avec `rootfs --dnsmasq`.
Voir la section DNS du guide LAN pour les commandes et limites.
`example --lldp` ajoute la découverte réelle des voisins avec lldpd/lldpcli,
inspection et capture LLDP ; son rootfs optionnel se prépare avec `--lldpd` et `--lldpcli`.
`example --svi` ajoute un switch L3 Linux avec gateways sur VLAN 10/20, trunk,
configuration SVI et activation explicite de `ip routing`, sans nouveau daemon.
`example --static-routing` ajoute un LAN avec switch L3 et routeur : configurer
les routes aller/retour avec `ip route`/`no ip route`, y compris default route et /32.
`route LAB NODE IPv4` lit la décision réelle du kernel, l’entrée FIB et le voisinage,
sans paquet de test ; `--source`/`--ingress` précisent le contexte du lookup.
`inspect`/`explain` exposent aussi rp_filter et forwarding par interface,
avec les valeurs effectives lisibles en texte. `route` fournit des findings
structurés et des vérifications suggérées selon les flags et états NUD observés.
Le scénario `example --enterprise` intègre 20 nodes (12 PC, 4 switches,
routeur, firewall, DHCP et WAN). `benchmark` mesure le repos et une charge ICMP
parallèle puis nettoie le lab. Le scénario `example --lacp` ajoute un trunk VLAN sur deux liens agrégés par LACP Linux,
avec inspection de négociation et seuil min-links. `example --stp` ajoute une boucle contrôlée par le STP commun 802.1D du kernel, avec protections BPDU Guard/Root Guard optionnelles.
`explain LAB [NODE]` ajoute un diagnostic passif lisible en français, ou structuré avec `--json`, fondé sur les états réels du kernel.
`capture LAB NODE INTERFACE --output trace.pcap` enregistre les vraies trames du node avec durée/paquets/taille bornés et filtres BPF (tcpdump/nsenter/timeout optionnels).
`explain LAB` compare aussi les memberships VLAN observés entre switches (LACP regroupé), et affiche les compteurs RX/TX/errors/drops cumulés sans conclure à la livraison des paquets.
Le budget total 2 Gio reste à valider. `example --rstp` utilise un backend
Open vSwitch optionnel dans les containers (rootfs `--openvswitch`, module
`openvswitch` préchargé), avec ports access et RSTP réel. Voir le guide LAN.


## Scénarios en ligne de commande

La commande native `monitor LAB NODE [INTERFACE] --seconds 5 [--json]` mesure
passivement les différences RX/TX et les débits moyens par port sur deux relevés.
Les changements d'identité et diminutions de compteurs détectés rendent les taux
indisponibles ; aucun test de livraison n'est implicite.
Voir [le guide LAN](NATIVE_LAN_CORE.md#débits-passifs-sur-un-intervalle).

Le scénario natif `example --port-security` ajoute l'admission de MAC source
statiques sur ports access OCI, avec filtrage nftables réel, compteurs,
configuration IOS partielle et save/restore des MAC déclarées. Dynamic/sticky
learning et shutdown automatique ne sont pas implémentés.
Voir [le guide de port security](NATIVE_LAN_CORE.md#port-security-statique-sur-ports-access).

Le scénario natif `example --dhcp-snooping` démarre un vrai client, un serveur
trusted et un serveur rogue. Il ajoute filtrage DHCPv4 sur ports access et
bindings volatiles issus des échanges REQUEST/ACK, avec worker supervisé,
compteurs et save/restore de la politique. Trunks/LACP et relay/Option 82
restent hors périmètre ; inspection ARP disponible séparément. Voir [le guide DHCP snooping](NATIVE_LAN_CORE.md#dhcp-snooping-ipv4--confiance-et-bindings-observés).

Le scénario natif `example --arp-inspection` ajoute la validation ARP réelle :
MAC Ethernet + MAC/IP ARP + port/VLAN, depuis bindings statiques explicites ou
permissions DHCP à timeout kernel court. Les permissions dynamiques expirent
sans worker ; les paquets IPv4 de données ne sont pas filtrés par cette option.
Voir [le guide ARP](NATIVE_LAN_CORE.md#inspection-arp-dynamique-sur-ports-access).

Native DHCPv4 relay: `example --dhcp-relay` connects a client VLAN to a remote single-pool DHCP server through a real dnsmasq relay. Setup and limits: [Native LAN core](NATIVE_LAN_CORE.md#dhcpv4-relay-remote-single-pool-server).

Native multi-VLAN DHCP: `example --dhcp-multi` uses per-VLAN helpers and a central dnsmasq server with disjoint remote pools; see the native LAN guide for limits and setup.

Native dynamic routing: `example --ospf` runs real BIRD 2 OSPFv2 in an area-zero three-router topology with a higher-cost backup path. `example --ospf-cli` starts the numbered topology without OSPF daemons; create/remove its processes through the partial IOS adapter. `example --ospf-broadcast` adds four routers on a shared Ethernet LAN with observed DR/BDR/DROther roles and normal 2-Way neighbors. `example --ospf-svi` connects a real Linux L3-switch VLAN interface to a router over a tagged VLAN trunk, with passive client-LAN advertisements. `example --ospf-dhcp` adds a co-located DHCP relay and remote pool, with independent OSPF/helper transactions and recovery. `example --ospf-dhcp-multi` adds two independent client VLANs/pools, learned return routes and scoped recovery that preserves services on other nodes. Per-interface Hello/Dead CLI timers drive actual BIRD adjacency expiry and recovery. See the native LAN guide for image setup, commands and the bounded supported profile.

Native connectivity verification: `verify LAB PC1 PC2 --bidirectional --json` reads actual endpoint addresses (including DHCP) and executes bounded real ICMP with kernel route evidence and passed/failed/blocked/unknown results. It does not certify all protocols; passive `explain` and `route` remain available. See `docs/NATIVE_LAN_CORE.md`.

Native infrastructure discovery: `example --ospf-dhcp-lldp` adds actual physical-port LLDP to the seven-node OSPF/two-VLAN DHCP lab, including its trunk. Discovery remains separate from routing adjacency and delivery. See [setup and limits](NATIVE_LAN_CORE.md#physical-lldp-alongside-ospf-and-dhcp).

Readable LLDP diagnostics: `explain LAB NODE` prints actual received local/remote identifiers and advertised TTL; `inspect` retains raw JSON0 plus a normalized summary. Empty, partial and unknown reads remain distinct. See [the guide](NATIVE_LAN_CORE.md#readable-received-lldp-neighbors).

Routed application scenario: `example --lan-services` composes eight OCI nodes with two DHCP client VLANs, DHCP-supplied DNS, local UDP/TCP DNS, name-based HTTP across OSPF and physical LLDP. See [setup and service/failure boundaries](NATIVE_LAN_CORE.md#routed-lan-services-dhcp-dns-and-http-with-ospf-and-lldp).

Native service diagnostics: `python3 -m network_labs.appliances probe lan-services PC1 web.lab.test`
reports separate real DNS A, TCP connection and HTTP HEAD results. See
[bounded service probe scope](NATIVE_LAN_CORE.md#explicit-dns-tcp-and-http-service-probes).

Static IPv6 LAN foundation: `example --ipv6-vlan --rootfs PATH` creates an isolated
six-node VLAN10/20 lab with real IPv6/NDP. This initial profile covers static /64
hosts and L2 switching only; see [IPv6 scope and commands](NATIVE_LAN_CORE.md#static-ipv6-on-an-isolated-l2-vlan-lan).

`example --ipv6-routed --rootfs PATH` adds two internal IPv6 LANs with actual
physical routers, explicit static/default routes and forwarding/route drift
checks. [Scope and commands](NATIVE_LAN_CORE.md#static-ipv6-routing-between-internal-lans).

`example --slaac --rootfs PATH` uses real RA-only dnsmasq and kernel SLAAC for
IPv6 host addressing/default-router discovery, with routed internal-LAN traffic.
A dnsmasq rootfs is required. [Scope and commands](NATIVE_LAN_CORE.md#slaac-and-real-router-advertisements).

`example --dhcpv6 --rootfs PATH` adds a real stateful BusyBox DHCPv6 client and
managed dnsmasq pool, with RA gateway discovery and finite lease expiry. See
[DHCPv6 scope and commands](NATIVE_LAN_CORE.md#stateful-dhcpv6-on-an-internal-lan).

`verify LAB PC1 PC2 --family ipv6 --bidirectional` now checks actual static,
SLAAC or DHCPv6 endpoint addresses, DAD readiness and real ICMPv6 delivery with
source-aware kernel route evidence. See [IPv6 verification](NATIVE_LAN_CORE.md#explicit-ipv6-connectivity-verification).

`example --dual-stack --rootfs PATH` runs static IPv4 and IPv6 on the same
four-node routed LAN, with independent forwarding/routes and per-family real
verification. See [dual-stack scope and commands](NATIVE_LAN_CORE.md#static-dual-stack-routing-on-internal-lans).

`example --management` adds real Dropbear SSH (public-key Linux shell),
authenticated BusyBox Telnet and remote UDP Syslog sending on an internal LAN.
Build an optional `--dropbear` rootfs and provide public keys/password hashes;
see [management commands and limits](NATIVE_LAN_CORE.md#ssh-telnet-and-remote-udp-syslog)
and [LAN protocol coverage](LAN_PROTOCOL_COVERAGE.md) for remaining protocols.

`example --syslog` adds a real node-local rsyslog UDP collector with an explicit sender allowlist and rotating volatile logs. See [collector setup and tests](NATIVE_LAN_CORE.md#node-local-udp-syslog-collector).

`example --snmp` adds a real read-only SNMPv2c agent with source/community access policy and node-local IF-MIB telemetry. See [SNMP setup and polling](NATIVE_LAN_CORE.md#read-only-snmpv2c-on-a-native-node).

`example --snmpv3` adds a separate read-only USM SHA-256/AES authPriv agent with protected master-key configuration and a fresh runtime engine identity. See [SNMPv3 setup and polling](NATIVE_LAN_CORE.md#read-only-snmpv3-with-usm-authpriv).

`example --snmp-notifications` adds actual agent coldStart traps/informs and a node-local log-only receiver, with distinct packet, ACK and log evidence. See [notification setup and loss tests](NATIVE_LAN_CORE.md#snmp-notifications-traps-informs-and-a-node-local-receiver).

`example --snmpv3-informs` adds a USM-only log receiver and real SHA-256/AES authPriv informs, with receiver discovery and fresh engine identities. See [encrypted inform setup](NATIVE_LAN_CORE.md#snmpv3-authpriv-informs).

`example --snmpv3-traps` adds two real authPriv trap agents with fresh sender-engine bindings and a log receiver that retires rotated identities. See [managed sender-engine traps](NATIVE_LAN_CORE.md#snmpv3-authpriv-traps-with-managed-sender-engines).
