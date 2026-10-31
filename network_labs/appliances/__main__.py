"""Native lab commands. No display needed and no implicit host changes."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from .catalog import capabilities
from .runtime import Manager, RuntimeFailure, plan, static_busybox_rootfs
from .spec import example, load


def main(arguments=None):
    parser = argparse.ArgumentParser(description='Network LABS native experimental appliances')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor', help='Read-only host dependency report; not a boot test.')
    labs = commands.add_parser('labs', help='List recorded native lab names, phases and nodes; no liveness checks.')
    labs.add_argument('--json', action='store_true')
    manifests = commands.add_parser('manifests', help='List native JSON manifests in the current directory; no lab changes.')
    manifests.add_argument('--json', action='store_true')
    sample = commands.add_parser('example', help='Print a three-node OCI manifest; no host changes.')
    sample.add_argument('--rootfs', type=Path, required=True)
    sample.add_argument('--ntp', action='store_true', help='Isolated chronyd relay and educational local reference.')
    sample.add_argument('--radius', action='store_true', help='Separate managed FreeRADIUS PAP server; requires explicit lab credentials and matching rootfs.')
    sample.add_argument('--radius-user', help='Username for --radius.')
    sample.add_argument('--radius-password-file', type=Path, help='Private password file for --radius; only SHA-256 is stored.')
    sample.add_argument('--radius-ssh', action='store_true', help='Require RADIUS credentials on stdin for fixed SSH diagnostics; requires --radius and --ssh-authorized-key.')
    sample.add_argument('--radius-ssh-shell', action='store_true', help='Explicitly enable the bounded RADIUS SSH shell, including PTY; requires --radius --radius-ssh.')
    sample.add_argument('--radius-shell', action='store_true', help='With --radius, explicitly permit the learner a non-root CLI shell via radius-login.')
    sample.add_argument('--radius-accounting', action='store_true', help='With --radius --radius-shell, require acknowledged session accounting and enable private server records.')
    sample.add_argument('--radius-secret-file', type=Path, help='Private shared-secret file for --radius; stored in the private manifest.')
    sample.add_argument('--tftp', action='store_true', help='Read-only TFTP server with declared sample files; requires --dnsmasq rootfs.')
    sample.add_argument('--tftp-file', action='append', metavar='NAME=PATH', help='With --tftp, embed a public binary file (max 65536 bytes); repeat up to 8 times, replacing sample files.')
    sample.add_argument('--snmp-notifications', action='store_true', help='Real v2c agent coldStart and log-only trap/inform receiver.')
    sample.add_argument('--snmp-notification-mode', choices=('trap', 'inform'), help='Notification reference mode; default trap; requires --snmp-notifications.')
    sample.add_argument('--snmp-link-events', action='store_true', help='Native DisMan IF-MIB up/down observations and authPriv notifications.')
    sample.add_argument('--snmp-link-mode', choices=('trap', 'inform'), help='Link-event reference delivery; default trap; requires --snmp-link-events.')
    sample.add_argument('--snmpv3-traps', action='store_true', help='Two USM authPriv trap agents and a receiver bound to their fresh runtime engines.')
    sample.add_argument('--snmpv3-informs', action='store_true', help='Real SHA-256/AES authPriv informs and a USM-only log receiver.')
    sample.add_argument('--snmpv3', action='store_true', help='Read-only USM SHA-256/AES authPriv agent, without v2c fallback.')
    sample.add_argument('--snmp-user', help='SNMPv3 username; required with --snmpv3, --snmpv3-informs, --snmpv3-traps or --snmp-link-events.')
    sample.add_argument('--snmp-auth-passphrase-file', type=Path, help='SNMPv3 authentication passphrase file; converted to a master key.')
    sample.add_argument('--snmp-privacy-passphrase-file', type=Path, help='SNMPv3 privacy passphrase file; converted to a master key.')
    sample.add_argument('--snmp', action='store_true', help='Real read-only SNMPv2c agent and separate monitored LAN; requires --snmpd rootfs.')
    sample.add_argument('--snmp-community-file', type=Path, help='8..64 character community token for --snmp; default is the documented lab token.')
    sample.add_argument('--syslog', action='store_true', help='Real UDP syslog sender and rsyslog collector; requires --rsyslog rootfs.')
    sample.add_argument('--management', action='store_true', help='Real SSH/Telnet and UDP syslog sender on an internal IPv4 LAN.')
    sample.add_argument('--ssh-authorized-key', type=Path, help='Public OpenSSH ed25519 key for --management; never a private key.')
    sample.add_argument('--ssh-action', action='append', choices=('identity', 'hostname', 'security-context'), help='Repeat to restrict --management SSH to fixed diagnostics, with no shell or PTY.')
    sample.add_argument('--telnet-password-hash-file', type=Path, help='SHA-512 crypt password hash for --management Telnet login.')
    sample.add_argument('--dual-stack', action='store_true', help='Static IPv4 and IPv6 on the same internal routed LAN; independent forwarding/routes.')
    sample.add_argument('--dhcpv6-pd', action='store_true', help='One real Kea /64 prefix delegation to a router and SLAAC on its LAN; requires PD rootfs assets.')
    sample.add_argument('--dhcpv6-relay', action='store_true', help='Remote DHCPv6 IA_NA pool through a physical relay and BIRD managed RA; requires dnsmasq, bird and birdc rootfs.')
    sample.add_argument('--dhcpv6', action='store_true', help='Stateful BusyBox DHCPv6 client, dnsmasq pool and real RA gateway; requires dnsmasq rootfs.')
    sample.add_argument('--slaac', action='store_true', help='Kernel SLAAC client with real RA and routed IPv6 LAN traffic; requires dnsmasq rootfs.')
    sample.add_argument('--ra-guard-dhcpv6', action='store_true', help='Local IA_NA DHCPv6 and RA across a guarded access VLAN.')
    sample.add_argument('--ra-guard', action='store_true', help='Conservative access-port RA Guard with real SLAAC.')
    sample.add_argument('--ipv6-firewall', action='store_true', help='Static IPv6 forwarding firewall with stateful return traffic.')
    sample.add_argument('--ipv6-subinterfaces', action='store_true', help='Static IPv6 router-on-a-stick and tagged route transit.')
    sample.add_argument('--ipv6-svi', action='store_true', help='Two internal IPv6 VLANs routed by real Linux switch SVIs across a trunk.')
    sample.add_argument('--ipv6-routed', action='store_true', help='Two internal static IPv6 LANs across two routers.')
    sample.add_argument('--ipv6-vlan', action='store_true', help='Six-node static IPv6 VLAN/trunk LAN; no routing or RA.')
    sample.add_argument('--lan-services', action='store_true', help='Eight-node routed DHCP/DNS/HTTP LAN with OSPF and physical LLDP.')
    sample.add_argument('--ospf-dhcp-lldp', action='store_true', help='Physical LLDP discovery on the two-VLAN OSPF/DHCP infrastructure, including its trunk.')
    sample.add_argument('--ospf-dhcp-multi', action='store_true', help='Two DHCP client VLANs and OSPF on one L3 switch, with independent helpers and remote pools.')
    sample.add_argument('--ospf-dhcp', action='store_true', help='Real OSPF and DHCP relay together on one L3 switch, with a remote-pool server.')
    sample.add_argument('--ospf-svi', action='store_true', help='Real OSPF on a Linux L3 switch SVI, VLAN trunk and router.')
    sample.add_argument('--ospf-broadcast', action='store_true', help='Four real BIRD routers on a shared Ethernet LAN with DR/BDR election.')
    sample.add_argument('--ospf-cli', action='store_true', help='Numbered OSPF triangle without routing daemons; configure all three processes through the CLI.')
    sample.add_argument('--ospfv3-svi', action='store_true', help='Real OSPFv3 adjacency on a Linux switch SVI through a tagged transit VLAN.')
    sample.add_argument('--ospfv3', action='store_true', help='Real BIRD 2 OSPFv3 between two internal IPv6 LANs.')
    sample.add_argument('--ospf', action='store_true', help='Real BIRD 2 OSPFv2 area-zero triangle with primary and backup paths.')
    sample.add_argument('--dhcp-multi', action='store_true', help='Two client VLANs, per-VLAN helpers and one real dnsmasq multi-pool server.')
    sample.add_argument('--dhcp-relay', action='store_true', help='Real dnsmasq relay on an L3 switch and remote single-pool BusyBox DHCP server.')
    sample.add_argument('--static-routing', action='store_true', help='L3 switch and router with missing forward/return routes for CLI configuration.')
    sample.add_argument('--svi', action='store_true', help='Real Linux L3 switch with two routed VLAN interfaces and a trunk.')
    sample.add_argument('--rstp', action='store_true', help='Real Open vSwitch RSTP triangle; requires an OVS rootfs and kernel module.')
    sample.add_argument('--lldp', action='store_true', help='Real lldpd neighbor discovery on four isolated OCI nodes.')
    sample.add_argument('--dns', action='store_true', help='Real local dnsmasq DNS, DHCP-supplied resolver, static resolver and HTTP by name.')
    sample.add_argument('--dhcp-reservations', action='store_true', help='Stable DHCP printer reservation and two dynamic clients on a snooped LAN.')
    sample.add_argument('--multicast', action='store_true', help='IGMPv2 snooping and local querier on one access VLAN.')
    sample.add_argument('--ip-source-guard', action='store_true', help='IPv4 source admission with DHCP/static bindings, plus ARP inspection.')
    sample.add_argument('--arp-inspection', action='store_true', help='DHCP-derived and explicit static ARP admission on access ports.')
    sample.add_argument('--dhcp-snooping', action='store_true', help='Trusted DHCP server and blocked rogue server with observed bindings.')
    sample.add_argument('--port-security', action='store_true', help='Three-node LAN with static secure source-MAC admission.')
    sample.add_argument('--stp', action='store_true', help='Nine-node VLAN LAN on a triangle with real classic STP.')
    sample.add_argument('--stp-lacp', action='store_true', help='Common STP/LACP/spare with explicit carrier FDB recovery.')
    sample.add_argument('--stp-lacp-min-links', type=int, choices=(1, 2), help='LACP carrier threshold for --stp-lacp, default 1.')
    sample.add_argument('--stp-lacp-strict', action='store_true', help='Require native strict LACP for --stp-lacp; unsupported kernel/iproute2 refuses startup.')
    sample.add_argument('--lacp', action='store_true', help='Six-node VLAN LAN with a negotiated two-link LACP trunk.')
    sample.add_argument('--enterprise', action='store_true', help='20-node LAN with router, firewall, DHCP and WAN.')
    sample.add_argument('--firewall', action='store_true', help='Three-node stateful firewall and NAT reference lab.')
    sample.add_argument('--campus', action='store_true', help='Eight-node VLAN/trunk/router/DHCP reference LAN.')
    rootfs = commands.add_parser('rootfs', help='Build an offline minimal rootfs from trusted static BusyBox.')
    rootfs.add_argument('--busybox', type=Path, required=True)
    rootfs.add_argument('--openvswitch', action='store_true', help='Copy trusted installed OVS executables, ELF libraries and schema.')
    rootfs.add_argument('--lldpd', type=Path, help='Trusted Debian/Ubuntu lldpd executable, paired with --lldpcli.')
    rootfs.add_argument('--lldpcli', type=Path, help='Trusted matching lldpcli executable.')
    rootfs.add_argument('--bird', type=Path, help='Trusted BIRD 2 daemon ELF for routing and router advertisements.')
    rootfs.add_argument('--birdc', type=Path, help='Trusted BIRD 2 control-client ELF.')
    rootfs.add_argument('--snmptrapd', type=Path, help='Trusted Net-SNMP trap/inform receiver ELF and shared libraries.')
    rootfs.add_argument('--snmpd', type=Path, help='Trusted Net-SNMP agent ELF and its resolved shared libraries.')
    rootfs.add_argument('--rsyslog', type=Path, help='Trusted rsyslogd ELF for a real UDP collector.')
    rootfs.add_argument('--freeradius', type=Path, help='Trusted FreeRADIUS 3 ELF for managed PAP authentication.')
    rootfs.add_argument('--freeradius-modules', type=Path, help='Trusted matching FreeRADIUS module directory containing rlm_pap.so.')
    rootfs.add_argument('--freeradius-dictionaries', type=Path, help='Trusted complete FreeRADIUS dictionary directory.')
    rootfs.add_argument('--chronyd', type=Path, help='Trusted chronyd ELF for the bounded NTP server.')
    rootfs.add_argument('--chronyc', type=Path, help='Trusted compatible chronyc ELF for read-only NTP CLI observations; requires --chronyd.')
    rootfs.add_argument('--rsyslog-modules', type=Path, help='Trusted matching imudp.so/lmnet.so directory; otherwise detect the system directory.')
    rootfs.add_argument('--ssh-relay', type=Path, help='Trusted compiled SSH RADIUS relay ELF; required for the optional interactive shell, with --dropbear.')
    rootfs.add_argument('--dropbear', type=Path, help='Trusted Dropbear SSH server ELF and its resolved shared libraries.')
    rootfs.add_argument('--kea-dhcp6', type=Path, help='Trusted Kea DHCPv6 executable for the isolated PD server.')
    rootfs.add_argument('--dhcpv6-pd-hook', type=Path, help='Trusted compiled finite /64 DHCPv6 PD event hook.')
    rootfs.add_argument('--dnsmasq', type=Path, help='Optional trusted host dnsmasq ELF; copy it and resolved shared libraries offline.')
    rootfs.add_argument('--output', type=Path, required=True)
    for command in ('plan', 'start'):
        item = commands.add_parser(command)
        item.add_argument('manifest', type=Path)
    bench = commands.add_parser('benchmark', help='Start a stopped OCI lab, measure idle/ICMP load, then stop it.')
    bench.add_argument('manifest', type=Path)
    bench.add_argument('--seconds', type=int, default=5, help='Seconds per phase, 1..30.')
    bench.add_argument('--source', action='append', help='Repeat for each host; default: PC-prefixed hosts.')
    bench.add_argument('--target', required=True, help='Static IPv4 address belonging to this lab.')
    bench.add_argument('--output', type=Path, help='New JSON report file; existing files are refused.')
    for command in ('status', 'stop', 'save', 'restore', 'recover', 'export'):
        item = commands.add_parser(command)
        item.add_argument('name')
        if command == 'export':
            item.add_argument('--startup', action='store_true', help='Export last saved startup configuration.')
    show = commands.add_parser('show', help='Read actual Linux state using a bounded set of IOS-style show commands.')
    show.add_argument('name'); show.add_argument('node')
    show.add_argument('--text', required=True, help='One complete command, e.g. "show ip interface brief".')
    show.add_argument('--json', action='store_true')
    inspect = commands.add_parser('inspect', help='Read actual kernel interfaces/routes/VLAN/FDB state.')
    inspect.add_argument('name'); inspect.add_argument('node')
    route = commands.add_parser('route', help='Observe the actual Linux IPv4 route decision; sends no test packets.')
    route.add_argument('name'); route.add_argument('node'); route.add_argument('destination')
    route.add_argument('--source', help='Local source, or original remote source with --ingress.')
    route.add_argument('--ingress', help='Managed Linux ingress interface; requires --source.')
    route.add_argument('--json', action='store_true')
    verify = commands.add_parser('verify', help='Send bounded real ICMP between two observed single-NIC OCI hosts.')
    verify.add_argument('name'); verify.add_argument('source'); verify.add_argument('destination')
    verify.add_argument('--family', choices=('ipv4', 'ipv6'), default='ipv4')
    verify.add_argument('--count', type=int, default=3)
    verify.add_argument('--bidirectional', action='store_true')
    verify.add_argument('--json', action='store_true')
    service = commands.add_parser('probe', help='Bounded DNS A, TCP, HTTP(S) HEAD and SNTP from an OCI host.')
    service.add_argument('name'); service.add_argument('source'); service.add_argument('target')
    service.add_argument('--protocol', choices=('dns', 'tcp', 'http', 'https', 'sntp'), default='http')
    service.add_argument('--ca-file', type=Path, help='Explicit trusted PEM CA bundle for HTTPS; required with --protocol https.')
    service.add_argument('--port', type=int)
    service.add_argument('--path', default='/')
    service.add_argument('--timeout', type=int, default=3, help='Deadline per wire stage, 1..5 seconds.')
    service.add_argument('--json', action='store_true')
    tftp = commands.add_parser('tftp-read', help='Read a bounded TFTP file from a managed host without saving it.')
    tftp.add_argument('name'); tftp.add_argument('source'); tftp.add_argument('server'); tftp.add_argument('filename')
    tftp.add_argument('--timeout', type=int, default=5, help='Total transfer deadline, 1..10 seconds.')
    tftp.add_argument('--sha256', help='Optional expected SHA-256 of the complete transfer.')
    tftp.add_argument('--json', action='store_true')
    radius = commands.add_parser('radius-auth', help='One explicit PAP authentication request to an existing RADIUS server; no node access changes.')
    radius.add_argument('name'); radius.add_argument('source'); radius.add_argument('server')
    radius.add_argument('--username', required=True)
    radius.add_argument('--password-file', type=Path, required=True)
    radius.add_argument('--secret-file', type=Path, required=True)
    radius.add_argument('--timeout', type=int, default=3, help='Overall deadline, 1..5 seconds; no retries.')
    access = commands.add_parser('radius-exec', help='Require a verified RADIUS Accept before one fixed non-root diagnostic; no device login policy changes.')
    access.add_argument('name'); access.add_argument('source'); access.add_argument('server')
    access.add_argument('--action', choices=('identity', 'hostname', 'security-context'), default='identity')
    access.add_argument('--username', required=True)
    access.add_argument('--password-file', type=Path, required=True)
    access.add_argument('--secret-file', type=Path, required=True)
    access.add_argument('--timeout', type=int, default=3)
    access.add_argument('--json', action='store_true')
    login = commands.add_parser('radius-login', help='Open a non-root local CLI shell after declared shell authorization and verified RADIUS Accept; not SSH/Telnet.')
    login.add_argument('name'); login.add_argument('source'); login.add_argument('server')
    login.add_argument('--username', required=True)
    login.add_argument('--password-file', type=Path, required=True)
    login.add_argument('--secret-file', type=Path, required=True)
    login.add_argument('--timeout', type=int, default=3, help='Authentication deadline, 1..5 seconds; not session lifetime.')
    login.add_argument('--no-tty', action='store_true', help='Read shell commands from stdin without a terminal.')
    login.add_argument('--seconds', type=int, help='Session lifetime, 1..3600 seconds, at most the declared node limit (default policy: 300).')
    radius.add_argument('--json', action='store_true')
    sntp_demo = commands.add_parser('sntp-demo', help='One-shot educational SNTP exchange between two managed hosts.')
    sntp_demo.add_argument('name'); sntp_demo.add_argument('client'); sntp_demo.add_argument('server')
    sntp_demo.add_argument('--server-offset-seconds', type=int, default=0, help='Temporary educational server offset from host time, -86400..86400 seconds.')
    sntp_demo.add_argument('--samples', type=int, default=1, help='Number of sequential samples, 1..5.')
    sntp_demo.add_argument('--json', action='store_true')
    https_demo = commands.add_parser('https-demo', help='Temporary HTTPS exchange between two managed hosts with generated demo trust.')
    https_demo.add_argument('name'); https_demo.add_argument('client'); https_demo.add_argument('server')
    https_demo.add_argument('--json', action='store_true')
    explain = commands.add_parser('explain', help='Explain observed native state in French, without sending test packets.')
    explain.add_argument('name'); explain.add_argument('node', nargs='?')
    explain.add_argument('--json', action='store_true', help='Structured observations for scripts and future UI.')
    monitor = commands.add_parser('monitor', help='Two passive counter samples with conservative per-interface deltas/rates.')
    monitor.add_argument('name'); monitor.add_argument('node'); monitor.add_argument('interface', nargs='?')
    monitor.add_argument('--seconds', type=int, default=5, help='Wait between samples, 1..30 seconds.')
    monitor.add_argument('--json', action='store_true')
    multicast = commands.add_parser('multicast', help='Bounded real IPv4 multicast send or membership/receive probe; releases lab lock.')
    multicast.add_argument('name'); multicast.add_argument('node'); multicast.add_argument('interface', nargs='?', default='eth0')
    multicast.add_argument('--group', default='239.10.10.10')
    multicast.add_argument('--port', type=int, default=5000)
    multicast.add_argument('--seconds', type=int, default=10)
    multicast.add_argument('--count', type=int, default=3)
    multicast.add_argument('--send', help='Send this UTF-8 payload; omit to join and receive.')
    capture = commands.add_parser('capture', help='Bounded real PCAP capture in an OCI node; other lab commands remain usable.')
    capture.add_argument('name'); capture.add_argument('node'); capture.add_argument('interface')
    capture.add_argument('--output', type=Path, required=True, help='New PCAP file; existing files are refused.')
    capture.add_argument('--seconds', type=int, default=10)
    capture.add_argument('--packets', type=int, default=1000)
    capture.add_argument('--snaplen', type=int, default=2048)
    capture.add_argument('--filter', default='', help='Quoted libpcap BPF expression, never a shell command.')
    configure = commands.add_parser('configure', help='Apply a validated partial IOS-style block to a running node.')
    configure.add_argument('name'); configure.add_argument('node')
    config_source = configure.add_mutually_exclusive_group(required=True)
    config_source.add_argument('--file', type=Path)
    config_source.add_argument('--text', help='Multiline configuration; quote it in the calling shell.')
    multicast_policy = commands.add_parser('multicast-policy', help='Apply a validated single-access-VLAN Linux multicast policy.')
    multicast_policy.add_argument('name'); multicast_policy.add_argument('node')
    multicast_policy.add_argument('--file', type=Path, required=True)
    tree = commands.add_parser('spanning-tree', help='Configure a Linux common STP policy; this is not PVST/RSTP.')
    tree.add_argument('name'); tree.add_argument('node')
    tree_source = tree.add_mutually_exclusive_group(required=True)
    tree_source.add_argument('--file', type=Path)
    tree_source.add_argument('--priority', type=int, help='Change only this switch bridge priority.')
    firewall = commands.add_parser('firewall', help='Atomically replace a managed IPv4 firewall policy.')
    firewall.add_argument('name'); firewall.add_argument('node')
    firewall.add_argument('--file', type=Path, required=True)
    for action in ('sessions', 'clear-sessions'):
        item = commands.add_parser(action)
        item.add_argument('name'); item.add_argument('node')
    execute = commands.add_parser('exec', help='Execute real commands in an OCI node, not the simulator CLI.')
    execute.add_argument('--tty', action='store_true')
    execute.add_argument('name'); execute.add_argument('node')
    execute.add_argument('argv', nargs=argparse.REMAINDER)
    args = parser.parse_args(arguments)
    try:
        if args.command == 'doctor':
            result = capabilities()
        elif args.command == 'labs':
            from .labs import list_labs, render
            result = list_labs()
            print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
            return 0
        elif args.command == 'manifests':
            from .manifests import list_manifests, render
            result = list_manifests()
            print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
            return 0
        elif args.command == 'example':
            if args.stp_lacp_min_links is not None and not args.stp_lacp:
                raise ValueError('--stp-lacp-min-links requires --stp-lacp.')
            if args.stp_lacp_strict and not args.stp_lacp:
                raise ValueError('--stp-lacp-strict requires --stp-lacp.')
            from .examples import stp_lacp_lab, ra_guard_dhcpv6_lab, ra_guard_lab, ipv6_firewall_lab, ipv6_subinterfaces_lab, dhcpv6_pd_lab, dhcpv6_relay_lab, ospfv3_svi_lab, ipv6_svi_lab, ospfv3_lab, campus, firewall_lab, enterprise, lacp_lab, stp_lab, port_security_lab, dhcp_snooping_lab, arp_inspection_lab, source_guard_lab, multicast_lab, dhcp_reservations_lab, dns_lab, lldp_lab, rstp_lab, svi_lab, static_routing_lab, dhcp_relay_lab, dhcp_multi_lab, ospf_lab, ospf_cli_lab, ospf_broadcast_lab, ospf_svi_lab, ospf_dhcp_lab, ospf_dhcp_multi_lab, ospf_dhcp_lldp_lab, lan_services_lab, ipv6_vlan_lab, ipv6_routed_lab, slaac_lab, dhcpv6_lab, dual_stack_lab, management_lab, syslog_lab, snmp_lab, snmpv3_lab, snmp_notifications_lab, snmpv3_informs_lab, snmpv3_traps_lab, snmp_links_lab
            if sum((args.stp_lacp, args.ra_guard_dhcpv6, args.ra_guard, args.ipv6_firewall, args.ipv6_subinterfaces, args.dhcpv6_pd, args.dhcpv6_relay, args.ospfv3_svi, args.ipv6_svi, args.ospfv3, args.radius, args.tftp, args.ntp, args.snmp_link_events, args.snmpv3_traps, args.snmpv3_informs, args.snmp_notifications, args.snmpv3, args.snmp, args.syslog, args.management, args.dual_stack, args.dhcpv6, args.slaac, args.ipv6_routed, args.ipv6_vlan, args.lan_services, args.ospf_dhcp_lldp, args.campus, args.firewall, args.enterprise, args.lacp, args.stp, args.port_security, args.dhcp_snooping, args.arp_inspection, args.ip_source_guard, args.multicast, args.dhcp_reservations, args.dns, args.lldp, args.rstp, args.svi, args.static_routing, args.dhcp_relay, args.dhcp_multi, args.ospf, args.ospf_cli, args.ospf_broadcast, args.ospf_svi, args.ospf_dhcp, args.ospf_dhcp_multi)) > 1:
                raise ValueError('Choose only one reference scenario.')
            if args.snmp_link_mode and not args.snmp_link_events:
                raise ValueError('Link-event mode requires --snmp-link-events.')
            if args.snmp_notification_mode and not args.snmp_notifications:
                raise ValueError('Notification mode requires --snmp-notifications.')
            user = None
            v3_options = (args.snmp_user, args.snmp_auth_passphrase_file, args.snmp_privacy_passphrase_file)
            if args.snmpv3 or args.snmpv3_informs or args.snmpv3_traps or args.snmp_link_events:
                if not all(v3_options):
                    raise ValueError('--snmpv3 / --snmpv3-informs / --snmpv3-traps / --snmp-link-events requires a username and both passphrase files.')
                from .snmp import usm_credentials
                user = usm_credentials(args.snmp_user, args.snmp_auth_passphrase_file.read_text().rstrip('\r\n'),
                                       args.snmp_privacy_passphrase_file.read_text().rstrip('\r\n'))
            elif any(v3_options):
                raise ValueError('SNMPv3 credential options require --snmpv3, --snmpv3-informs, --snmpv3-traps or --snmp-link-events.')
            if args.snmp_community_file and not args.snmp:
                raise ValueError('SNMP community option requires --snmp.')
            if (args.ssh_authorized_key or args.telnet_password_hash_file or args.ssh_action is not None) and not (args.management or args.radius_ssh):
                raise ValueError('Management credentials require --management or --radius-ssh.')
            key = args.ssh_authorized_key.read_text().strip() if args.ssh_authorized_key else None
            password = args.telnet_password_hash_file.read_text().strip() if args.telnet_password_hash_file else ''
            from .examples import ntp_lab, tftp_lab, radius_lab
            if args.tftp_file and not args.tftp:
                raise ValueError('--tftp-file requires --tftp.')
            from .tftp_server import import_files
            tftp_files = import_files(args.tftp_file) if args.tftp_file else None
            radius_options = (args.radius_user, args.radius_password_file, args.radius_secret_file)
            if args.radius_shell and not args.radius:
                raise ValueError('--radius-shell requires --radius.')
            if args.radius_ssh_shell and not (args.radius and args.radius_ssh):
                raise ValueError('--radius-ssh-shell requires --radius --radius-ssh.')
            if args.radius_accounting and not (args.radius and (args.radius_shell or args.radius_ssh_shell)):
                raise ValueError('--radius-accounting requires --radius with --radius-shell or --radius-ssh-shell.')
            if args.radius_ssh and (not args.radius or not key or args.management or args.telnet_password_hash_file):
                raise ValueError('--radius-ssh requires --radius --ssh-authorized-key and no Telnet/--management profile.')
            radius_parameters = None
            if args.radius:
                if not all(radius_options):
                    raise ValueError('--radius requires --radius-user, --radius-password-file and --radius-secret-file.')
                import hashlib
                from .radius import load_credential, validate_credentials
                radius_password = load_credential(args.radius_password_file)
                radius_secret = load_credential(args.radius_secret_file)
                validate_credentials(args.radius_user, radius_password, radius_secret)
                radius_parameters = (radius_secret, hashlib.sha256(radius_password.encode()).hexdigest(), args.radius_user)
            elif any(radius_options):
                raise ValueError('RADIUS example credentials require --radius.')
            result = stp_lacp_lab(args.rootfs, args.stp_lacp_min_links or 1, True if args.stp_lacp_strict else None) if args.stp_lacp else ra_guard_dhcpv6_lab(args.rootfs) if args.ra_guard_dhcpv6 else ra_guard_lab(args.rootfs) if args.ra_guard else ipv6_firewall_lab(args.rootfs) if args.ipv6_firewall else ipv6_subinterfaces_lab(args.rootfs) if args.ipv6_subinterfaces else dhcpv6_pd_lab(args.rootfs) if args.dhcpv6_pd else dhcpv6_relay_lab(args.rootfs) if args.dhcpv6_relay else ospfv3_svi_lab(args.rootfs) if args.ospfv3_svi else ipv6_svi_lab(args.rootfs) if args.ipv6_svi else ospfv3_lab(args.rootfs) if args.ospfv3 else radius_lab(args.rootfs, *radius_parameters, allow_shell=args.radius_shell, accounting=args.radius_accounting, ssh_key=key if args.radius_ssh else None, ssh_actions=args.ssh_action, ssh_shell=args.radius_ssh_shell) if args.radius else tftp_lab(args.rootfs, files=tftp_files) if args.tftp else ntp_lab(args.rootfs) if args.ntp else snmp_links_lab(args.rootfs, user, args.snmp_link_mode or 'trap') if args.snmp_link_events else snmpv3_traps_lab(args.rootfs, user) if args.snmpv3_traps else snmpv3_informs_lab(args.rootfs, user) if args.snmpv3_informs else snmp_notifications_lab(args.rootfs, args.snmp_notification_mode or 'trap') if args.snmp_notifications else snmpv3_lab(args.rootfs, user) if args.snmpv3 else snmp_lab(args.rootfs, args.snmp_community_file.read_text().strip() if args.snmp_community_file else 'network-labs-ro') if args.snmp else syslog_lab(args.rootfs) if args.syslog else management_lab(args.rootfs, key, password, ssh_actions=args.ssh_action) if args.management else dual_stack_lab(args.rootfs) if args.dual_stack else dhcpv6_lab(args.rootfs) if args.dhcpv6 else slaac_lab(args.rootfs) if args.slaac else ipv6_routed_lab(args.rootfs) if args.ipv6_routed else ipv6_vlan_lab(args.rootfs) if args.ipv6_vlan else lan_services_lab(args.rootfs) if args.lan_services else ospf_dhcp_lldp_lab(args.rootfs) if args.ospf_dhcp_lldp else ospf_dhcp_multi_lab(args.rootfs) if args.ospf_dhcp_multi else ospf_dhcp_lab(args.rootfs) if args.ospf_dhcp else ospf_svi_lab(args.rootfs) if args.ospf_svi else ospf_broadcast_lab(args.rootfs) if args.ospf_broadcast else ospf_cli_lab(args.rootfs) if args.ospf_cli else ospf_lab(args.rootfs) if args.ospf else dhcp_multi_lab(args.rootfs) if args.dhcp_multi else dhcp_relay_lab(args.rootfs) if args.dhcp_relay else static_routing_lab(args.rootfs) if args.static_routing else svi_lab(args.rootfs) if args.svi else rstp_lab(args.rootfs) if args.rstp else lldp_lab(args.rootfs) if args.lldp else dns_lab(args.rootfs) if args.dns else dhcp_reservations_lab(args.rootfs) if args.dhcp_reservations else multicast_lab(args.rootfs) if args.multicast else source_guard_lab(args.rootfs) if args.ip_source_guard else arp_inspection_lab(args.rootfs) if args.arp_inspection else dhcp_snooping_lab(args.rootfs) if args.dhcp_snooping else port_security_lab(args.rootfs) if args.port_security else stp_lab(args.rootfs) if args.stp else lacp_lab(args.rootfs) if args.lacp else enterprise(args.rootfs) if args.enterprise else firewall_lab(args.rootfs) if args.firewall else campus(args.rootfs) if args.campus else example(args.rootfs)
        elif args.command == 'rootfs':
            result = {'rootfs': str(static_busybox_rootfs(args.busybox, args.output, dnsmasq=args.dnsmasq, lldpd=args.lldpd, lldpcli=args.lldpcli, openvswitch=args.openvswitch, bird=args.bird, birdc=args.birdc, dropbear=args.dropbear, ssh_relay=args.ssh_relay, rsyslog=args.rsyslog, rsyslog_modules=args.rsyslog_modules, snmpd=args.snmpd, snmptrapd=args.snmptrapd, chronyd=args.chronyd, chronyc=args.chronyc, freeradius=args.freeradius, freeradius_modules=args.freeradius_modules, freeradius_dictionaries=args.freeradius_dictionaries, kea_dhcp6=args.kea_dhcp6, dhcpv6_pd_hook=args.dhcpv6_pd_hook))}
        elif args.command == 'benchmark':
            from .benchmark import benchmark, summary
            if args.output and (args.output.exists() or args.output.is_symlink()):
                raise ValueError('Report already exists; choose a new --output path.')
            result = benchmark(load(args.manifest), seconds=args.seconds, sources=args.source, target=args.target)
            if args.output:
                with args.output.open('x', encoding='utf-8') as output:
                    json.dump(result, output, indent=2)
            print(json.dumps({**summary(result), 'report': str(args.output)} if args.output else result, indent=2))
            return 0 if result['assessment']['packet_test_passed'] and result['all_nodes_running_after_load'] and not result['assessment']['oom_kill_observed'] else 1
        elif args.command == 'plan':
            result = plan(load(args.manifest))
        elif args.command == 'multicast':
            from .multicast_probe import probe
            try:
                result = probe(Manager(args.name), args.node, args.interface, group=args.group, port=args.port,
                               seconds=args.seconds, count=args.count, text=args.send)
            except KeyboardInterrupt:
                return 130
        elif args.command == 'monitor':
            from .monitor import monitor, render
            try:
                result = monitor(args.name, args.node, args.interface, seconds=args.seconds,
                                 ready=lambda: print('Observation initiale terminée. Vous pouvez lancer le trafic dans un autre terminal.', file=sys.stderr, flush=True))
            except KeyboardInterrupt:
                print('Observation interrompue ; aucune différence calculée.', file=sys.stderr)
                return 130
            print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
            return 0
        elif args.command == 'capture':
            from .capture import capture
            result = capture(Manager(args.name), args.node, args.interface, args.output, seconds=args.seconds,
                             packets=args.packets, snaplen=args.snaplen, expression=args.filter,
                             ready=lambda: print(f'Capture active : {args.node}/{args.interface}. Vous pouvez lancer le trafic dans un autre terminal.', file=sys.stderr, flush=True))
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 130 if result['stop_reason'] == 'interrupted' else 0
        else:
            try:
                spec = load(args.manifest) if args.command == 'start' else None
            except FileNotFoundError as error:
                raise RuntimeFailure('Fichier manifeste introuvable. Depuis le dossier du projet, exécutez :\n  python3 -m network_labs.appliances manifests') from error
            with Manager(spec['name'] if spec else args.name).locked() as manager:
                if args.command == 'start':
                    manager.start(spec); result = manager.status()
                elif args.command == 'restore':
                    from .persistence import load_startup
                    manager.start(load_startup(args.name)); result = manager.status()
                elif args.command == 'stop':
                    manager.stop(); result = {'stopped': args.name}
                elif args.command == 'save':
                    result = manager.write_startup()
                elif args.command == 'recover':
                    manager.recover(); result = manager.status()
                elif args.command == 'show':
                    from .show import show, render
                    result = show(manager, args.node, args.text)
                    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
                    return 0 if result['status'] == 'observed' else 1
                elif args.command == 'inspect':
                    result = manager.inspect(args.node)
                elif args.command == 'verify':
                    from .verify import verify, render
                    result = verify(manager, args.source, args.destination, count=args.count, bidirectional=args.bidirectional, family=args.family)
                    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
                    return 0 if result['status'] == 'passed' else 1
                elif args.command == 'probe':
                    from .service_probe import probe, render, load_ca
                    if args.ca_file and args.protocol != 'https':
                        raise ValueError('--ca-file requires --protocol https.')
                    trust = {'ca_pem': load_ca(args.ca_file)} if args.ca_file else {}
                    result = probe(manager, args.source, args.target, protocol=args.protocol,
                                   port=args.port, path=args.path, timeout=args.timeout, **trust)
                    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
                    return 0 if result['status'] == 'passed' else 1
                elif args.command == 'radius-auth':
                    from .radius import probe, render, load_credential
                    result = probe(manager, args.source, args.server, username=args.username,
                                   password=load_credential(args.password_file), secret=load_credential(args.secret_file),
                                   timeout=args.timeout)
                    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
                    return 0 if result['status'] == 'passed' else 1
                elif args.command == 'radius-exec':
                    from .radius import load_credential
                    from .radius_exec import execute
                    result = execute(manager, args.source, args.server, action=args.action, username=args.username,
                                     password=load_credential(args.password_file), secret=load_credential(args.secret_file),
                                     timeout=args.timeout)
                    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else
                          'RADIUS execution: ' + result['status'].upper() + '\n' + result.get('stdout', ''))
                    return 0 if result['status'] == 'passed' else 1
                elif args.command == 'radius-login':
                    from .radius import load_credential
                    from .radius_login import login
                    result = login(manager, args.source, args.server, username=args.username,
                                   password=load_credential(args.password_file), secret=load_credential(args.secret_file),
                                   timeout=args.timeout, terminal=not args.no_tty and sys.stdin.isatty() and sys.stdout.isatty(),
                                   seconds=args.seconds)
                    if result['status'] != 'passed':
                        print('RADIUS login: ' + result['status'].upper() + ' ' + result.get('error', ''), file=sys.stderr)
                    return 130 if result['status'] == 'interrupted' else 124 if result['status'] == 'expired' else 0 if result['status'] == 'passed' else 1
                elif args.command == 'tftp-read':
                    from .tftp import read, render
                    result = read(manager, args.source, args.server, args.filename, timeout=args.timeout, expected_sha256=args.sha256)
                    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
                    return 0 if result['status'] == 'passed' else 1
                elif args.command == 'sntp-demo':
                    from .sntp_demo import demo, render
                    result = demo(manager, args.client, args.server, server_offset_seconds=args.server_offset_seconds, samples=args.samples)
                    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
                    return 0 if result['status'] == 'passed' else 1
                elif args.command == 'https-demo':
                    from .https_demo import demo, render
                    result = demo(manager, args.client, args.server)
                    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
                    return 0 if result['status'] == 'passed' else 1
                elif args.command == 'explain':
                    from .diagnostics import explain, render
                    result = explain(manager, args.node)
                    if not args.json:
                        print(render(result))
                        return 0
                elif args.command == 'configure':
                    text = args.file.read_text(encoding='utf-8') if args.file else args.text
                    result = manager.configure_ios(args.node, text)
                elif args.command == 'route':
                    from .route_lookup import lookup, render
                    result = lookup(manager, args.node, args.destination, source=args.source, ingress=args.ingress)
                    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
                    return 0
                elif args.command == 'multicast-policy':
                    result = manager.configure_multicast(args.node, json.loads(args.file.read_text(encoding='utf-8')))
                elif args.command == 'spanning-tree':
                    policy = json.loads(args.file.read_text(encoding='utf-8')) if args.file else None
                    result = manager.configure_spanning_tree(args.node, policy, priority=args.priority)
                elif args.command == 'firewall':
                    result = manager.configure_firewall(args.node, json.loads(args.file.read_text(encoding='utf-8')))
                elif args.command in ('sessions', 'clear-sessions'):
                    result = manager.sessions(args.node, clear=args.command == 'clear-sessions')
                elif args.command == 'export':
                    if args.startup:
                        from .persistence import load_startup
                        result = load_startup(args.name)
                    else:
                        from .persistence import drift
                        differences = drift(manager)
                        if differences:
                            raise RuntimeFailure('Unmanaged kernel changes detected: ' + '; '.join(differences))
                        result = manager.read()['spec']
                elif args.command == 'exec':
                    command = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
                    return manager.execute(args.node, command, tty=args.tty)
                else:
                    result = manager.status()
        if args.command not in ('example', 'export'):
            from .radius_server import redact
            result = redact(result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (RuntimeFailure, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print('Native lab: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
