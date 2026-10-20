"""Bounded headless benchmark: owned OCI lab, idle/load sampling, always cleanup.

Cgroup attribution is not a measurement of total application memory. Host deltas
include unrelated activity; no total-application 2 GiB certification is inferred.
"""
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import resource
import signal
import subprocess
import time

from .lan import addresses
from .runtime import Manager, RuntimeFailure
from .spec import MIB, integer, prefix, validate

CGROUP_ROOT = Path('/sys/fs/cgroup/network-labs')
PROC_ROOT = Path('/proc')


def key_values(path):
    return {parts[0]: int(parts[1]) for line in path.read_text().splitlines() if (parts := line.split())}


def host_snapshot():
    memory = key_values(PROC_ROOT / 'meminfo')
    ticks = [int(v) for v in (PROC_ROOT / 'stat').read_text().splitlines()[0].split()[1:9]]
    return {'memory_total_bytes': memory['MemTotal:'] * 1024,
            'memory_available_bytes': memory['MemAvailable:'] * 1024,
            'swap_used_bytes': (memory['SwapTotal:'] - memory['SwapFree:']) * 1024,
            'cpu_ticks_total': sum(ticks), 'cpu_ticks_busy': sum(ticks) - ticks[3] - ticks[4]}


def group_snapshot(path):
    cpu = key_values(path / 'cpu.stat')
    return {'memory_bytes': int((path / 'memory.current').read_text()),
            'swap_bytes': int((path / 'memory.swap.current').read_text()),
            'cpu_usage_usec': cpu['usage_usec'],
            'memory_events': key_values(path / 'memory.events')}


def sample(manager):
    usage = resource.getrusage(resource.RUSAGE_SELF)
    try:
        pss = next(int(line.split()[1]) * 1024 for line in (PROC_ROOT / 'self' / 'smaps_rollup').read_text().splitlines() if line.startswith('Pss:'))
    except (OSError, KeyError, ValueError, StopIteration):
        pss = None
    return {'time': time.monotonic(), 'lab_cgroup': group_snapshot(CGROUP_ROOT / prefix(manager.state['spec'])),
            'runner_pss_bytes': pss, 'runner_cpu_seconds': usage.ru_utime + usage.ru_stime,
            'host': host_snapshot()}


def summarize(samples):
    first, last = samples[0], samples[-1]
    seconds = last['time'] - first['time']
    if seconds <= 0:
        raise ValueError('Measurement needs a positive time interval.')
    total_ticks = last['host']['cpu_ticks_total'] - first['host']['cpu_ticks_total']
    memory = [s['lab_cgroup']['memory_bytes'] for s in samples]
    return {'duration_seconds': seconds, 'samples': len(samples),
            'lab_cgroup_memory_mean_bytes': sum(memory) / len(memory),
            'lab_cgroup_memory_sampled_peak_bytes': max(memory),
            'lab_cgroup_swap_sampled_peak_bytes': max(s['lab_cgroup']['swap_bytes'] for s in samples),
            'lab_cgroup_cpu_percent_one_core': 100 * (last['lab_cgroup']['cpu_usage_usec'] - first['lab_cgroup']['cpu_usage_usec']) / (seconds * 1e6),
            'runner_cpu_percent_one_core': 100 * (last['runner_cpu_seconds'] - first['runner_cpu_seconds']) / seconds,
            'runner_pss_sampled_peak_bytes': max((s['runner_pss_bytes'] for s in samples if s['runner_pss_bytes'] is not None), default=None),
            'host_busy_percent_total_capacity': 100 * (last['host']['cpu_ticks_busy'] - first['host']['cpu_ticks_busy']) / total_ticks if total_ticks else None,
            'host_available_min_bytes': min(s['host']['memory_available_bytes'] for s in samples),
            'lab_memory_event_deltas': {k: last['lab_cgroup']['memory_events'].get(k, 0) - v
                                        for k, v in first['lab_cgroup']['memory_events'].items()}}


def measure(manager, seconds, interval=0.2):
    start = time.monotonic()
    samples = [sample(manager)]
    while (remaining := seconds - (time.monotonic() - start)) > 0:
        time.sleep(min(interval, remaining))
        samples.append(sample(manager))
    return summarize(samples)


def wait_ready(manager, timeout=15):
    pending = [n for n in manager.state['spec']['nodes'] if n['dhcp_clients']]
    deadline = time.monotonic() + timeout
    while pending:
        remaining = []
        for node in pending:
            actual = manager.inspect(node['name'])
            ready = all(any(item['ifname'] == interface and any(a.get('scope') == 'global' for a in item.get('addr_info', []))
                            for item in actual['addresses']) for interface in node['dhcp_clients'])
            ready = ready and any(r.get('dst') == 'default' and r.get('gateway') for r in actual['routes'])
            if not ready:
                remaining.append(node)
        pending = remaining
        if pending:
            if time.monotonic() >= deadline:
                raise RuntimeFailure('DHCP readiness timed out: ' + ', '.join(n['name'] for n in pending))
            time.sleep(0.1)
    status = manager.status()
    if any(n['state'].get('status') != 'running' for n in status['nodes']):
        raise RuntimeFailure('Not all OCI nodes are running.')


def stop_children(children):
    for _, process, _ in children:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)


