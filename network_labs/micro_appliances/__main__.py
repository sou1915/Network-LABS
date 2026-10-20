"""Run optional experiments without modifying host interfaces or the normal lab."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from .experiment import functional_demo,benchmark_worker,isolation_demo
from .runtime import DependencyMissing


def main():
    parser=argparse.ArgumentParser(description='Experimental Wasm micro-appliances: no Windows/Linux guest OS, no host-network access.')
    commands=parser.add_subparsers(dest='command',required=True)
    demo=commands.add_parser('demo');demo.add_argument('--json',type=Path);demo.add_argument('--pcap',type=Path)
    commands.add_parser('isolation')
    benchmark=commands.add_parser('benchmark');benchmark.add_argument('--sizes',nargs='+',type=int,default=[10,50,100]);benchmark.add_argument('--json',type=Path)
    worker=commands.add_parser('_benchmark-worker');worker.add_argument('--hosts',type=int,required=True)
    args=parser.parse_args()
    try:
        if args.command=='demo':
            fabric,report=functional_demo()
            if args.pcap:fabric.write_pcap(args.pcap)
            fabric.close()
            if args.json:args.json.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
            print('3 instances Wasm indépendantes · aucun OS invité')
            for name,ok in [('ARP / ICMP echo',report['ping']['ok']),('TCP handshake',report['tcp_handshake_observed']),('TCP echo payload',report['tcp_echo_ok']),('Packet checksums',report['packet_checksums_ok'])]:
                print(name+': '+('OK' if ok else 'FAILED'))
            for node in report['runtime']['nodes']:
                print(f"{node['name']} : {node['linear_memory_bytes']//1024} Kio mémoire linéaire, RX {node['rx_frames']}, TX {node['tx_frames']}")
            rss=report['process_memory'].get('rss_bytes')
            if rss:print(f'RSS du processus entier, hors GUI : {rss/1048576:.2f} Mio')
            if args.pcap:print('PCAP:',args.pcap)
            if args.json:print('Rapport:',args.json)
            return 0 if report['ok'] else 1
        if args.command=='isolation':
            report=isolation_demo();print(json.dumps(report,indent=2));return 0 if report['ok'] else 1
        if args.command=='_benchmark-worker':
            if not 2<=args.hosts<=254:parser.error('2..254 endpoints required.')
            report=benchmark_worker(args.hosts);print(json.dumps(report));return 0 if report['ok'] else 1
        reports=[]
        for hosts in args.sizes:
            if not 2<=hosts<=254:parser.error('2..254 endpoints required.')
            process=subprocess.run([sys.executable,'-m','network_labs.micro_appliances','_benchmark-worker','--hosts',str(hosts)],capture_output=True,text=True,timeout=90)
            if process.returncode:
                raise RuntimeError(process.stderr.strip() or process.stdout.strip())
            row=json.loads(process.stdout);reports.append(row)
            memory=row['memory_after_traffic'].get('rss_bytes',0)/1048576
            print(f"{hosts} PC + 1 switch | RSS processus {memory:.2f} MiB | mémoire linéaire {row['runtime']['linear_memory_bytes']/1048576:.2f} MiB | {row['ping_success']}/{row['ping_total']} ping | TCP {'OK' if row['tcp_echo_ok'] else 'FAILED'} | CPU trafic {row['traffic_cpu_seconds']:.3f}s")
        result={'note':'Fresh subprocess per size. All figures are measured in the execution environment, not the user laptop. Guest linear memory is not total process RAM; idle CPU is measured while the virtual clock is paused.','runs':reports}
        if args.json:args.json.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
        return 0
    except (DependencyMissing,OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as error:
        print(str(error),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
