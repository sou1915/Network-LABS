# LAN protocol coverage and remaining work

LAN remains the priority before WAN. A protocol name means only the documented
profile below; it does not imply every vendor implementation, option, GUI or
coexistence combination. The native workflow provides real packet/service tests;
the educational canvas/Wasm engine remains separate.

Both complete native CI runs for commit `0e761a0` passed all 51 tests on
2026-10-28, covering the documented STP/LACP recovery and chronyd control
socket corrections alongside the other native scenarios:
[push](https://github.com/sou1915/Network-LABS/actions/runs/40716003990/job/122913748047),
[pull request](https://github.com/sou1915/Network-LABS/actions/runs/40716014900/job/122913781926).
This records those bounded profiles, not completion of the remaining columns.

The [STP/LACP validation matrix](STP_LACP_VALIDATION.md) describes the additional
partial-flush rollback, min-links, logical shutdown and saved restart scenarios.

| Family | Current bounded profile | Remaining work |
|---|---|---|
| SSH | Dropbear, ed25519 public-key auth, non-root Linux command/PTY, TCP/22 | Vendor shells, richer account/AAA policy, managed host-key persistence, IPv6/coexistence profiles |
| Telnet | BusyBox telnetd + login, SHA-512 password hash, non-root Linux terminal, TCP/23 | Vendor CLI adapters and richer account/AAA policy |
| Syslog | Real local logging + UDP/514 forwarding; node-local rsyslog collector with sender allowlist, rotation and real fault/packet tests | TCP/TLS, richer RFC5424 policy, durable central retention/search and structured device events |
| SNMP | Separate read-only IPv4 v2c and v3 USM SHA-256/AES authPriv agents; manager policy, sysName/agent uptime, real IF-MIB counters; v2c trap/inform and separate v3 authPriv inform/sender-engine trap profiles with log-only receivers and packet/loss/restore tests; selected physical IF-MIB up/down observations via native DisMan | Vendor-specific events, broader operational states/event sources, richer user/algorithm policy, vendor MIBs, IPv6 and broader coexistence |
| NTP/SNTP | One unauthenticated IPv4 SNTP query; temporary educational responder; experimental managed chronyd relay and explicitly isolated local-reference lab with allowlisted clients, without clock writes; complete native end-to-end test passed in CI | Independent node clock representation, broader upstream policy, authentication and IPv6 |
| AAA/access | [Bounded RADIUS PAP authentication observation and experimental managed FreeRADIUS 3 server](NATIVE_RADIUS.md) with explicit clients/users and mandatory integrity checks; FreeRADIUS 3.2.5 interoperability and managed OCI policy/save/restart passed in dedicated CI; no access-policy changes | Broader interoperability, actual login/access enforcement, accounting, TACACS+, 802.1X/EAP and policy tests |
| File services | Bounded TFTP octet read with optional SHA-256, timeout retries and bounded final ACK dally; experimental managed read-only dnsmasq server with declared text or Base64 binary files, exercised in native CI | Direct binary file imports, write, larger files/options, FTP, SFTP and PXE |
| IPv4/IPv6 | Real addressing, ARP/NDP/DAD, ICMP, static routing; static routed dual-stack | Dynamic dual-stack combinations, IPv6 SVIs/subinterfaces, IPv6 policy/security |
| DHCP/DNS | IPv4 leases/reservations/relay/multi-pool, local DNS A; IPv6 IA_NA and RA/SLAAC subsets | DHCPv6 relay/PD/stateless, IPv6 DNS provisioning, advanced DNS/DNSSEC |
| HTTP/HTTPS | BusyBox HTTP sample service; bounded DNS/TCP/HTTP(S) HEAD with explicit CA/name validation; temporary two-node HTTPS demo with generated trust, exercised in native CI | Persistent managed HTTPS server, revocation/mutual TLS, redirects/application profiles, IPv6 service probes |
| VLAN/switching | Access/trunk dot1Q, Linux bridges, LACP, common STP; managed STP/LACP administrative recovery reconciles dynamic FDB after settled control state, with repeated bidirectional VLAN tests in dedicated CI; scoped OVS RSTP | Broader kernel/carrier-failure validation, MSTP/PVST, broader switching interactions and vendor details |
| Discovery/multicast | Received LLDP and scoped Linux IGMPv2 snooping/querier | CDP, MLD, broader multicast and discovery profiles |
| Internal routing | Static IPv4/IPv6, BIRD OSPFv2 area 0 subsets | OSPFv3, broader IGP features, VRRP/gateway redundancy and failover |
| Security | Scoped IPv4 nftables/NAT, port security, DHCP snooping, ARP/IP admission | IPv6 firewall/RA Guard and broader security/service coexistence |
| Local Windows/Linux services | Basic node connectivity and shell services | SMB/AD-oriented scenarios, mDNS/LLMNR/NetBIOS and device-specific connectivity GUIs |

WAN/BGP/VPN and full vendor firmware/GUI fidelity remain separate later stages.
No completion percentage or whole-application 2 GiB guarantee is derived from
this list. See [Native LAN core](NATIVE_LAN_CORE.md#ssh-telnet-and-remote-udp-syslog)
for exact commands and scope.
