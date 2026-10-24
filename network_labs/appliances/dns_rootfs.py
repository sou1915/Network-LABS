"""Offline copy plan for a trusted local service executable and its ELF dependencies."""
import os
from pathlib import Path
import re
import struct
import subprocess


def assets(binary, *, destination='/usr/sbin/dnsmasq', identity='dnsmasq version ', version_args=('--version',), version_check=None):
    binary = Path(binary).resolve()
    raw = binary.read_bytes()
    if len(raw) < 64 or raw[:4] != b'\x7fELF' or raw[4] not in (1, 2) or raw[5] not in (1, 2):
        raise ValueError('Trusted host service must be an ELF executable.')
    version = subprocess.run([str(binary), *version_args], text=True, capture_output=True, timeout=5)
    accepted = version_check(version) if version_check is not None else (version.returncode == 0 and version.stdout.lower().startswith(identity))
    if not accepted:
        raise ValueError('The trusted binary did not identify itself as ' + identity.strip() + '.')
    endian, is64 = ('<' if raw[5] == 1 else '>'), raw[4] == 2
    offset = struct.unpack_from(endian + ('Q' if is64 else 'I'), raw, 32 if is64 else 28)[0]
    size, count = struct.unpack_from(endian + 'HH', raw, 54 if is64 else 42)
    if size < (56 if is64 else 32) or offset + count * size > len(raw):
        raise ValueError('Malformed service ELF program header table.')
    interpreters = []
    for index in range(count):
        header = offset + index * size
        if struct.unpack_from(endian + 'I', raw, header)[0] == 3:
            start = struct.unpack_from(endian + ('Q' if is64 else 'I'), raw, header + (8 if is64 else 4))[0]
            length = struct.unpack_from(endian + ('Q' if is64 else 'I'), raw, header + (32 if is64 else 16))[0]
            if start + length > len(raw):
                raise ValueError('Malformed ELF interpreter.')
            interpreters.append(Path(raw[start:start + length].rstrip(b'\0').decode()))
    planned = {Path(destination): binary}
    if interpreters:
        environment = {k: v for k, v in os.environ.items() if k not in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'LD_AUDIT')}
        result = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, timeout=10, env={**environment, 'LC_ALL': 'C'})
        if result.returncode or 'not found' in result.stdout:
            raise ValueError('Cannot resolve all trusted service shared libraries with host ldd.')
        libraries = [Path(match) for match in re.findall(r'(?:=>\s+|^\s*)(/[^\s()]+)', result.stdout, re.MULTILINE)]
        for path in interpreters + libraries:
            if not path.is_absolute() or '..' in path.parts or not path.is_file():
                raise ValueError('DNS ELF dependency is not an existing absolute file: ' + str(path))
            planned[path] = path.resolve()
        if not libraries:
            raise ValueError('No dynamic service libraries were resolved.')
    return sorted(((source, target) for target, source in planned.items()), key=lambda pair: str(pair[1]))
