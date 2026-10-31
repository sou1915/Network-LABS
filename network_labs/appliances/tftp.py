"""Read-only, size-bounded TFTP transfer from a managed node."""
from datetime import datetime, timezone
import hmac
import json
from pathlib import Path
import re
import subprocess
import sys

from .runtime import RuntimeFailure
from .service_probe import unicast
from .spec import integer
from .verify import _endpoint
from .route_lookup import _json_read


def read(manager, source, address, filename, *, timeout=5, expected_sha256=None):
    integer(timeout, 1, 10, 'TFTP deadline seconds')
    if not isinstance(address, str): raise ValueError('TFTP requires a literal IPv4 server address.')
    address = unicast(address)
    if not isinstance(filename, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', filename) or filename in ('.', '..'):
        raise ValueError('Use a single ASCII filename without directories, 1..128 characters.')
    if expected_sha256 is not None and (not isinstance(expected_sha256, str) or not re.fullmatch(r'[0-9A-Fa-f]{64}', expected_sha256)):
        raise ValueError('Expected SHA-256 must contain 64 hexadecimal characters.')
    state = manager.read()
    if state['phase'] != 'running' or 'pending_spec' in state or 'pending_node' in state:
        raise RuntimeFailure('TFTP requires a running lab without pending configuration.')
    match = next(((i, n) for i, n in enumerate(state['spec']['nodes']) if n['name'] == source), None)
    if match is None or match[1]['runtime'] != 'oci' or match[1]['role'] != 'host' or set(match[1]['interfaces']) != {'eth0'} or match[1].get('subinterfaces') or match[1].get('port_channels'):
        raise ValueError('TFTP requires a managed single-interface OCI host.')
    index, node = match; endpoint = _endpoint(manager, index, node)
    report = {'lab': manager.name, 'node': source, 'server': address, 'filename': filename, 'port': 69,
              'endpoint': endpoint, 'status': endpoint['status'], 'transfer': None, 'hash_matches': None,
              'started_at': datetime.now(timezone.utc).isoformat(), 'configuration_changed': False,
              'scope': 'One unauthenticated IPv4 TFTP octet read, at most 65536 bytes and 256 received datagrams including final ACK dally. At most three timeout retransmissions per block with exponential backoff within the overall deadline. Identical final DATA may be acknowledged again for up to one second within the same deadline. Passed means content received locally and initial final ACK sent, not confirmed server receipt. No file is saved, no writes, option negotiation, IPv6 or DNS. A failed transfer does not establish its cause.'}
    def finish(status):
        report.update(status=status, finished_at=datetime.now(timezone.utc).isoformat())
        return report
    if endpoint['status'] != 'ready': return finish(endpoint['status'])
    route = _json_read(manager, index, 'ip', '-j', '-4', 'route', 'get', address)
    report['route'] = route
    if address == endpoint['address'] or any(row.get('type') in ('local', 'broadcast', 'multicast') or row.get('dev') == 'lo' for row in route['records'] or []):
        report['error'] = 'A remote target is required.'
        return finish('blocked')
    request = {'source': endpoint['address'], 'address': address, 'filename': filename, 'timeout': timeout, 'port': 69}
    worker = Path(__file__).with_name('tftp_worker.py').read_text()
    try:
        process = manager.ns(index, sys.executable, '-I', '-c', worker, json.dumps(request), check=False, timeout=timeout + 2)
        result = json.loads(process.stdout)
        if process.returncode or not isinstance(result, dict) or result.get('status') not in ('passed', 'failed', 'unknown'):
            raise ValueError('TFTP worker output unavailable.')
        if result['status'] == 'passed' and (type(result.get('bytes_received')) is not int or not 0 <= result['bytes_received'] <= 65536 or
                                              not isinstance(result.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', result['sha256'])):
            raise ValueError('Completed TFTP result lacks valid length or SHA-256.')
    except (OSError, RuntimeFailure, ValueError, subprocess.TimeoutExpired) as error:
        report['error'] = str(error)[:300]
        return finish('unknown')
    report['transfer'] = result
    if result['status'] == 'passed' and expected_sha256 is not None:
        actual = result.get('sha256')
        if not isinstance(actual, str) or not re.fullmatch(r'[0-9a-f]{64}', actual):
            report['error'] = 'Completed transfer lacks a valid SHA-256.'
            return finish('unknown')
        report['hash_matches'] = hmac.compare_digest(actual, expected_sha256.lower())
        if not report['hash_matches']: return finish('failed')
    return finish(result['status'])


def render(report):
    lines = ['TFTP lecture : ' + report['status'].upper() + ' | ' + report['node'] + ' → ' + report['server'],
             'Fichier : ' + json.dumps(report['filename'], ensure_ascii=True)]
    transfer = report.get('transfer')
    if transfer:
        lines.append('Octets reçus : ' + str(transfer.get('bytes_received', 0)))
        if 'retransmissions' in transfer: lines.append('Retransmissions : ' + str(transfer['retransmissions']))
        if transfer.get('final_ack'):
            lines.append('Dernier ACK : ' + str(transfer['final_ack']['duplicate_acks']) +
                         ' confirmation(s) répétée(s) ; ' + transfer['final_ack']['status'])
        if transfer.get('sha256'): lines.append('SHA-256 : ' + transfer['sha256'])
        if transfer.get('error'): lines.append('Erreur : ' + json.dumps(transfer['error'], ensure_ascii=True))
        if transfer.get('error_code') is not None: lines.append('Code TFTP : ' + str(transfer['error_code']))
    if report['hash_matches'] is not None: lines.append('SHA-256 attendu : ' + ('correspond' if report['hash_matches'] else 'différent'))
    if report.get('error'): lines.append('Détail : ' + json.dumps(report['error'], ensure_ascii=True))
    lines.append('Lecture non authentifiée ; aucun fichier sauvegardé. Un échec ne précise pas sa cause.')
    return '\n'.join(lines)
