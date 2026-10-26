"""Independent bounded decoder of captured Ethernet/IPv4/UDP SNMPv3 headers.

Tests inspect USM metadata and the encrypted scoped-PDU tag, without decrypting
or implementing the production agent/client protocol.
"""
import struct


def fields(data):
    offset = 0
    while offset < len(data):
        if offset + 2 > len(data): raise ValueError('Truncated BER header')
        tag, length = data[offset:offset + 2]; offset += 2
        if length & 128:
            count = length & 127
            if not 1 <= count <= 4 or offset + count > len(data): raise ValueError('Invalid BER length')
            length = int.from_bytes(data[offset:offset + count], 'big'); offset += count
        if offset + length > len(data): raise ValueError('Truncated BER value')
        yield tag, data[offset:offset + length]; offset += length


def snmpv3(data):
    outer = list(fields(data))
    if len(outer) != 1 or outer[0][0] != 0x30: raise ValueError('Expected SNMP sequence')
    message = list(fields(outer[0][1]))
    if len(message) != 4 or message[0] != (2, b'\x03') or message[1][0] != 0x30 or message[2][0] != 4:
        raise ValueError('Expected SNMPv3 message')
    header = list(fields(message[1][1])); security = list(fields(message[2][1]))
    if len(header) != 4 or header[2][0] != 4 or len(header[2][1]) != 1 or header[3] != (2, b'\x03'):
        raise ValueError('Expected USM security model')
    if len(security) != 1 or security[0][0] != 0x30: raise ValueError('Expected USM sequence')
    usm = list(fields(security[0][1]))
    if len(usm) != 6 or [v[0] for v in usm] != [4, 2, 2, 4, 4, 4]: raise ValueError('Invalid USM fields')
    return {'flags': header[2][1][0], 'engine_id': usm[0][1], 'boots': int.from_bytes(usm[1][1], 'big'),
            'username': usm[3][1], 'auth_length': len(usm[4][1]), 'privacy_length': len(usm[5][1]),
            'data_tag': message[3][0], 'data': message[3][1]}


def captured_v3(data):
    if data[:4] != b'\xd4\xc3\xb2\xa1' or len(data) < 24 or struct.unpack_from('<I', data, 20)[0] != 1:
        raise ValueError('Expected little-endian Ethernet PCAP')
    offset = 24; result = []
    while offset < len(data):
        if offset + 16 > len(data): raise ValueError('Truncated PCAP record')
        size = struct.unpack_from('<I', data, offset + 8)[0]; offset += 16
        frame = data[offset:offset + size]; offset += size
        if len(frame) != size: raise ValueError('Truncated frame')
        if len(frame) < 42 or frame[12:14] != b'\x08\x00' or frame[14] >> 4 != 4 or frame[23] != 17: continue
        ihl = (frame[14] & 15) * 4; start = 14 + ihl
        if ihl < 20 or start + 8 > len(frame): raise ValueError('Invalid IP/UDP header')
        source, target, length = struct.unpack_from('!HHH', frame, start)
        if 161 not in (source, target): continue
        if length < 8 or start + length > len(frame): raise ValueError('Truncated UDP payload')
        result.append({'source_port': source, 'target_port': target, **snmpv3(frame[start + 8:start + length])})
    return result


def captured_notifications(data):
    """Decode v2c notification/response PDUs, retaining exact request IDs."""
    if data[:4] != b'\xd4\xc3\xb2\xa1' or len(data) < 24 or struct.unpack_from('<I', data, 20)[0] != 1:
        raise ValueError('Expected little-endian Ethernet PCAP')
    offset = 24; result = []
    while offset < len(data):
        if offset + 16 > len(data): raise ValueError('Truncated PCAP record')
        size = struct.unpack_from('<I', data, offset + 8)[0]; offset += 16
        frame = data[offset:offset + size]; offset += size
        if len(frame) != size: raise ValueError('Truncated frame')
        if len(frame) < 42 or frame[12:14] != b'\x08\x00' or frame[14] >> 4 != 4 or frame[23] != 17: continue
        start = 14 + (frame[14] & 15) * 4
        if start < 34 or start + 8 > len(frame): raise ValueError('Invalid IP/UDP header')
        source, target, length = struct.unpack_from('!HHH', frame, start)
        if 162 not in (source, target): continue
        if length < 8 or start + length > len(frame): raise ValueError('Truncated UDP payload')
        outer = list(fields(frame[start + 8:start + length]))
        if len(outer) != 1 or outer[0][0] != 0x30: raise ValueError('Invalid SNMP sequence')
        message = list(fields(outer[0][1]))
        if len(message) != 3 or message[0] != (2, b'\x01'): continue
        if message[1][0] != 4 or message[2][0] not in (0xa2, 0xa6, 0xa7): raise ValueError('Invalid v2c notification/response')
        pdu = list(fields(message[2][1]))
        if len(pdu) != 4 or [v[0] for v in pdu] != [2, 2, 2, 0x30]: raise ValueError('Invalid notification PDU')
        result.append({'source_port': source, 'target_port': target, 'source_ip': '.'.join(map(str, frame[26:30])),
                       'community': message[1][1], 'pdu_tag': message[2][0],
                       'request_id': int.from_bytes(pdu[0][1], 'big', signed=True),
                       'error_status': int.from_bytes(pdu[1][1], 'big'), 'varbinds': pdu[3][1]})
    return result
