# Micro-nodes natifs : environnement hybride expérimental

Le logiciel dispose désormais d'un gestionnaire natif indépendant du moteur
pédagogique et du réseau Wasm. Un manifest décrit chaque node, son runtime, ses
interfaces, ses commandes de démarrage et son budget mémoire. Les nodes restent
actifs entre les commandes/tests jusqu'à l'arrêt explicite du lab.

## Ce qui est implémenté

| Élément | État et périmètre |
| --- | --- |
| OCI / crun | Adaptateur expérimental : start, exec, status, stop ; namespaces réseau/PID/mount/UTS/IPC/cgroup ; overlay privé par node ; limites mémoire/CPU/processus |
| Fabric Linux | Namespaces et câbles veth ; bridge Linux non tagué pour le rôle switch ; TAP et bridge intermédiaire pour Firecracker |
| Firecracker | Adaptateur expérimental : lancement avec kernel/disque locaux, disque copié par node, une NIC Ethernet, console fichier, suivi du VMM et arrêt |
| GUI | Menu Fichier et `--native-lab` : diagnostic, édition JSON, plan, boutons start/status/stop dans un terminal avec sudo |
| Wasm | Backend existant conservé ; réseau distinct, pas de pont Wasm ↔ fabric natif |
| Libkrun, Unikraft, Hyperlight/Nanvix | Recherche ; aucun adaptateur exécutable ou téléchargement automatique |
| WASI 0.3, netkit/eBPF | Recherche ; l'ABI Wasm existante et le fabric veth ne les utilisent pas |

La présence d'un exécutable ou l'accès à `/dev/kvm` ne prouve pas un démarrage
réussi. `doctor` distingue détection et implémentation. Le statut Firecracker
indique seulement que le VMM est vivant, jamais que le guest est prêt.

## Premier LAN OCI sur Ubuntu

Depuis **le dossier du dépôt** (celui qui contient `network_labs/`) :

```bash
sudo apt update
sudo apt install -y python3 python3-tk crun iproute2 busybox-static
python3 -m network_labs.appliances doctor

# Construction locale, sans téléchargement d'image ; destination nouvelle.
python3 -m network_labs.appliances rootfs \
  --busybox /usr/bin/busybox --output "$HOME/network-labs-rootfs"

# PC1 — SW1 — PC2, adresses 192.0.2.10 et 192.0.2.20.
python3 -m network_labs.appliances example \
  --rootfs "$HOME/network-labs-rootfs" > native-lan.json
python3 -m network_labs.appliances plan native-lan.json
sudo python3 -m network_labs.appliances start native-lan.json
sudo python3 -m network_labs.appliances exec micro-lan PC1 -- /bin/ip addr
sudo python3 -m network_labs.appliances exec micro-lan PC1 -- /bin/ping -c 3 192.0.2.20
sudo python3 -m network_labs.appliances exec --tty micro-lan PC1 -- /bin/sh
# exit pour sortir du shell du node, puis :
sudo python3 -m network_labs.appliances status micro-lan
sudo python3 -m network_labs.appliances stop micro-lan
```

Le rootfs BusyBox contient uniquement des outils minimaux. Il ne contient ni
FRR, ni nftables, ni Open vSwitch, ni firmware constructeur. Un rootfs complet
compatible peut être fourni pour ces programmes ; leur présence et leurs
configurations restent nécessaires. Utiliser uniquement des assets de confiance.
Le builder refuse les ELF dynamiquement liés et ne les exécute pas pour les inspecter.

La GUI s'ouvre avec `python3 -m network_labs --native-lab`. Son manifest par
défaut utilise `$HOME/network-labs-rootfs`. Le bouton Démarrer enregistre le JSON,
puis ouvre un terminal externe pour sudo. Aucune élévation n'est réalisée dans
le processus Tk. La console Linux réelle s'ouvre avec la commande `exec --tty`
ci-dessus ; les terminaux du canvas restent les CLI simulées existantes.

## Mélanger OCI et Firecracker

Ajouter au manifest un node de ce type et un port libre sur le switch, puis
relier `["VM1", "eth0"]` à ce port dans `links` :

```json
{
  "name": "VM1",
  "runtime": "firecracker",
  "role": "host",
  "memory_mib": 128,
  "kernel": "/chemin/absolu/vmlinux",
  "disk": "/chemin/absolu/rootfs.ext4",
  "interfaces": {"eth0": "192.0.2.30/24"}
}
```

Prérequis supplémentaires : Firecracker installé dans le PATH utilisé par sudo,
KVM accessible, kernel Linux compatible Firecracker avec Virtio et configuration
IP au boot (`CONFIG_IP_PNP`), disque root ext4 amorçable et init. Les assets doivent
correspondre à l'architecture du PC. Aucun kernel ou firmware n'est inclus.
Le guest doit conserver l'IP de la ligne de commande ; un gestionnaire réseau
dans son rootfs peut la remplacer et doit donc être configuré en conséquence.