def workload(manager, sources, target, seconds):
    children = []
    results = []
    try:
        for source in sources:
            log = manager.directory / (source + '-benchmark.log')
            with log.open('w') as output:
                process = subprocess.Popen(['crun', '--root', str(manager.directory / 'crun'), 'exec', source,
                                            '/bin/ping', '-n', '-i', '0.1', '-c', str(seconds * 10), '-W', '1', target],
                                           stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                           start_new_session=True)
            children.append((source, process, log))
        metrics = measure(manager, seconds)
        for source, process, log in children:
            process.wait(timeout=3)
            text = log.read_text(errors='replace')
            packets = re.search(r'(\d+) packets transmitted, (\d+) packets received', text)
            results.append({'source': source, 'returncode': process.returncode,
                            'transmitted': int(packets[1]) if packets else None,
                            'received': int(packets[2]) if packets else None,
                            'output': text[-1500:]})
        passed = all(r['returncode'] == 0 and r['transmitted'] == r['received'] == seconds * 10 for r in results)
        return {'metrics': metrics, 'flows': results, 'all_packets_received': passed,
                'protocol': 'icmp', 'target': target, 'requested_packets_per_source': seconds * 10,
                'requested_packets_per_second_per_source': 10, 'note': 'Bounded connectivity workload, not maximum-throughput or application-load testing.'}
    finally:
        stop_children(children)


def benchmark(data, *, seconds=5, sources=None, target):
    spec = validate(data)
    integer(seconds, 1, 30, 'seconds per phase')
    if any(n['runtime'] != 'oci' for n in spec['nodes']):
        raise ValueError('This benchmark supports OCI-only labs, not VM guests.')
    target = str(ipaddress.IPv4Address(target))
    if not any(a and str(ipaddress.IPv4Interface(a).ip) == target for n in spec['nodes'] for a in addresses(n).values()):
        raise ValueError('Benchmark target must be a statically configured address inside this lab.')
    sources = sources if sources is not None else [n['name'] for n in spec['nodes'] if n['name'].startswith('PC') and n['role'] == 'host']
    hosts = {n['name'] for n in spec['nodes'] if n['role'] == 'host'}
    if not sources or len(sources) > 16 or len(set(sources)) != len(sources) or set(sources) - hosts:
        raise ValueError('Choose 1..16 distinct OCI host sources; default selects PC-prefixed hosts.')
    report = {'version': 1, 'lab': spec['name'], 'node_count': len(spec['nodes']),
              'environment': {'kernel': platform.release(), 'machine': platform.machine(), 'logical_cpus': os.cpu_count()},
              'allocated_node_mib': sum(n['memory_mib'] for n in spec['nodes']),
              'reserve_mib': spec['reserve_mib'], 'host_before': host_snapshot()}
    with Manager(spec['name']).locked() as manager:
        if manager.directory.exists():
            raise RuntimeFailure('Benchmark needs a stopped lab; existing lab will not be adopted or stopped.')
        started = time.monotonic()
        try:
            manager.start(spec)
            wait_ready(manager)
            report['startup_and_readiness_seconds'] = time.monotonic() - started
            report['idle'] = measure(manager, seconds)
            report['load'] = workload(manager, sources, target, seconds)
            status = manager.status()
            report['all_nodes_running_after_load'] = all(n['state'].get('status') == 'running' for n in status['nodes'])
            report['nodes_after_load'] = {n['name']: group_snapshot(CGROUP_ROOT / prefix(spec) / n['name']) for n in spec['nodes']}
        finally:
            if manager.directory.exists():
                manager.stop()
        report['cleanup_complete'] = not manager.directory.exists()
    report['host_after'] = host_snapshot()
    peaks = [report['idle']['lab_cgroup_memory_sampled_peak_bytes'], report['load']['metrics']['lab_cgroup_memory_sampled_peak_bytes']]
    report['host_used_increase_at_sampled_available_min_bytes'] = report['host_before']['memory_available_bytes'] - min(report['idle']['host_available_min_bytes'], report['load']['metrics']['host_available_min_bytes'])
    report['assessment'] = {'target_bytes': spec['budget_mib'] * MIB,
                            'lab_cgroup_sampled_peak_under_target': max(peaks) < spec['budget_mib'] * MIB,
                            'total_application_under_target': 'unverified',
                            'packet_test_passed': report['load']['all_packets_received'],
                            'oom_kill_observed': any(n['memory_events'].get('oom_kill', 0) for n in report['nodes_after_load'].values()),
                            'notes': ['Lab parent cgroup includes descendants; do not add per-node memory again.',
                                      'Sampled peaks exclude startup spikes and may miss peaks between samples.',
                                      'Runner PSS is separate; shared pages mean it must not be blindly added to cgroup memory.',
                                      'Host readings include unrelated programs, caches, kernel/network work and measurement overhead.',
                                      'Cgroup CPU is task attribution; networking work can run outside these cgroups.',
                                      'Final GUI, vendor firmware, VMs and heavy services are not covered. No total-app 2 GiB claim.']}
    return report


def summary(report):
    def phase(metrics):
        pss = metrics['runner_pss_sampled_peak_bytes']
        return {'lab_cgroup_memory_sampled_peak_mib': round(metrics['lab_cgroup_memory_sampled_peak_bytes'] / MIB, 3),
                'lab_cgroup_cpu_percent_one_core': round(metrics['lab_cgroup_cpu_percent_one_core'], 3),
                'runner_pss_sampled_peak_mib': round(pss / MIB, 3) if pss is not None else None,
                'host_busy_percent_total_capacity': metrics['host_busy_percent_total_capacity']}
    return {'lab': report['lab'], 'node_count': report['node_count'],
            'startup_and_readiness_seconds': round(report['startup_and_readiness_seconds'], 3),
            'idle': phase(report['idle']), 'load': phase(report['load']['metrics']),
            'traffic': {'sources': len(report['load']['flows']), 'protocol': report['load']['protocol'],
                        'packets_per_source': report['load']['requested_packets_per_source'],
                        'all_packets_received': report['load']['all_packets_received']},
            'all_nodes_running_after_load': report['all_nodes_running_after_load'],
            'cleanup_complete': report['cleanup_complete'], 'assessment': report['assessment']}
