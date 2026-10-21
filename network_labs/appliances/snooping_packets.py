"""Strict Ethernet/IPv4 DHCP observations; never infer a lease from an IP address."""
import ipaddress
import struct
import time


def checksum(data):
    if len(data) & 1:
        data += b'\0'
    value = sum(struct.unpack('!' + str(len(data) // 2) + 'H', data))
    while value >> 16:
        value = (value & 65535) + (value >> 16)
    return value


def decode(frame, *, checksum_offloaded=False):
    if len(frame) < 14 + 20 or frame[12:14] != b'\x08\x00':
        return None
    ip = frame[14:]
    ihl = (ip[0] & 15) * 4
    if ip[0] >> 4 != 4 or ihl < 20 or len(ip) < ihl + 8 or ip[9] != 17:
        return None
    if checksum(ip[:ihl]) != 65535:
        return None
    total, frag = struct.unpack_from('!H', ip, 2)[0], struct.unpack_from('!H', ip, 6)[0]
    if frag & 0x3fff or total > len(ip) or total < ihl + 8:
        return None
    udp = ip[ihl:total]
    sport, dport, size = struct.unpack_from('!HHH', udp)
    if (sport, dport) not in ((68, 67), (67, 68)) or size != len(udp) or size < 8 + 240:
        return None
    udp_checksum = struct.unpack_from('!H', udp, 6)[0]
    if udp_checksum and not checksum_offloaded:
        pseudo = ip[12:20] + struct.pack('!BBH', 0, 17, size)
        if checksum(pseudo + udp) != 65535:
            return None
    data = udp[8:size]
    if data[1:3] != b'\x01\x06' or data[3] or data[24:28] != b'\0' * 4 or data[236:240] != b'\x63\x82\x53\x63':
        return None
    mac = data[28:34]
    if mac == b'\0' * 6 or mac[0] & 1:
        return None
    options, offset, ended = {}, 240, False
    while offset < len(data):
        code = data[offset]; offset += 1
        if code == 255:
            ended = True; break
        if code == 0:
            continue
        if offset >= len(data):
            return None
        length = data[offset]; offset += 1
        if offset + length > len(data) or code in options:
            return None
        options[code] = data[offset:offset + length]; offset += length
    if not ended or 52 in options or options.get(53) not in (b'\x03', b'\x04', b'\x05', b'\x06', b'\x07'):
        return None
    for code in (50, 51, 54):
        if code in options and len(options[code]) != 4:
            return None
    op, kind = data[0], options[53][0]
    if sport == 68:
        if op != 1 or kind not in (3, 4, 7) or frame[6:12] != mac:
            return None
    elif op != 2 or kind not in (5, 6) or frame[:6] not in (mac, b'\xff' * 6) or options.get(54) != ip[12:16]:
        return None
    ipv4 = lambda b: str(ipaddress.IPv4Address(bytes(b)))
    return {'kind': kind, 'xid': struct.unpack_from('!I', data, 4)[0], 'mac': mac.hex(':'),
            'ciaddr': ipv4(data[12:16]), 'yiaddr': ipv4(data[16:20]),
            'requested': ipv4(options[50]) if 50 in options else None,
            'server': ipv4(options[54]) if 54 in options else None,
            'lease': struct.unpack('!I', options[51])[0] if 51 in options else None}


class Bindings:
    """Bounded, volatile correlations, with monotonic expiry and ambiguous-port refusal."""
    def __init__(self, ports, trusted, limit=1024):
        self.ports, self.trusted, self.limit = ports, set(trusted), limit
        self.pending, self.bindings = {}, {}
        self.events = {'requests': 0, 'acks': 0, 'untrusted_replies': 0, 'unmatched_replies': 0,
                       'capacity_refusals': 0, 'expired': 0}

    def expire(self, now):
        self.pending = {k: v for k, v in self.pending.items() if now < v['until']}
        expired = [k for k, v in self.bindings.items() if now >= v['until']]
        for key in expired:
            del self.bindings[key]
        self.events['expired'] += len(expired)

    def feed(self, port, frame, now=None, *, checksum_offloaded=False):
        now = time.monotonic() if now is None else now
        self.expire(now)
        packet = decode(frame, checksum_offloaded=checksum_offloaded)
        if packet is None or port not in self.ports:
            return
        vlan = self.ports[port]
        key = (vlan, packet['xid'], packet['mac'])
        binding_key = (vlan, packet['mac'])
        kind = packet['kind']
        if kind in (3, 4, 7):
            if port in self.trusted:
                return
            if kind == 3:
                self.events['requests'] += 1
                if key not in self.pending and len(self.pending) >= self.limit:
                    self.events['capacity_refusals'] += 1; return
                old = self.pending.get(key)
                self.pending[key] = {'port': port, 'ambiguous': bool(old and (old['port'] != port or old['ambiguous'])),
                                     'address': packet['requested'] or (packet['ciaddr'] if packet['ciaddr'] != '0.0.0.0' else None),
                                     'server': packet['server'], 'until': now + 60}
            else:
                old = self.bindings.get(binding_key)
                claimed = packet['ciaddr'] if kind == 7 else packet['requested']
                if old and old['port'] == port and old['address'] == claimed and (packet['server'] is None or packet['server'] == old['server']):
                    del self.bindings[binding_key]
                self.pending.pop(key, None)
            return
        if port not in self.trusted:
            self.events['untrusted_replies'] += 1; return
        request = self.pending.get(key)
        if not request or request['ambiguous'] or (request['server'] and request['server'] != packet['server']):
            self.events['unmatched_replies'] += 1; return
        if kind == 6:
            old = self.bindings.get(binding_key)
            if old and old['port'] == request['port']:
                del self.bindings[binding_key]
            self.pending.pop(key, None); return
        address = ipaddress.IPv4Address(packet['yiaddr'])
        if not packet['server'] or not packet['lease'] or address.is_unspecified or address.is_multicast or int(address) == 0xffffffff or (request['address'] and request['address'] != str(address)):
            return
        if binding_key not in self.bindings and len(self.bindings) >= self.limit:
            self.events['capacity_refusals'] += 1; return
        self.bindings[binding_key] = {'mac': packet['mac'], 'address': str(address), 'vlan': vlan,
                                     'port': request['port'], 'server_port': port, 'server': packet['server'],
                                     'lease_seconds': packet['lease'], 'until': now + packet['lease'],
                                     'learned_monotonic': now, 'xid': packet['xid'],
                                     'evidence': 'Observed matching client DHCPREQUEST and trusted-port DHCPACK; not proof of endpoint installation.'}
        self.pending.pop(key, None)
        self.events['acks'] += 1

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        self.expire(now)
        return {'bindings': [{**value, 'remaining_seconds': max(0, value['until'] - now)} for _, value in sorted(self.bindings.items())],
                'pending_count': len(self.pending), 'events': dict(self.events), 'capacity': self.limit}
