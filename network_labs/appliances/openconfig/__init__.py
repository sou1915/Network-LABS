"""The OpenConfig leaves Network LABS implements, as the OpenConfig YANG models define them.

catalogue.json is generated from github.com/openconfig/public at a pinned commit by tools/openconfig/generate.py
(pyang). It holds, for each leaf, its schema path, its YANG type resolved through typedefs (ranges, enum values,
identities), its default, units and description. Validation ranges, choices, defaults and help text come from
here, so the CLIs and the generated GUI pages agree with the standard model.
"""
import functools
import json
from pathlib import Path
import re

HERE = Path(__file__).parent


@functools.lru_cache(maxsize=None)
def catalogue():
    return json.loads((HERE / 'catalogue.json').read_text(encoding='utf-8'))


@functools.lru_cache(maxsize=None)
def _by_path():
    return {leaf['path']: leaf for leaf in catalogue()['leaves']}


def leaf(path):
    try:
        return _by_path()[path]
    except KeyError:
        raise KeyError(f'Not in the OpenConfig catalogue: {path}') from None


def _chain(path):
    kind = leaf(path)['type']
    return kind if isinstance(kind, list) else [kind]


def base(path):
    """The YANG built-in type at the end of the typedef chain: uint16, boolean, string, enumeration, identityref…"""
    return _chain(path)[-1]['name']


def integer_range(path):
    """(low, high) for an integer leaf: its YANG range if any, else the range of its base type."""
    limits = {'uint8': (0, 255), 'uint16': (0, 65535), 'uint32': (0, 4294967295), 'int32': (-2147483648, 2147483647)}
    chain = _chain(path)
    low, high = limits[chain[-1]['name']] if chain[-1]['name'] in limits else limits['uint32']
    for step in chain:
        if 'range' in step:
            first, _, last = step['range'].partition('..')
            low = low if first.strip() == 'min' else int(first)
            high = high if last.strip() == 'max' else int(last or first)
    return low, high


def choices(path):
    """The enum values or identities a leaf accepts (in the model's order)."""
    for step in reversed(_chain(path)):
        if 'enum' in step:
            return [e['name'] for e in step['enum']]
        if step.get('identities'):
            return list(step['identities'])
        for member in step.get('union', []):
            member = member if isinstance(member, list) else [member]
            if 'enum' in member[-1]:
                return [e['name'] for e in member[-1]['enum']]
    return []


def default(path):
    return leaf(path).get('default')


def description(path):
    return leaf(path).get('description') or ''


def short_help(path, limit=180):
    """The description's first sentence(s), cut at LIMIT characters, for tooltips and CLI help."""
    text = re.sub(r'\s+', ' ', description(path)).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(' ', 1)[0]
    return cut + '…'


def name(path):
    return path.rstrip('/').rsplit('/', 1)[-1]
