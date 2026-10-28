"""Offline FreeRADIUS 3 PAP executable/module/dictionary copy plan."""
from pathlib import Path
import re

from .dns_rootfs import assets, shared_library_assets
from .radius_server import BINARY, MODULES, DICTIONARY


def rootfs_assets(binary, modules, dictionaries):
    modules = Path(modules).resolve(); dictionaries = Path(dictionaries).resolve()
    if not (modules / 'rlm_pap.so').is_file() or not (dictionaries / 'dictionary').is_file():
        raise ValueError('FreeRADIUS requires a trusted PAP module and complete dictionary directory.')
    planned = assets(binary, destination=BINARY, identity='FreeRADIUS 3', version_args=('-v',),
                     version_check=lambda r: r.returncode == 0 and re.search(r'FreeRADIUS Version 3\.', r.stdout + r.stderr))
    planned += shared_library_assets(modules / 'rlm_pap.so', MODULES + '/rlm_pap.so')
    # Optional when building auth-only roots; accounting startup requires it.
    if (modules / 'rlm_detail.so').is_file():
        planned += shared_library_assets(modules / 'rlm_detail.so', MODULES + '/rlm_detail.so')
    # FreeRADIUS 3 loads OpenSSL's legacy provider during global startup, even
    # for PAP-only policy. dlopen providers are not enumerated by ldd.
    # Supported Debian/Ubuntu OpenSSL 3 keeps modules beside the resolved
    # libcrypto library (whose compiled MODULESDIR uses that same location).
    crypto = {Path(source).resolve() for source, target in planned if Path(target).name == 'libcrypto.so.3'}
    for library in sorted(crypto):
        provider = library.parent / 'ossl-modules/legacy.so'
        if not provider.is_file():
            raise ValueError('FreeRADIUS OpenSSL 3 requires a matching ossl-modules/legacy.so beside libcrypto.')
        planned += shared_library_assets(provider, str(provider))
    total = 0; files = []
    for path in sorted(dictionaries.rglob('*')):
        if path.is_symlink(): raise ValueError('FreeRADIUS dictionary assets must not contain symlinks.')
        if path.is_dir(): continue
        if not path.is_file(): raise ValueError('FreeRADIUS dictionary assets must be regular files.')
        total += path.stat().st_size; files.append(path)
        if len(files) > 1024 or total > 16 * 1024 * 1024:
            raise ValueError('FreeRADIUS dictionaries exceed 1024 files or 16 MiB.')
    planned += [(path, Path(DICTIONARY) / path.relative_to(dictionaries)) for path in files]
    targets = {}
    for source, target in planned:
        if target in targets and targets[target].resolve() != Path(source).resolve():
            raise ValueError('Conflicting FreeRADIUS asset destinations.')
        targets[target] = Path(source)
    return [(source, target) for target, source in sorted(targets.items())]
