"""A student's progress through the guided missions, kept in a private file of their user configuration.

The file holds, per mission, the best score, whether it was solved and the hints used, plus the
micro-VM kernel and disk paths last entered. It is advisory: a missing or damaged file starts over.
"""
import json
import os
from pathlib import Path
import tempfile
import time


def path():
    base = os.environ.get('XDG_CONFIG_HOME') or str(Path.home() / '.config')
    return Path(base) / 'network-labs' / 'progress.json'


def load():
    try:
        data = json.loads(path().read_text())
    except (OSError, ValueError):
        return {'missions': {}, 'paths': {}}
    if not isinstance(data, dict):
        return {'missions': {}, 'paths': {}}
    missions = data.get('missions') if isinstance(data.get('missions'), dict) else {}
    paths = data.get('paths') if isinstance(data.get('paths'), dict) else {}
    return {'missions': missions, 'paths': {k: v for k, v in paths.items() if isinstance(v, str)}}


def _save(data):
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix='.progress-')
    try:
        with os.fdopen(handle, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=1)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def record(mission_id, passed, total, hints=0, solved=False):
    """Keep the best result of MISSION_ID; returns its entry."""
    data = load()
    entry = data['missions'].get(mission_id) if isinstance(data['missions'].get(mission_id), dict) else {}
    was_solved, used = bool(entry.get('solved')), int(entry.get('hints', hints))
    # Hints count for the best solved attempt: a later solve with fewer hints improves it, nothing else does.
    if solved and (not was_solved or hints < used):
        used = hints
    entry = {'best': max(int(entry.get('best', 0)), passed), 'total': total, 'tries': int(entry.get('tries', 0)) + 1,
             'solved': was_solved or solved, 'hints': used, 'last': time.strftime('%Y-%m-%d %H:%M')}
    data['missions'][mission_id] = entry
    try:
        _save(data)
    except OSError:
        pass  # progress is a convenience; a read-only home must not stop the lab
    return entry


def remember_paths(kernel, disk):
    data = load()
    data['paths'] = {'kernel': kernel, 'disk': disk}
    try:
        _save(data)
    except OSError:
        pass
