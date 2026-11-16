# Modèles et marques ajoutés

Les profils suivants sont créables. Les quantités de ports ci-dessous sont
implémentées : un port occupé ne peut pas recevoir un deuxième câble, et un
switch complet refuse une liaison supplémentaire. La sauvegarde conserve le
profil et les ports. Les noms `gi0/x`, `gi1/x` sont ceux du simulateur ; ils ne
prétendent pas reproduire la nomenclature native de chaque constructeur.

| Profil texte | Marque / modèle | Interfaces du profil |
| --- | --- | --- |
| `tplink-sg108e` | TP-Link TL-SG108E | 8 Ethernet |
| `netgear-gs108e` | NETGEAR GS108Ev3 | 8 Ethernet |
| `aruba-1930-24` | HPE Aruba Instant On 1930 JL682A | 24 Ethernet + 4 uplinks |
| `unifi-lite8` | Ubiquiti UniFi USW-Lite-8-PoE | 8 Ethernet ; alimentation PoE non simulée |
| `mikrotik-crs326` | MikroTik CRS326-24G-2S+RM | 24 Ethernet + 2 uplinks |
| `dlink-dgs1210` | D-Link DGS-1210-28 | 24 Ethernet + 4 interfaces combo abstraites |
| `qnap-ts264` | QNAP TS-264 | Un adaptateur LAN abstrait ; port SMB/445 simulé |
| `brother-hl5200` | Brother HL-L5200DW | Un adaptateur LAN ; port RAW/9100 simulé, sans radio |
| `dell-poweredge` | Dell PowerEdge, profil serveur de gamme | Un adaptateur LAN, sous-ensemble CLI Linux |
| `hpe-proliant` | HPE ProLiant, profil serveur de gamme | Un adaptateur LAN, sous-ensemble CLI Linux |
| `lenovo-thinksystem` | Lenovo ThinkSystem, profil serveur de gamme | Un adaptateur LAN, sous-ensemble CLI Linux |

Les profils serveurs de gamme ne représentent pas un SKU matériel précis.
Ces ajouts complètent les profils Cisco, Windows/Linux, HP, Synology, Axis,
Yealink et les identités firewall existantes. Le catalogue est filtrable par
rôle, marque et modèle, et reste non exhaustif.

## Portée commune

Les nouveaux switches partagent le moteur L2 éducatif et le gestionnaire web
local. Leur interface est présentée selon leur famille. Les consoles de marque
non implémentées sont annoncées indisponibles. MikroTik possède un sous-ensemble
RouterOS identité/interfaces ; les réglages bridge/VLAN RouterOS ne sont pas
implémentés. Voir [FIDELITY.md](FIDELITY.md). Le modèle de ports n'est pas un
inventaire exact des fonctionnalités réelles : le moteur partagé peut exposer
des options que le produit réel ne fournit pas. Pas de firmware, débit mesuré,
transceiver physique, PoE, ASIC ou système constructeur.

Les endpoints partagent un modèle IPv4 mono-interface et des services de ports.
Le NAS réel peut avoir plusieurs interfaces, mais cette version du simulateur
n'émule pas encore le multi-homing ou l'agrégation des endpoints. Aucun système
de fichiers, NAS/DSM/QTS, impression ou application serveur réel n'est exécuté.

## Références de disposition des ports

- [TP-Link TL-SG108E](https://www.tp-link.com/us/business-networking/soho-switch-easy-smart/tl-sg108e/)
- [NETGEAR GS108Ev3](https://kb.netgear.com/25093/GS108Ev3-FAQs)
- [Aruba Instant On 1930](https://www.arubainstanton.com/files/DS_AIO_1930SwitchSeries_fr.pdf)
- [UniFi Lite 8 PoE](https://techspecs.ui.com/unifi/wifi/usw-lite-8-poe)
- [MikroTik CRS326](https://mikrotik.com/product/CRS326-24G-2SplusRM)
- [D-Link DGS-1210-28](https://www.dlink.com/us/en/products/dgs-1210-28-28-port-gigabit-smart-managed-switch)
- [QNAP TS-264](https://www.qnap.com/en/product/ts-264)
- [Brother HL-L5200DW](https://support.brother.com/g/b/spec.aspx?c=eu_ot+&lang=en+&prod=hll5200dw_us_eu_as)
