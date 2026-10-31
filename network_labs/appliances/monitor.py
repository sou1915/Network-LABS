"""Two bounded passive samples; rates are unknown across detected epoch changes."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time

from .interface_stats import FIELDS, decode, managed_ports
from .runtime import Manager, RuntimeFailure, process_identity
from .spec import integer, namespace

NETNS_ROOT = Path('/run/netns')
RATES = ('rx_packets_per_second', 'tx_packets_per_second', 'rx_bits_per_second', 'tx_bits_per_second')


def _sample(lab, name):
    # Always a fresh Manager: stop/restore may replace state between samples.
    with Manager(lab).locked() as manager:
        state = manager.read()
        if state['phase'] != 'running':
            raise RuntimeFailure('Lab must be running for observation.')
        match = next(((i, n) for i, n in enumerate(state['spec']['nodes']) if n['name'] == name), None)
        if match is None or match[1]['runtime'] != 'oci':
            raise ValueError('Monitoring requires an existing OCI node.')
        index, node = match
        result = manager.crun('state', name, check=False)
        status = json.loads(result.stdout) if result.returncode == 0 else {}
        pid = status.get('pid')
        if status.get('status') != 'running' or type(pid) is not int or pid <= 0:
            raise RuntimeFailure('Node container is not confirmed running.')
        starttime = process_identity(pid)
        if starttime is None:
            raise RuntimeFailure('Container process identity unavailable.')
        ns = os.stat(NETNS_ROOT / namespace(state['spec'], index))
        began = time.monotonic_ns()
        links = json.loads(manager.ns(index, 'ip', '-j', '-s', '-d', 'link', 'show').stdout)
        ended = time.monotonic_ns()
        byname = {r['ifname']: r for r in links}
        ports = {}
        for port in sorted(managed_ports(node)):
            link = byname.get(port)
            ports[port] = None if link is None else {
                **decode(link), 'address': link.get('address'), 'link_type': link.get('link_type'),
                'kind': link.get('linkinfo', {}).get('info_kind'), 'flags': link.get('flags', [])}
        return {'observed_at': datetime.now(timezone.utc).isoformat(), 'monotonic_ns': (began + ended) // 2,
                'read_duration_seconds': (ended - began) / 1e9, 'revision': state.get('revision', 0),
                'generation': {'netns_device': ns.st_dev, 'netns_inode': ns.st_ino, 'pid': pid, 'process_starttime': starttime},
                'ports': ports}


def compare(before, after, names):
    elapsed = (after['monotonic_ns'] - before['monotonic_ns']) / 1e9 if after else None
    rows = []
    for name in names:
        a, b = before['ports'].get(name), after['ports'].get(name) if after else None
        row = {'port': name, 'status': 'unknown', 'reason': '', 'before': a, 'after': b,
               'delta': {f: None for f in FIELDS}, 'rates': {f: None for f in RATES}}
        rows.append(row)
        if after is None:
            row.update(status='observation_unavailable', reason='Seconde observation indisponible.')
        elif not a or not b:
            row.update(status='interface_unavailable', reason='Interface absente dans au moins un relevé ; aucune différence calculée.')
        elif not before.get('generation') or before['generation'] != after.get('generation'):
            row.update(status='generation_changed', reason='Identité du conteneur/namespace modifiée ou inconnue.')
        elif type(a.get('ifindex')) is not int or a['ifindex'] <= 0 or type(b.get('ifindex')) is not int or b['ifindex'] <= 0:
            row.update(status='identity_unavailable', reason='Identité de l’interface indisponible.')
        elif any(a.get(k) != b.get(k) for k in ('ifindex', 'address', 'link_type', 'kind')):
            row.update(status='identity_changed', reason='Identité de l’interface modifiée ; recréation ou changement possible.')
        elif a.get('width_bits') not in (32, 64) or a.get('width_bits') != b.get('width_bits'):
            row.update(status='counter_source_changed', reason='Source/largeur des compteurs modifiée ou indisponible.')
        elif elapsed is None or elapsed <= 0:
            row.update(status='time_unavailable', reason='Intervalle monotone non positif.')
        else:
            comparable = {f: (a['counters'].get(f), b['counters'].get(f)) for f in FIELDS}
            decreased = [f for f, (x, y) in comparable.items() if x is not None and y is not None and y < x]
            if decreased:
                row.update(status='counter_decreased', reason='Compteurs diminués : ' + ', '.join(decreased) + '. Reset/wrap possible ; aucune correction modulo supposée.')
                continue
            row['delta'] = {f: y - x if x is not None and y is not None else None for f, (x, y) in comparable.items()}
            for direction in ('rx', 'tx'):
                packets, octets = row['delta'][direction + '_packets'], row['delta'][direction + '_bytes']
                row['rates'][direction + '_packets_per_second'] = packets / elapsed if packets is not None else None
                row['rates'][direction + '_bits_per_second'] = octets * 8 / elapsed if octets is not None else None
            row.update(status='measured' if all(v is not None for v in row['delta'].values()) else 'partial',
                       reason='Différence de compteurs sur deux relevés ; ne certifie pas la livraison des paquets.')
    return elapsed, rows


def monitor(lab, node, interface=None, *, seconds=5, ready=None):
    integer(seconds, 1, 30, 'Monitoring seconds')
    before = _sample(lab, node)
    if interface is not None and interface not in before['ports']:
        raise ValueError('Interface must be a managed port of this node.')
    if ready:
        ready()
    # No lab lock or cached Manager survives this wait.
    time.sleep(seconds)
    error = None
    try:
        after = _sample(lab, node)
    except (RuntimeFailure, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        after = None; error = str(exc)
    names = [interface] if interface is not None else sorted(set(before['ports']) | (set(after['ports']) if after else set()))
    elapsed, rows = compare(before, after, names)
    return {'version': 1, 'lab': lab, 'node': node, 'interface': interface, 'passive': True, 'packet_delivery': 'not_tested',
            'requested_wait_seconds': seconds, 'elapsed_seconds': elapsed, 'before': before, 'after': after,
            'second_observation_available': after is not None, 'observation_error': error, 'ports': rows,
            'note': 'Approximate interface rates from two sequential snapshots; no packet probes, loss percentage, application throughput or aggregate bond/member total.'}


def render(report):
    elapsed = f"{report['elapsed_seconds']:.3f} s" if report['elapsed_seconds'] is not None else '?'
    lines = [f"Lab {report['lab']} | node {report['node']} | intervalle observé : {elapsed}",
             'Moyennes passives par interface, sans somme entre bond et membres.']
    display = lambda x: '?' if x is None else f'{x:.2f}'
    for row in report['ports']:
        rates = row['rates']
        lines.append(f"{row['port']} [{row['status']}] RX {display(rates['rx_packets_per_second'])} pkt/s, {display(rates['rx_bits_per_second'])} bit/s | TX {display(rates['tx_packets_per_second'])} pkt/s, {display(rates['tx_bits_per_second'])} bit/s")
        lines.append('  ' + row['reason'])
        changes = {k: v for k, v in row['delta'].items() if k.endswith(('_errors', '_dropped')) and v is not None and v > 0}
        if changes:
            lines.append('  Hausse erreurs/drops : ' + ', '.join(f'{k}=+{v}' for k, v in changes.items()) + ' ; cause et flux non déterminés.')
    if report['observation_error']:
        lines.append('Seconde lecture impossible : ' + report['observation_error'])
    lines.append('Deux relevés ne détectent pas tous les resets/recréations ; aucune livraison ou absence de perte certifiée.')
    return '\n'.join(lines)
