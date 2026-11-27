# Documentation : par où commencer

Network LABS a deux moteurs. Les **micro-VM** (Firecracker, une vraie machine Linux par équipement) sont le cœur de la
release 1 et de l'atelier. Les **conteneurs OCI** sont l'ancien moteur, gelé pendant la release 1 ; beaucoup de
documents ci-dessous datent de lui. Chaque document dit en tête de quel moteur il parle.

## D'abord

| Document | Pour |
|---|---|
| [README](../README.md) | installer, lancer, utiliser l'atelier comme Packet Tracer |
| [STATUS.md](STATUS.md) | ce qui marche aujourd'hui, fonction par fonction, et ce qui manque (à jour) |
| [RELEASE_1.md](RELEASE_1.md) | le périmètre de la première version et ses règles |
| [PROJECT_VISION.md](PROJECT_VISION.md) | où va le projet |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | langues, style, tests, vérifications, licence des contributions |
| [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) | polices, icônes et feuilles de style reprises, leurs licences ; les marques |

## Utiliser l'application

| Document | Sujet |
|---|---|
| [GUI.md](GUI.md) | configurer un équipement dans l'atelier ou en CLI |
| [WEB.md](WEB.md) | les pages de gestion web des équipements |
| [SWITCHING.md](SWITCHING.md) | la CLI dans Network LABS |
| [FIDELITY.md](FIDELITY.md) | les interfaces et commandes de chaque constructeur, ce qui est copié et ce qui ne l'est pas |
| [MODELS.md](MODELS.md) | les modèles et marques de la bibliothèque |
| [NODE_MANAGEMENT_ROADMAP.md](NODE_MANAGEMENT_ROADMAP.md) | ce que chaque type d'équipement permet de régler |
| [SIMULATION.md](SIMULATION.md) | comprendre un test réseau |
| [ARCHITECTURE_FR.md](ARCHITECTURE_FR.md) | comment les moteurs fonctionnent, et leurs limites |

## Conteneurs (OCI), moteur gelé

[CONTAINERS.md](CONTAINERS.md) rassemble les scénarios en ligne de commande. Le détail par fonction :
[NATIVE_LAN_CORE.md](NATIVE_LAN_CORE.md) (le guide principal), [LAN_PROTOCOL_COVERAGE.md](LAN_PROTOCOL_COVERAGE.md),
[HYBRID_APPLIANCES.md](HYBRID_APPLIANCES.md), [NATIVE_GUI_FLOW.md](NATIVE_GUI_FLOW.md), [FIREWALLS.md](FIREWALLS.md),
[SERVICES.md](SERVICES.md), [STP_LACP_VALIDATION.md](STP_LACP_VALIDATION.md), [TRUNK_VLAN_REVIEW.md](TRUNK_VLAN_REVIEW.md),
[BENCHMARK_KERNEL_PEAK.md](BENCHMARK_KERNEL_PEAK.md), puis une note par service :

- DNS et IPv6 : [DNS_AAAA_ONLY](DNS_AAAA_ONLY.md), [DUAL_STACK_DNS](DUAL_STACK_DNS.md),
  [DUAL_STACK_SERVICES](DUAL_STACK_SERVICES.md), [IPV6_DNS_FIREWALL](IPV6_DNS_FIREWALL.md),
  [IPV6_DNS_HTTPS](IPV6_DNS_HTTPS.md), [IPV6_DNS_OSPFV3](IPV6_DNS_OSPFV3.md),
  [IPV6_DNS_OSPFV3_FAILOVER](IPV6_DNS_OSPFV3_FAILOVER.md), [IPV6_DNS_SUBINTERFACES](IPV6_DNS_SUBINTERFACES.md),
  [IPV6_DNS_TFTP](IPV6_DNS_TFTP.md), [IPV6_INPUT_FIREWALL](IPV6_INPUT_FIREWALL.md), [PROBE_IPV6](PROBE_IPV6.md).
