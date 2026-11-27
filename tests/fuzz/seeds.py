"""Seed inputs for agent_fuzz.c: one well-formed message per handler (first byte: the handler, second: the state)."""
import socket
import struct


def checksum(data):
    if len(data) % 2:
        data += b'\0'
    total = sum(struct.unpack(f'!{len(data) // 2}H', data))
    while total >> 16:
        total = (total & 0xffff) + (total >> 16)
    return ~total & 0xffff


def ipv4(protocol, source, destination, payload, ttl=1):
    header = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(payload), 0, 0, ttl, protocol, 0, socket.inet_aton(source),
                         socket.inet_aton(destination))
    header = header[:10] + struct.pack('!H', checksum(header)) + header[12:]
    return b'\x01\x00\x5e\x00\x00\x02' + b'\x00\x00\x0c\x07\xac\x01' + b'\x08\x00' + header + payload


def hsrp_v1(state=16, priority=120, op=0):
    message = struct.pack('!BBBBBBBB8s4s', 0, op, state, 3, 10, priority, 1, 0, b'cisco\0\0\0', socket.inet_aton('192.168.1.1'))
    udp = struct.pack('!HHHH', 1985, 1985, 8 + len(message), 0) + message
    return ipv4(17, '192.168.1.3', '224.0.0.2', udp)


def hsrp_v2(state=6, priority=120, op=0):
    group = struct.pack('!BBBBBBH6sIII16s', 1, 40, 2, op, state, 4, 4095, b'\x00\x00\x0c\x9f\xff\xff', priority, 1000, 4000,
                        socket.inet_aton('10.0.0.1') + bytes(12))
    auth = struct.pack('!BB8s', 3, 8, b'lab\0\0\0\0\0')
    message = group + auth
    udp = struct.pack('!HHHH', 1985, 1985, 8 + len(message), 0) + message
    return ipv4(17, '10.0.0.3', '224.0.0.102', udp)


def vrrp(vrid=1, priority=150, password=b''):
    authtype = 1 if password else 0
    message = struct.pack('!BBBBBBH4s8s', 0x21, vrid, priority, 1, authtype, 1, 0, socket.inet_aton('192.168.1.254'),
                          password.ljust(8, b'\0'))
    message = message[:6] + struct.pack('!H', checksum(message)) + message[8:]
    return ipv4(112, '192.168.1.3', '224.0.0.18', message, ttl=255)


def dns(name, qtype=1):
    labels = b''.join(bytes([len(part)]) + part.encode() for part in name.split('.')) + b'\0'
    return struct.pack('!HHHHHH', 0x1234, 0x0100, 1, 0, 0, 0) + labels + struct.pack('!HH', qtype, 1)


def seeds():
    found = {
        'hsrp-v1-active': b'\0\4' + hsrp_v1(), 'hsrp-v1-coup': b'\0\4' + hsrp_v1(op=1), 'hsrp-v1-standby': b'\0\3' + hsrp_v1(state=8),
        'hsrp-v2-active': b'\1\4' + hsrp_v2(), 'hsrp-v2-resign': b'\1\2' + hsrp_v2(op=2),
        'vrrp-master': b'\2\1' + vrrp(), 'vrrp-resign': b'\2\2' + vrrp(priority=0),
        'vrrp-password': b'\3\1' + vrrp(vrid=7, password=b'secret'),
        'guard-frame': b'\4\0' + b'\xff' * 6 + b'\x02\x00\x00\x00\x00\x09\x08\x06' + bytes(28),
        'guard-bpdu': b'\4\1' + b'\x01\x80\xc2\x00\x00\x00\x02\x00\x00\x00\x00\x09\x00\x26' + bytes(38),
        'dns-a': b'\5\0' + dns('www.lab'), 'dns-cname': b'\5\0' + dns('web', 255),
        'dns-ptr': b'\5\0' + dns('10.2.0.192.in-addr.arpa', 12),
        'syslog': b'\6\0<34>Oct 11 22:14:15 R1 %LINK-3-UPDOWN: Interface eth0, changed state to up',
        'tftp-read': b'\7\0\0\1config.txt\0octet\0', 'tftp-write': b'\7\0\0\2backup-r1.cfg\0NETASCII\0',
        'hsrp-spec': b'\x08\0eth0/1/1/192.168.1.1/110/y/3/10/636973636f',
        'vrrp-spec': b'\x08\1eth0.20/12/10.0.20.254/100/y/1/-', 'guard-spec': b'\x08\2eth3/3/r/y/n/10/020000000001',
        'services': b'\x09\0dns a:www.lab=192.0.2.10 cname:web=www.lab ntp:3 syslog tftp sync:192.0.2.1',
        'bgp': b'\x0a\0' + b'65001 1.1.1.1 10.0.0.2:65002,10.0.1.2:65003 10.1.0.0/24,10.2.0.0/16',
        'eigrp': b'\x0a\1' + b'100 1.1.1.1 10.0.0.0/24,10.1.0.0/24 eth1',
        'ospf': b'\x0a\2' + b'1.1.1.1 10 40 eth0:0:10,eth1:0:10',
        'rip': b'\x0a\3' + b'1.1.1.1 2 eth0,eth1',
    }
    return found
