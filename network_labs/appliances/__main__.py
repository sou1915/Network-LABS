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
    inspect = commands.add_parser('inspect', help='Read actual kernel interfaces/routes/VLAN/FDB state.')
    inspect.add_argument('name'); inspect.add_argument('node')
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
            from .examples import campus, firewall_lab, enterprise, lacp_lab, stp_lab, port_security_lab, dhcp_snooping_lab, arp_inspection_lab, source_guard_lab, multicast_lab, dhcp_reservations_lab, dns_lab
            if sum((args.campus, args.firewall, args.enterprise, args.lacp, args.stp, args.port_security, args.dhcp_snooping, args.arp_inspection, args.ip_source_guard, args.multicast, args.dhcp_reservations, args.dns)) > 1:
                raise ValueError('Choose only one reference scenario.')
            result = dns_lab(args.rootfs) if args.dns else dhcp_reservations_lab(args.rootfs) if args.dhcp_reservations else multicast_lab(args.rootfs) if args.multicast else source_guard_lab(args.rootfs) if args.ip_source_guard else arp_inspection_lab(args.rootfs) if args.arp_inspection else dhcp_snooping_lab(args.rootfs) if args.dhcp_snooping else port_security_lab(args.rootfs) if args.port_security else stp_lab(args.rootfs) if args.stp else lacp_lab(args.rootfs) if args.lacp else enterprise(args.rootfs) if args.enterprise else firewall_lab(args.rootfs) if args.firewall else campus(args.rootfs) if args.campus else example(args.rootfs)
        elif args.command == 'rootfs':
            result = {'rootfs': str(static_busybox_rootfs(args.busybox, args.output, dnsmasq=args.dnsmasq))}
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
                elif args.command == 'inspect':
                    result = manager.inspect(args.node)
                elif args.command == 'explain':
                    from .diagnostics import explain, render
                    result = explain(manager, args.node)
                    if not args.json:
                        print(render(result))
                        return 0
                elif args.command == 'configure':
                    text = args.file.read_text(encoding='utf-8') if args.file else args.text
                    result = manager.configure_ios(args.node, text)
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
