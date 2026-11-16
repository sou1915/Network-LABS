"""List recorded native lab state without claiming live resource health."""
import json
import os

from . import runtime
from .runtime import RuntimeFailure
from .spec import identifier


def list_labs():
    if os.geteuid() != 0:
        raise RuntimeFailure('Native lab inventory requires sudo.')
    root = runtime.STATE_ROOT
    if root.is_symlink():
        raise RuntimeFailure('Refusing symlink state directory.')
    if not root.exists():
        return {'labs': [], 'scope': 'Recorded state only; no process or network liveness checks.'}
    info = root.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeFailure('State directory must be owned by root and not writable by other users.')
    rows = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if entry.is_symlink() or not entry.is_dir():
            continue
        try:
            identifier(entry.name)
        except ValueError:
            continue
        row = {'name': entry.name, 'phase': 'unknown', 'nodes': [], 'error': None}
        try:
            with runtime.Manager(entry.name).locked() as manager:
                state = manager.read()
                if state['spec']['name'] != entry.name or not isinstance(state.get('phase'), str):
                    raise ValueError('State identity or phase is invalid.')
                row['phase'] = state['phase']
                row['nodes'] = [{'name': n['name'], 'role': n['role'], 'runtime': n['runtime']} for n in state['spec']['nodes']]
        except (RuntimeFailure, OSError, ValueError, KeyError, TypeError) as error:
            row['error'] = str(error)[:500]
        rows.append(row)
    return {'labs': rows, 'scope': 'Recorded state only; no process or network liveness checks.'}


def render(report):
    lines = ['Labs natifs enregistrés (état enregistré, pas une vérification des processus) :']
    if not report['labs']:
        lines.append('Aucun état de lab trouvé.')
    for row in report['labs']:
        lines.append(json.dumps(row['name'], ensure_ascii=True) + ' [' + json.dumps(row['phase'], ensure_ascii=True) + ']')
        for node in row['nodes']:
            lines.append('  ' + json.dumps(node['name'], ensure_ascii=True) + ' — ' + json.dumps(node['role'], ensure_ascii=True))
        if row['error']:
            lines.append('  État indisponible : ' + json.dumps(row['error'], ensure_ascii=True))
    return '\n'.join(lines)
