"""Normalize received lldpcli JSON0 records without consulting declared links.

Contract: upstream lldpd tests/integration/test_lldpcli.py:test_json0_output.
Repeated interface entries remain repeated; system names are optional claims,
not identities resolved against our node inventory. TTL is advertised, not age.
"""
import re


def _text(value):
    return value if isinstance(value, str) and value.strip() and len(value) <= 2048 else None


def _single(value):
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError('Expected one JSON0 object.')
    return value[0]


def _id(value):
    item = _single(value)
    kind, text = _text(item.get('type')), _text(item.get('value'))
    if kind is None or text is None:
        raise ValueError('Missing advertised identifier.')
    return {'type': kind, 'value': text}


def normalize_neighbors(raw):
    """Keep unavailable/malformed input distinct from an observed empty table."""
    result = {'status': 'unknown', 'neighbors': None, 'unparsed_entries': None,
              'source': 'Received lldpcli JSON0; no declared-link or node-name resolution',
              'ttl_semantics': 'Advertised TTL seconds, not remaining lifetime or a countdown'}
    try:
        block = _single(raw['lldp'])
        if block and 'interface' not in block:
            return result
        entries = block.get('interface', [])
        if not isinstance(entries, list) or len(entries) > 4096:
            return result
    except (KeyError, TypeError, ValueError):
        return result
    rows, rejected, incomplete = [], 0, False
    for entry in entries:
        try:
            local = _text(entry.get('name'))
            if local is None or entry.get('via') != 'LLDP':
                raise ValueError('Missing local port or unsupported protocol.')
            chassis, port = _single(entry.get('chassis')), _single(entry.get('port'))
            row = {'local_port': local, 'protocol': 'LLDP', 'chassis_id': _id(chassis.get('id')),
                   'port_id': _id(port.get('id')), 'system_name': None, 'ttl_seconds': None,
                   'age': _text(entry.get('age')), 'incomplete_fields': []}
            if 'name' in chassis:
                try:
                    row['system_name'] = _text(_single(chassis['name']).get('value'))
                    if row['system_name'] is None:
                        raise ValueError('Invalid advertised name.')
                except ValueError:
                    row['incomplete_fields'].append('system_name')
            if 'ttl' in port:
                try:
                    ttl = _single(port['ttl']).get('value')
                    if not isinstance(ttl, str) or not re.fullmatch(r'[0-9]{1,5}', ttl) or int(ttl) > 65535:
                        raise ValueError('Invalid advertised TTL.')
                    row['ttl_seconds'] = int(ttl)
                except ValueError:
                    row['incomplete_fields'].append('ttl_seconds')
            else:
                row['incomplete_fields'].append('ttl_seconds')
            incomplete |= bool(row['incomplete_fields'])
            rows.append(row)
        except (AttributeError, TypeError, ValueError):
            rejected += 1
    result.update(status='partial' if rejected or incomplete else 'observed',
                  neighbors=rows, unparsed_entries=rejected)
    if rejected and not rows:
        result.update(status='unknown', neighbors=None)
    return result
