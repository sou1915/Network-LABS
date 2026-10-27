# LAN protocol coverage and remaining work

LAN remains the priority before WAN. A protocol name means only the documented
profile below; it does not imply every vendor implementation, option, GUI or
coexistence combination. The native workflow provides real packet/service tests;
the educational canvas/Wasm engine remains separate.

| Family | Current bounded profile | Remaining work |
|---|---|---|
| SSH | Dropbear, ed25519 public-key auth, non-root Linux command/PTY, TCP/22 | Vendor shells, richer account/AAA policy, managed host-key persistence, IPv6/coexistence profiles |
| Telnet | BusyBox telnetd + login, SHA-512 password hash, non-root Linux terminal, TCP/23 | Vendor CLI adapters and richer account/AAA policy |
| Syslog | Real local logging + UDP/514 forwarding; node-local rsyslog collector with sender allowlist, rotation and real fault/packet tests | TCP/TLS, richer RFC5424 policy, durable central retention/search and structured device events |
| SNMP | Separate read-only IPv4 v2c and v3 USM SHA-256/AES authPriv agents; manager policy, sysName/agent uptime, real IF-MIB counters; v2c trap/inform and separate v3 authPriv inform/sender-engine trap profiles with log-only receivers and packet/loss/restore tests; selected physical IF-MIB up/down observations via native DisMan | Vendor-specific events, broader operational states/event sources, richer user/algorithm policy, vendor MIBs, IPv6 and broader coexistence |
| NTP/SNTP | One unauthenticated IPv4 SNTP query to an existing server; temporary educational two-node responder using host time, with offset/delay evidence and no clock writes | Persistent managed NTP server with real upstream, independent node clock representation, continuous discipline, authentication, IPv6 and native end-to-end lab validation |
| AAA/access | Planned | RADIUS, TACACS+, 802.1X/EAP and policy tests |
| File services | Planned | TFTP, FTP and SFTP/PXE profiles with actual transfers |
| IPv4/IPv6 | Real addressing, ARP/NDP/DAD, ICMP, static routing; static routed dual-stack | Dynamic dual-stack combinations, IPv6 SVIs/subinterfaces, IPv6 policy/security |
| DHCP/DNS | IPv4 leases/reservations/relay/multi-pool, local DNS A; IPv6 IA_NA and RA/SLAAC subsets | DHCPv6 relay/PD/stateless, IPv6 DNS provisioning, advanced DNS/DNSSEC |
| HTTP | BusyBox sample service and bounded DNS/TCP/HTTP HEAD probes | HTTPS/TLS, redirects/application profiles, IPv6 service probes |
| VLAN/switching | Access/trunk dot1Q, Linux bridges, LACP, common STP; scoped OVS RSTP | MSTP/PVST, broader switching interactions and vendor details |
| Discovery/multicast | Received LLDP and scoped Linux IGMPv2 snooping/querier | CDP, MLD, broader multicast and discovery profiles |
| Internal routing | Static IPv4/IPv6, BIRD OSPFv2 area 0 subsets | OSPFv3, broader IGP features, VRRP/gateway redundancy and failover |
| Security | Scoped IPv4 nftables/NAT, port security, DHCP snooping, ARP/IP admission | IPv6 firewall/RA Guard and broader security/service coexistence |
| Local Windows/Linux services | Basic node connectivity and shell services | SMB/AD-oriented scenarios, mDNS/LLMNR/NetBIOS and device-specific connectivity GUIs |

WAN/BGP/VPN and full vendor firmware/GUI fidelity remain separate later stages.
No completion percentage or whole-application 2 GiB guarantee is derived from
this list. See [Native LAN core](NATIVE_LAN_CORE.md#ssh-telnet-and-remote-udp-syslog)
for exact commands and scope.