L'adaptateur expose un TAP dans un namespace dédié et le relie aux veth par un
bridge. Il ne se contente pas d'un proxy TCP ou NAT, ce qui permet le transport
Ethernet entre OCI et VM. Il est limité à **un host IPv4 avec une NIC** ; pas encore
de routeur VM multi-NIC, d'agent guest, de `exec` VM, de snapshots ou d'API live.
Le VMM est lancé avec `--no-api`. Lire la console à
`/run/network-labs/<lab>/<node>/console.log` avec sudo et tester les paquets pour
vérifier la disponibilité du guest. Le lancement du VMM n'est pas un test de boot.

## Configuration réelle et limites

- `interfaces` utilise `eth0`..`eth99`, IPv4/CIDR statique ou chaîne vide.
  `gateway` ajoute une route par défaut **dans le node**, jamais dans l'hôte.
- `role: switch` crée `br0` sans adresse et y attache les ports. STP est désactivé ;
  les cycles entre switches sont refusés avant création des ressources.
- `role: router` active le forwarding IPv4 dans son namespace. FRR reste à
  installer/configurer dans le rootfs ; le rôle ne simule pas de daemon OSPF/BGP.
- `role: firewall` exige des commandes `startup` explicites. Il ne génère ni
  politique ni NAT et ne transforme pas BusyBox en FortiOS.
- `command` est le processus persistant du container (par défaut `sleep`).
  `startup` est une liste de tableaux argv exécutés dans le container, par exemple
  `[["/bin/sh", "-c", "...script de configuration..."]]`. Les shells éventuels sont
  explicitement demandés **dans le node**, pas exécutés sur l'hôte.
- La GUI constructeur, les traductions de CLI, DHCP, VLAN/STP, FRR, nftables et
  les services nécessitent encore leur intégration dédiée. Les réglages du
  simulateur pédagogique ne sont pas importés automatiquement.
- Les rôles/services non portés échouent explicitement. Aucune opération native
  ne retombe sur une réponse pédagogique calculée.

## Mémoire et durée de vie

Le manifest propose 2048 Mio, dont 512 Mio de réserve pour GUI et surcoûts.
La somme des allocations des nodes + réserve est validée avant démarrage.
Les containers ont une limite cgroup par node, un quota CPU et 128 processus.
Firecracker reçoit une taille de RAM guest, qui n'inclut pas toute la mémoire du VMM.

**Le total du programme n'est pas plafonné à 2 Gio par cette validation.**
`status` peut lire `memory.current` des cgroups OCI ; cela n'inclut pas tout le
programme, les VMM ou le kernel hôte. Aucun nombre de nodes sous 2 Gio n'est
garanti sans mesure GUI ouverte et trafic actif.

Chaque container a un overlay privé : une écriture sur PC1 n'apparaît pas sur PC2.
Chaque VM a sa copie du disque. Ces modifications restent présentes entre les
commandes, mais **stop supprime les overlays, copies de disques et logs**.
Exporter ce qui doit être conservé avant stop ; le JSON et les assets de base
restent intacts. Le prochain start rejoue le manifest depuis ces assets.

Les ressources sont enregistrées dans `/run/network-labs/<lab>` et les namespaces
portent un préfixe propre au lab. Le gestionnaire verrouille le lab, refuse les
collisions, tente un rollback à l'échec et conserve l'état si le nettoyage échoue.
`stop <lab>` utilise cet état, pas un manifest éventuellement modifié entre-temps.
Le réseau physique, les routes et règles firewall de l'hôte ne sont pas configurés.

## Validation

Tests sans privilèges :

```bash
python3 -m unittest discover -s tests -p test_appliance_runtime.py -v
```

Test réel opt-in sur un hôte Linux de test avec les prérequis :

```bash
sudo env NETWORK_LABS_NATIVE_TESTS=1 python3 -m unittest discover \
  -s tests -p test_native_integration.py -v
```

Ce test démarre trois containers, vérifie un vrai ping à travers le bridge,
l'isolation des fichiers, la persistance entre commandes, la coupure/reprise
d'un lien, la conservation des routes de l'hôte et le nettoyage. Il fait aussi
partie du job CI `native-containers`. Firecracker nécessite une validation
supplémentaire avec assets et KVM ; ce test OCI ne valide pas les microVMs.

## Références de conception

- [OCI runtime specification](https://github.com/opencontainers/runtime-spec)
- [crun, commandes et options](https://github.com/containers/crun/blob/main/crun.1.md)
- [Linux network namespaces](https://man7.org/linux/man-pages/man7/network_namespaces.7.html)
- [cgroups v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)
- [Firecracker](https://github.com/firecracker-microvm/firecracker)
- [libkrun](https://github.com/libkrun/libkrun)
- [Unikraft](https://github.com/unikraft/unikraft)
- [Hyperlight / Nanvix](https://opensource.microsoft.com/blog/2026/01/28/hyperlight-nanvix-posix-support-for-hyperlight-micro-vms/)
- [WASI 0.3](https://wasi.dev/releases/wasi-p3)
- [netkit, documentation Cilium](https://docs.cilium.io/en/latest/operations/performance/tuning/)
