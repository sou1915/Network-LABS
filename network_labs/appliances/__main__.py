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
    sample = commands.add_parser('example', help='Print a three-node OCI manifest; no host changes.')
    sample.add_argument('--rootfs', type=Path, required=True)
    sample.add_argument('--ipv6-vlan', action='store_true', help='Six-node static IPv6 VLAN/trunk LAN; no routing or RA.')
    sample.add_argument('--lan-services', action='store_true', help='Eight-node routed DHCP/DNS/HTTP LAN with OSPF and physical LLDP.')
    sample.add_argument('--ospf-dhcp-lldp', action='store_true', help='Physical LLDP discovery on the two-VLAN OSPF/DHCP infrastructure, including its trunk.')
    sample.add_argument('--ospf-dhcp-multi', action='store_true', help='Two DHCP client VLANs and OSPF on one L3 switch, with independent helpers and remote pools.')
    sample.add_argument('--ospf-dhcp', action='store_true', help='Real OSPF and DHCP relay together on one L3 switch, with a remote-pool server.')
    sample.add_argument('--ospf-svi', action='store_true', help='Real OSPF on a Linux L3 switch SVI, VLAN trunk and router.')
    sample.add_argument('--ospf-broadcast', action='store_true', help='Four real BIRD routers on a shared Ethernet LAN with DR/BDR election.')
    sample.add_argument('--ospf-cli', action='store_true', help='Numbered OSPF triangle without routing daemons; configure all three processes through the CLI.')
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
    sample.add_argument('--lacp', action='store_true', help='Six-node VLAN LAN with a negotiated two-link LACP trunk.')
    sample.add_argument('--enterprise', action='store_true', help='20-node LAN with router, firewall, DHCP and WAN.')
    sample.add_argument('--firewall', action='store_true', help='Three-node stateful firewall and NAT reference lab.')
    sample.add_argument('--campus', action='store_true', help='Eight-node VLAN/trunk/router/DHCP reference LAN.')
    rootfs = commands.add_parser('rootfs', help='Build an offline minimal rootfs from trusted static BusyBox.')
    rootfs.add_argument('--busybox', type=Path, required=True)
    rootfs.add_argument('--openvswitch', action='store_true', help='Copy trusted installed OVS executables, ELF libraries and schema.')
    rootfs.add_argument('--lldpd', type=Path, help='Trusted Debian/Ubuntu lldpd executable, paired with --lldpcli.')
    rootfs.add_argument('--lldpcli', type=Path, help='Trusted matching lldpcli executable.')
    rootfs.add_argument('--bird', type=Path, help='Trusted BIRD 2 daemon ELF for OSPF.')
    rootfs.add_argument('--birdc', type=Path, help='Trusted BIRD 2 control-client ELF.')
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
    verify.add_argument('--count', type=int, default=3)
    verify.add_argument('--bidirectional', action='store_true')
    verify.add_argument('--json', action='store_true')
    service = commands.add_parser('probe', help='Bounded DNS A, TCP connect and HTTP HEAD from an OCI host.')
    service.add_argument('name'); service.add_argument('source'); service.add_argument('target')
    service.add_argument('--protocol', choices=('dns', 'tcp', 'http'), default='http')
    service.add_argument('--port', type=int)
    service.add_argument('--path', default='/')
    service.add_argument('--timeout', type=int, default=3, help='Deadline per wire stage, 1..5 seconds.')
    service.add_argument('--json', action='store_true')
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
        elif args.command == 'example':
            from .examples import campus, firewall_lab, enterprise, lacp_lab, stp_lab, port_security_lab, dhcp_snooping_lab, arp_inspection_lab, source_guard_lab, multicast_lab, dhcp_reservations_lab, dns_lab, lldp_lab, rstp_lab, svi_lab, static_routing_lab, dhcp_relay_lab, dhcp_multi_lab, ospf_lab, ospf_cli_lab, ospf_broadcast_lab, ospf_svi_lab, ospf_dhcp_lab, ospf_dhcp_multi_lab, ospf_dhcp_lldp_lab, lan_services_lab, ipv6_vlan_lab
            if sum((args.ipv6_vlan, args.lan_services, args.ospf_dhcp_lldp, args.campus, args.firewall, args.enterprise, args.lacp, args.stp, args.port_security, args.dhcp_snooping, args.arp_inspection, args.ip_source_guard, args.multicast, args.dhcp_reservations, args.dns, args.lldp, args.rstp, args.svi, args.static_routing, args.dhcp_relay, args.dhcp_multi, args.ospf, args.ospf_cli, args.ospf_broadcast, args.ospf_svi, args.ospf_dhcp, args.ospf_dhcp_multi)) > 1:
                raise ValueError('Choose only one reference scenario.')
            result = ipv6_vlan_lab(args.rootfs) if args.ipv6_vlan else lan_services_lab(args.rootfs) if args.lan_services else ospf_dhcp_lldp_lab(args.rootfs) if args.ospf_dhcp_lldp else ospf_dhcp_multi_lab(args.rootfs) if args.ospf_dhcp_multi else ospf_dhcp_lab(args.rootfs) if args.ospf_dhcp else ospf_svi_lab(args.rootfs) if args.ospf_svi else ospf_broadcast_lab(args.rootfs) if args.ospf_broadcast else ospf_cli_lab(args.rootfs) if args.ospf_cli else ospf_lab(args.rootfs) if args.ospf else dhcp_multi_lab(args.rootfs) if args.dhcp_multi else dhcp_relay_lab(args.rootfs) if args.dhcp_relay else static_routing_lab(args.rootfs) if args.static_routing else svi_lab(args.rootfs) if args.svi else rstp_lab(args.rootfs) if args.rstp else lldp_lab(args.rootfs) if args.lldp else dns_lab(args.rootfs) if args.dns else dhcp_reservations_lab(args.rootfs) if args.dhcp_reservations else multicast_lab(args.rootfs) if args.multicast else source_guard_lab(args.rootfs) if args.ip_source_guard else arp_inspection_lab(args.rootfs) if args.arp_inspection else dhcp_snooping_lab(args.rootfs) if args.dhcp_snooping else port_security_lab(args.rootfs) if args.port_security else stp_lab(args.rootfs) if args.stp else lacp_lab(args.rootfs) if args.lacp else enterprise(args.rootfs) if args.enterprise else firewall_lab(args.rootfs) if args.firewall else campus(args.rootfs) if args.campus else example(args.rootfs)
        elif args.command == 'rootfs':
            result = {'rootfs': str(static_busybox_rootfs(args.busybox, args.output, dnsmasq=args.dnsmasq, lldpd=args.lldpd, lldpcli=args.lldpcli, openvswitch=args.openvswitch, bird=args.bird, birdc=args.birdc))}
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
            spec = load(args.manifest) if args.command == 'start' else None
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
                    result = verify(manager, args.source, args.destination, count=args.count, bidirectional=args.bidirectional)
                    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
                    return 0 if result['status'] == 'passed' else 1
                elif args.command == 'probe':
                    from .service_probe import probe, render
                    result = probe(manager, args.source, args.target, protocol=args.protocol,
                                   port=args.port, path=args.path, timeout=args.timeout)
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
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (RuntimeFailure, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print('Native lab: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
