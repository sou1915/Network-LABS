"""Discover bounded local JSON manifests without exposing their contents."""
import json
import os
from pathlib import Path
import shlex
import stat

from .spec import validate

MAX_BYTES = 1024 * 1024
MAX_FILES = 200


def list_manifests(directory=None):
    root = Path.cwd() if directory is None else Path(directory)
    files = sorted((p for p in root.iterdir() if p.name.endswith('.json')), key=lambda p: p.name)
    rows = []
    for path in files[:MAX_FILES]:
        row = {'file': path.name, 'status': 'unavailable_or_invalid', 'name': None, 'nodes': []}
        descriptor = None
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise ValueError('Not a bounded regular file.')
            with os.fdopen(descriptor, 'rb') as source:
                descriptor = None
                data = source.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('File exceeds limit.')
            spec = validate(json.loads(data.decode('utf-8')))
            row.update(status='valid_manifest', name=spec['name'], nodes=[node['name'] for node in spec['nodes']])
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            pass
        finally:
            if descriptor is not None:
                os.close(descriptor)
        rows.append(row)
    return {'directory': str(root.resolve()), 'files': rows, 'truncated': len(files) > MAX_FILES,
            'scope': 'Schema validation only; assets, host prerequisites, running state and network operation are not checked.'}


def render(report):
    lines = ['Manifestes JSON dans : ' + json.dumps(report['directory'], ensure_ascii=True)]
    if not report['files']:
        lines.append('Aucun fichier JSON trouvé dans ce dossier.')
    for row in report['files']:
        filename = json.dumps(row['file'], ensure_ascii=True)
        if row['status'] != 'valid_manifest':
            lines.append(filename + ' : inaccessible ou non reconnu comme manifeste natif valide.')
            continue
        lines.append(filename + ' : lab ' + json.dumps(row['name'], ensure_ascii=True) + ' ; nodes ' + ', '.join(row['nodes']))
        if all(32 <= ord(c) < 127 for c in row['file']):
            lines.append('  Démarrer : sudo python3 -m network_labs.appliances start ' + shlex.quote('./' + row['file']))
        else:
            lines.append('  Nom non imprimable ou non ASCII : renommer le fichier avant de copier une commande.')
    if report['truncated']:
        lines.append('Liste limitée aux 200 premiers fichiers JSON.')
    lines.append('La validation du manifeste ne vérifie pas les fichiers rootfs, les dépendances ou le fonctionnement du lab.')
    return '\n'.join(lines)