- HTTPS : [HTTPS_SERVER](HTTPS_SERVER.md), [HTTPS_IDENTITY_LIFECYCLE](HTTPS_IDENTITY_LIFECYCLE.md),
  [IPV6_HTTPS](IPV6_HTTPS.md), [IPV6_HTTPS_FIREWALL](IPV6_HTTPS_FIREWALL.md).
- NTP et TFTP : [IPV6_NTP](IPV6_NTP.md), [IPV6_NTP_RELAY](IPV6_NTP_RELAY.md), [IPV6_TFTP](IPV6_TFTP.md),
  [IPV6_TFTP_SUBINTERFACES](IPV6_TFTP_SUBINTERFACES.md), [TFTP_IMPORTS](TFTP_IMPORTS.md).
- RADIUS et 802.1X : [NATIVE_RADIUS](NATIVE_RADIUS.md), [RADIUS_ACCOUNTING](RADIUS_ACCOUNTING.md),
  [RADIUS_EAP_MD5](RADIUS_EAP_MD5.md), [RADIUS_LOGIN](RADIUS_LOGIN.md), [RADIUS_OUTBOX](RADIUS_OUTBOX.md),
  [RADIUS_ROLES](RADIUS_ROLES.md), [RADIUS_SESSION_JOURNAL](RADIUS_SESSION_JOURNAL.md), [DOT1X_WIRED](DOT1X_WIRED.md),
  [DOT1X_MANAGED_PEER](DOT1X_MANAGED_PEER.md), [DUAL_STACK_RADIUS](DUAL_STACK_RADIUS.md).
- SSH et Telnet : [SSH_ACCESS_POLICY](SSH_ACCESS_POLICY.md), [SSH_HOST_IDENTITY](SSH_HOST_IDENTITY.md),
  [SSH_RADIUS](SSH_RADIUS.md), [SSH_RADIUS_HOST_IDENTITY](SSH_RADIUS_HOST_IDENTITY.md),
  [SSH_RADIUS_SHELL](SSH_RADIUS_SHELL.md), [SSH_SHELL_HOST_IDENTITY](SSH_SHELL_HOST_IDENTITY.md),
  [DUAL_STACK_SSH_HOST_IDENTITY](DUAL_STACK_SSH_HOST_IDENTITY.md), [TELNET_RADIUS](TELNET_RADIUS.md).
- Syslog : [SYSLOG_FORWARD](SYSLOG_FORWARD.md), [SYSLOG_FORWARD_RECOVERY](SYSLOG_FORWARD_RECOVERY.md),
  [SYSLOG_DISK_QUEUE](SYSLOG_DISK_QUEUE.md), [SYSLOG_TCP](SYSLOG_TCP.md), [SYSLOG_TLS](SYSLOG_TLS.md),
  [SYSLOG_TLS_LIFECYCLE](SYSLOG_TLS_LIFECYCLE.md).

## Expériences

[MICRO_APPLIANCES.md](MICRO_APPLIANCES.md) et [WASM_PROJECT.md](WASM_PROJECT.md) : des équipements en WebAssembly,
prototype facultatif hors de l'atelier.

## Historique (ne décrit plus l'application)

[PROJECT_STATUS.md](PROJECT_STATUS.md) (point d'étape du 6 novembre 2026), [LAN.md](LAN.md),
[LAN_CORE_ACCEPTANCE.md](LAN_CORE_ACCEPTANCE.md) (gelé le 6 novembre), [LAN_NEXT_STEPS.md](LAN_NEXT_STEPS.md),
[history/OLD_SIMULATOR.md](history/OLD_SIMULATOR.md) (l'ancien simulateur pédagogique, retiré),
[history/CODEX_HANDOFF.md](history/CODEX_HANDOFF.md), les preuves d'exécution [evidence/](evidence) et les mesures
[benchmarks/](benchmarks).
